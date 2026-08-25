"""Enrollments — API service."""

from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment_access import AssignmentAccessCredential
from app.models.courses import Course
from app.models.enrollment import Enrollment
from app.models.enrollment_access_policy import EnrollmentAccessPolicy
from app.models.users import User, UserInvitation
from app.modules.courses.release_service import ensure_course_release
from app.modules.enrollments.notification_outbox import (
    PostgresAssignmentNotificationStore,
    queue_manual_enrollment_notification,
)


async def get_enrolled_users(db: AsyncSession, course_id: UUID, tenant_id: UUID):
    """List users enrolled in a course."""
    course_exists = await db.scalar(
        select(Course.id).where(
            Course.id == course_id,
            Course.tenant_id == tenant_id,
        )
    )
    if course_exists is None:
        raise ValueError("Course not found")

    result = await db.execute(
        select(Enrollment).where(
            Enrollment.course_id == course_id,
            Enrollment.tenant_id == tenant_id,
        )
    )
    enrollments = list(result.scalars().all())
    statuses = await PostgresAssignmentNotificationStore(db).statuses(tenant_id=tenant_id, course_id=course_id)
    for enrollment in enrollments:
        delivery = statuses.get(enrollment.id)
        enrollment.notification_status = delivery.status if delivery else None
        enrollment.notification_attempt_count = delivery.attempt_count if delivery else 0
        enrollment.notification_delivered_at = delivery.delivered_at if delivery else None
        enrollment.notification_error = delivery.last_error_category if delivery else None
    return enrollments


async def get_enrollment_access(
    db: AsyncSession, enrollment_id: UUID, tenant_id: UUID, *, base_url: str | None
) -> dict | None:
    """Return the durable access state for an assigned learner.

    Account activation is intentionally separate from course-assignment
    notification.  The current product has no secure second factor for
    employees without email, so this endpoint must fail closed instead of
    delegating to the personnel-number kiosk flow.
    """
    result = await db.execute(
        select(Enrollment, User)
        .join(User, User.id == Enrollment.user_id)
        .where(Enrollment.id == enrollment_id, Enrollment.tenant_id == tenant_id)
    )
    row = result.one_or_none()
    if row is None:
        return None
    enrollment, learner = row

    from app.models.enrollment_access_policy import EnrollmentAccessPolicy

    policy = await db.scalar(
        select(EnrollmentAccessPolicy).where(
            EnrollmentAccessPolicy.enrollment_id == enrollment.id,
            EnrollmentAccessPolicy.tenant_id == tenant_id,
        )
    )

    has_email = bool((learner.email or "").strip())
    if (policy is not None and policy.delivery_mode == "personal_link") or not has_email:
        from app.models.assignment_access import AssignmentAccessCredential

        active_credential = await db.execute(
            select(AssignmentAccessCredential.id, AssignmentAccessCredential.expires_at).where(
                AssignmentAccessCredential.enrollment_id == enrollment.id,
                AssignmentAccessCredential.revoked_at.is_(None),
                AssignmentAccessCredential.expires_at > func.now(),
            )
        )
        credential_row = active_credential.one_or_none()
        return {
            "enrollment_id": enrollment.id,
            "user_id": learner.id,
            "access_kind": "personal_link" if has_email else "access_without_email",
            "state": "available" if credential_row else "blocked",
            "access_url": None,
            "expires_at": credential_row[1] if credential_row else None,
            "message": (
                "A protected link and PIN can be issued for this learner."
                if not credential_row
                else "A protected link is active. Reissue to revoke it and create a new PIN."
            ),
        }

    base = (base_url or "https://app.kml.kz").rstrip("/")
    if learner.has_login_access:
        return {
            "enrollment_id": enrollment.id,
            "user_id": learner.id,
            "access_kind": "course_access",
            "state": "available",
            "access_url": f"{base}/courses/{enrollment.course_id}",
            "expires_at": None,
            "message": "The learner can open the assigned course with the existing account.",
        }

    invitation = await db.scalar(
        select(UserInvitation)
        .where(
            UserInvitation.tenant_id == tenant_id,
            UserInvitation.user_id == learner.id,
            UserInvitation.status == "pending",
            UserInvitation.expires_at > func.now(),
        )
        .order_by(UserInvitation.created_at.desc())
        .limit(1)
    )
    if invitation is None:
        return {
            "enrollment_id": enrollment.id,
            "user_id": learner.id,
            "access_kind": "account_activation",
            "state": "needs_activation",
            "access_url": None,
            "message": "Account activation has not been prepared. Course notification is separate.",
        }

    return {
        "enrollment_id": enrollment.id,
        "user_id": learner.id,
        "access_kind": "account_activation",
        "state": "available",
        "access_url": f"{base}/accept-invite?token={invitation.token}",
        "expires_at": invitation.expires_at,
        "message": "Copy the activation link or create a fresh one if it has expired.",
    }


async def enroll_users(
    db: AsyncSession,
    course_id: UUID,
    tenant_id: UUID,
    user_ids: list[UUID],
    *,
    assigned_by: UUID | None = None,
    delivery_mode: str = "email",
    link_expires_at=None,
    completion_window_minutes: int | None = None,
    due_at=None,
):
    """Bulk enroll users with tenant + status validation (P1-5).

    Per TZ §7 P1-5: pre-fix code didn't validate that the user
    belongs to the caller's tenant or that the user is active.
    Both checks happen here. The DB-level unique constraint
    is the race-safe backstop (see migration 0040); the
    application check is the fast path.

    Silently skips:
      - users not found (could be a typo'd id; no 4xx — the UI
        is bulk-friendly and partial success is the model)
      - users from a different tenant (defense in depth — the
        router should have caught this, but if it didn't, we
        refuse to insert a cross-tenant Enrollment row)
      - users whose role is not `student`; system/team users are
        managed via /admin/team and must not become learners by
        accidental assignment
      - users that aren't `is_active=True` AND `status='active'`
      - users already enrolled in this course
    """
    if not user_ids:
        return []

    course = await db.scalar(
        select(Course).where(
            Course.id == course_id,
            Course.tenant_id == tenant_id,
        )
    )
    if course is None:
        raise ValueError("Course not found")
    if course.status != "published":
        raise ValueError("Course must be published before assignment")
    release = await ensure_course_release(db, course)

    # 1 round-trip: load all candidate users with their status
    # + tenant. We do this in one query (not N+1) so the cost
    # is constant for any batch size.
    users_result = await db.execute(
        select(User).where(
            User.id.in_(user_ids),
        )
    )
    users_by_id: dict[UUID, User] = {u.id: u for u in users_result.scalars().all()}

    enrollments: list[Enrollment] = []
    for uid in user_ids:
        user = users_by_id.get(uid)
        if user is None:
            # User id doesn't exist at all — skip silently.
            continue
        # Tenant check (defense in depth — router should filter
        # by tenant, but a bug there would leak cross-tenant).
        if user.tenant_id != tenant_id:
            continue
        if user.role != "student":
            continue
        # Active check: is_active AND status='active' are both
        # required. is_active is the boolean convenience flag;
        # status is the source of truth (e.g. 'suspended' is
        # not 'inactive' in the boolean sense but the user
        # must not be enrolled).
        if not user.is_active or user.status != "active":
            continue

        # Duplicate check (fast path; the DB constraint is
        # the race-safe backstop).
        existing = await db.execute(
            select(Enrollment).where(
                Enrollment.course_id == course_id,
                Enrollment.user_id == uid,
                Enrollment.tenant_id == tenant_id,
                Enrollment.recurring_assignment_id.is_(None),
            )
        )
        if existing.scalar_one_or_none():
            continue

        enrollment = Enrollment(
            id=uuid4(),
            course_id=course_id,
            user_id=uid,
            tenant_id=tenant_id,
            content_release_id=release.id,
            status="enrolled",
            source="manual",
        )
        db.add(enrollment)
        enrollments.append(enrollment)

    if enrollments:
        await db.flush()
        from app.modules.enrollments.access_service import upsert_access_policy

        for enrollment in enrollments:
            learner = users_by_id[enrollment.user_id]
            await upsert_access_policy(
                db,
                enrollment=enrollment,
                delivery_mode=delivery_mode,
                link_expires_at=link_expires_at,
                completion_window_minutes=completion_window_minutes,
                due_at=due_at,
            )
            if delivery_mode == "personal_link":
                # The methodologist explicitly chose a copied secure link, so
                # no invitation/outbox email is prepared for this enrollment.
                continue
            if assigned_by is None:
                continue
            if learner.email and learner.email.strip() and not learner.has_login_access:
                from app.core.config import get_settings
                from app.modules.users.invitations_service import prepare_user_invitation

                await prepare_user_invitation(
                    db,
                    tenant_id,
                    assigned_by,
                    learner.id,
                    get_settings().PUBLIC_URL,
                    reuse_valid=True,
                )
            notification_id = await queue_manual_enrollment_notification(
                db,
                tenant_id=tenant_id,
                enrollment_id=enrollment.id,
                assigned_by=assigned_by,
            )
            enrollment.notification_outbox_id = notification_id
    return enrollments


async def resend_enrollment_notification(db: AsyncSession, *, tenant_id: UUID, enrollment_id: UUID) -> UUID | None:
    enrollment = await db.scalar(
        select(Enrollment.id).where(
            Enrollment.id == enrollment_id,
            Enrollment.tenant_id == tenant_id,
            Enrollment.source.in_(("manual", "recurring")),
        )
    )
    if enrollment is None:
        return None
    return await PostgresAssignmentNotificationStore(db).requeue(tenant_id=tenant_id, enrollment_id=enrollment_id)


async def self_enroll(db: AsyncSession, course_id: UUID, user_id: UUID, tenant_id: UUID):
    """Self-enrollment — student enrolls themselves in a course."""
    # Check course exists and is published
    course_result = await db.execute(select(Course).where(Course.id == course_id, Course.tenant_id == tenant_id))
    course = course_result.scalar_one_or_none()
    if not course:
        raise ValueError("Course not found")
    if course.status != "published":
        raise ValueError("Course is not published")
    release = await ensure_course_release(db, course)

    # Check for existing enrollment
    existing = await db.execute(
        select(Enrollment).where(
            Enrollment.course_id == course_id,
            Enrollment.user_id == user_id,
            Enrollment.tenant_id == tenant_id,
            Enrollment.recurring_assignment_id.is_(None),
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("Already enrolled in this course")

    enrollment = Enrollment(
        id=uuid4(),
        course_id=course_id,
        user_id=user_id,
        tenant_id=tenant_id,
        content_release_id=release.id,
        status="enrolled",
    )
    db.add(enrollment)
    await db.flush()
    return enrollment


async def unenroll(db: AsyncSession, enrollment_id: UUID, tenant_id: UUID) -> None:
    result = await db.execute(
        select(Enrollment).where(Enrollment.id == enrollment_id, Enrollment.tenant_id == tenant_id)
    )
    enrollment = result.scalar_one_or_none()
    if enrollment:
        if enrollment.source != "manual":
            raise ValueError("Rule-driven enrollments must be changed through department or position rules")
        await db.execute(
            delete(AssignmentAccessCredential).where(
                AssignmentAccessCredential.enrollment_id == enrollment.id,
                AssignmentAccessCredential.tenant_id == tenant_id,
            )
        )
        await db.execute(
            delete(EnrollmentAccessPolicy).where(
                EnrollmentAccessPolicy.enrollment_id == enrollment.id,
                EnrollmentAccessPolicy.tenant_id == tenant_id,
            )
        )
        await db.delete(enrollment)


async def get_course_enrollment_stats(db: AsyncSession, course_id: UUID, tenant_id: UUID) -> dict:
    """Get enrollment statistics for a course."""
    total_result = await db.execute(
        select(func.count(Enrollment.id)).where(
            Enrollment.course_id == course_id,
            Enrollment.tenant_id == tenant_id,
        )
    )
    total = total_result.scalar() or 0

    completed_result = await db.execute(
        select(func.count(Enrollment.id)).where(
            Enrollment.course_id == course_id,
            Enrollment.tenant_id == tenant_id,
            Enrollment.status == "completed",
        )
    )
    completed = completed_result.scalar() or 0

    return {
        "course_id": str(course_id),
        "total_enrolled": total,
        "completed": completed,
        "in_progress": total - completed,
    }
