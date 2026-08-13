"""Enrollments — API router"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_role, require_tenant_user
from app.core.db import get_db
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.enrollments.schemas import (
    AssignmentAccessExchangeRequest,
    AssignmentAccessExchangeResponse,
    AssignmentAccessIssueResponse,
    EnrollmentAccessPolicyExtendRequest,
    EnrollmentAccessPolicyRequest,
    EnrollmentAccessPolicyResponse,
    EnrollmentAccessPolicyRevokeRequest,
    EnrollmentAccessResponse,
    EnrollmentCreate,
    EnrollmentNotificationResponse,
    EnrollmentResponse,
    PersonalLinkEnrollmentCreate,
)
from app.modules.enrollments.service import (
    enroll_users,
    get_course_enrollment_stats,
    get_enrolled_users,
    get_enrollment_access,
    resend_enrollment_notification,
    self_enroll,
    unenroll,
)

router = APIRouter(
    prefix="/courses",
    tags=["enrollments"],
    dependencies=[Depends(require_tenant_user())],
)
public_access_router = APIRouter(prefix="/assignment-access", tags=["assignment-access"])

stats_router = APIRouter(prefix="/enrollments", tags=["enrollments"])


@stats_router.get("/stats")
async def global_enrollment_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Global enrollment statistics for dashboard."""
    total_result = await db.execute(select(func.count(Enrollment.id)).where(Enrollment.tenant_id == user.tenant_id))
    total = total_result.scalar() or 0

    completed_result = await db.execute(
        select(func.count(Enrollment.id)).where(
            Enrollment.tenant_id == user.tenant_id,
            Enrollment.status == "completed",
        )
    )
    completed = completed_result.scalar() or 0

    return {"total": total, "completed": completed}


# Direct user→course assignment is a learning-content/methodologist
# concern (TZ_COURSE_ASSIGNMENT_ACCESS_v1 §1.2 level-4 manual override),
# not tenant administration. Tenant admins manage org/team structure;
# methodologist manages learning trajectories. Students keep the
# self-enrollment path below; everyone else is rejected.

_ENROLLMENT_MANAGER_ROLES = ("methodologist",)


@router.get("/{course_id}/enrollments", response_model=list[EnrollmentResponse])
async def list_enrollments(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    try:
        return await get_enrolled_users(db, course_id, user.tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{course_id}/enrollments", response_model=list[EnrollmentResponse], status_code=201)
async def create_enrollments(
    course_id: UUID,
    req: EnrollmentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    try:
        enrollments = await enroll_users(
            db,
            course_id,
            user.tenant_id,
            req.user_ids,
            assigned_by=user.id,
            delivery_mode=req.delivery_mode,
            link_expires_at=req.link_expires_at,
            completion_window_minutes=req.completion_window_minutes,
            due_at=req.due_at,
        )
        await db.commit()
        from app.modules.enrollments.notification_tasks import deliver_assignment_notification_task

        for enrollment in enrollments:
            if req.delivery_mode == "personal_link":
                continue
            notification_id = getattr(enrollment, "notification_outbox_id", None)
            if notification_id is not None:
                try:
                    deliver_assignment_notification_task.apply_async(args=[str(user.tenant_id), str(notification_id)])
                except Exception:
                    # The committed outbox remains recoverable by the timer.
                    pass
        return enrollments
    except ValueError as exc:
        status_code = 409 if "published" in str(exc) else 404
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.post(
    "/{course_id}/personal-link-enrollment",
    response_model=AssignmentAccessIssueResponse,
    status_code=201,
)
async def create_personal_link_enrollment(
    course_id: UUID,
    req: PersonalLinkEnrollmentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    """Atomically create an enrollment and its copyable personal-link PIN.

    This avoids the unsafe two-request gap between enrolling a learner and
    issuing their chosen delivery credential.  It never prepares an email
    invitation or notification outbox row.
    """
    from app.core.config import get_settings
    from app.modules.enrollments.access_service import issue_assignment_access

    try:
        enrollments = await enroll_users(
            db,
            course_id,
            user.tenant_id,
            [req.user_id],
            assigned_by=user.id,
            delivery_mode="personal_link",
            link_expires_at=req.link_expires_at,
            completion_window_minutes=req.completion_window_minutes,
            due_at=req.due_at,
        )
        if len(enrollments) != 1:
            raise ValueError("Learner could not be enrolled for personal-link delivery")
        issued = await issue_assignment_access(
            db,
            enrollments[0].id,
            user.tenant_id,
            getattr(get_settings(), "PUBLIC_URL", None),
            link_expires_at=req.link_expires_at,
            completion_window_minutes=req.completion_window_minutes,
            due_at=req.due_at,
            allow_email=True,
        )
        if issued is None:
            raise ValueError("Personal access credential could not be issued")
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        status_code = 409 if "published" in str(exc) or "could not" in str(exc) else 404
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except Exception:
        await db.rollback()
        raise
    return issued


@router.get("/enrollments/{enrollment_id}/access", response_model=EnrollmentAccessResponse)
async def enrollment_access(
    enrollment_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    """Retrieve assignment access without coupling it to assignment creation."""
    from app.core.config import get_settings

    access = await get_enrollment_access(
        db,
        enrollment_id,
        user.tenant_id,
        base_url=getattr(get_settings(), "PUBLIC_URL", None),
    )
    if access is None:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    return access


@router.post(
    "/enrollments/{enrollment_id}/notification/resend",
    response_model=EnrollmentNotificationResponse,
)
async def resend_assignment_notification(
    enrollment_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    notification_id = await resend_enrollment_notification(db, tenant_id=user.tenant_id, enrollment_id=enrollment_id)
    if notification_id is None:
        raise HTTPException(status_code=404, detail="Assignment notification not found")
    from app.modules.enrollments.notification_tasks import deliver_assignment_notification_task

    try:
        deliver_assignment_notification_task.apply_async(args=[str(user.tenant_id), str(notification_id)])
    except Exception:
        pass
    return EnrollmentNotificationResponse(enrollment_id=enrollment_id, notification_id=notification_id)


@router.post("/enrollments/{enrollment_id}/access-without-email", response_model=AssignmentAccessIssueResponse)
async def issue_access_without_email(
    enrollment_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    from app.core.config import get_settings
    from app.modules.enrollments.access_service import (
        AssignmentAccessWindowAlreadyStartedError,
        issue_assignment_access,
    )

    try:
        issued = await issue_assignment_access(
            db, enrollment_id, user.tenant_id, getattr(get_settings(), "PUBLIC_URL", None)
        )
    except AssignmentAccessWindowAlreadyStartedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "assignment_window_already_started",
                "message": "Started access cannot be reissued; use extend or revoke with a reason",
            },
        ) from exc
    if issued is None:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    from app.modules.audit.service import log_action

    await log_action(
        db,
        user.tenant_id,
        "issue",
        "assignment_access_link",
        resource_id=enrollment_id,
        user_id=user.id,
        details={"delivery_mode": "personal_link", "reissue": True},
    )
    return issued


@router.put("/enrollments/{enrollment_id}/access-policy", response_model=EnrollmentAccessPolicyResponse)
async def put_enrollment_access_policy(
    enrollment_id: UUID,
    req: EnrollmentAccessPolicyRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    from datetime import UTC, datetime

    from app.models.assignment_access import AssignmentAccessCredential
    from app.modules.enrollments.access_service import access_policy_payload, get_access_policy, upsert_access_policy

    enrollment = await db.scalar(
        select(Enrollment).where(Enrollment.id == enrollment_id, Enrollment.tenant_id == user.tenant_id)
    )
    if enrollment is None or enrollment.status not in {"enrolled", "in_progress"}:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    previous_policy = await get_access_policy(db, enrollment_id=enrollment_id, tenant_id=user.tenant_id, lock=True)
    if previous_policy is not None and previous_policy.completion_window_started_at is not None:
        changing_started_link_policy = req.delivery_mode == "personal_link" and any(
            (
                req.link_expires_at != previous_policy.link_expires_at,
                req.completion_window_minutes != previous_policy.completion_window_minutes,
                req.due_at != previous_policy.due_at,
            )
        )
        if changing_started_link_policy:
            raise HTTPException(
                status_code=409,
                detail="Started personal-link policy cannot be replaced; use extend, revoke, or reissue",
            )
    # Changing an enrollment back to ordinary email delivery must revoke the
    # credential that minted any assignment-access bearer.  Authentication
    # revalidates this field on every request, so the switch is immediately
    # effective without waiting for the JWT to expire.
    switching_to_email = (
        previous_policy is not None
        and previous_policy.delivery_mode == "personal_link"
        and req.delivery_mode == "email"
    )
    if switching_to_email:
        now = datetime.now(UTC)
        credentials = await db.scalars(
            select(AssignmentAccessCredential)
            .where(
                AssignmentAccessCredential.enrollment_id == enrollment_id,
                AssignmentAccessCredential.tenant_id == user.tenant_id,
                AssignmentAccessCredential.revoked_at.is_(None),
            )
            .with_for_update()
        )
        for credential in credentials:
            credential.revoked_at = now
            credential.revoked_reason = "delivery_mode_changed_to_email"
    policy = await upsert_access_policy(
        db,
        enrollment=enrollment,
        delivery_mode=req.delivery_mode,
        link_expires_at=req.link_expires_at,
        completion_window_minutes=req.completion_window_minutes,
        due_at=req.due_at,
    )
    return access_policy_payload(policy)


@router.post("/enrollments/{enrollment_id}/access-link", response_model=AssignmentAccessIssueResponse)
async def issue_personal_access_link(
    enrollment_id: UUID,
    req: EnrollmentAccessPolicyRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    from app.core.config import get_settings
    from app.modules.enrollments.access_service import (
        AssignmentAccessWindowAlreadyStartedError,
        issue_assignment_access,
    )

    if req.delivery_mode != "personal_link":
        raise HTTPException(status_code=422, detail="Personal access link requires delivery_mode=personal_link")
    try:
        issued = await issue_assignment_access(
            db,
            enrollment_id,
            user.tenant_id,
            getattr(get_settings(), "PUBLIC_URL", None),
            link_expires_at=req.link_expires_at,
            completion_window_minutes=req.completion_window_minutes,
            due_at=req.due_at,
            allow_email=True,
        )
    except AssignmentAccessWindowAlreadyStartedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "assignment_window_already_started",
                "message": "Started access cannot be reissued; use extend or revoke with a reason",
            },
        ) from exc
    if issued is None:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    return issued


@router.post("/enrollments/{enrollment_id}/access-policy/extend", response_model=EnrollmentAccessPolicyResponse)
async def extend_enrollment_access_policy(
    enrollment_id: UUID,
    req: EnrollmentAccessPolicyExtendRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    from app.modules.enrollments.access_service import access_policy_payload, get_access_policy

    policy = await get_access_policy(db, enrollment_id=enrollment_id, tenant_id=user.tenant_id, lock=True)
    if policy is None:
        raise HTTPException(status_code=404, detail="Enrollment access policy not found")
    if req.link_expires_at is not None:
        policy.link_expires_at = req.link_expires_at
        from app.models.assignment_access import AssignmentAccessCredential

        credentials = await db.scalars(
            select(AssignmentAccessCredential)
            .where(
                AssignmentAccessCredential.enrollment_id == enrollment_id,
                AssignmentAccessCredential.tenant_id == user.tenant_id,
                AssignmentAccessCredential.revoked_at.is_(None),
            )
            .with_for_update()
        )
        for credential in credentials:
            credential.expires_at = req.link_expires_at
    if req.completion_window_minutes is not None:
        policy.completion_window_minutes = req.completion_window_minutes
        if policy.completion_window_started_at is not None:
            # An operator-approved extension takes effect immediately for the
            # already-issued bearer. Never clear the active deadline and wait
            # for another PIN exchange, because that would create an
            # unrestricted interval.
            from datetime import UTC, datetime, timedelta

            policy.completion_window_expires_at = datetime.now(UTC) + timedelta(minutes=req.completion_window_minutes)
    if req.due_at is not None:
        policy.due_at = req.due_at
    policy.revoked_at = None
    policy.revoked_reason = None
    await db.flush()
    from app.modules.audit.service import log_action

    await log_action(
        db,
        user.tenant_id,
        "extend",
        "enrollment_access_policy",
        resource_id=enrollment_id,
        user_id=user.id,
        details={
            "reason": req.reason,
            "link_expires_at": req.link_expires_at.isoformat() if req.link_expires_at else None,
            "completion_window_minutes": req.completion_window_minutes,
            "due_at": req.due_at.isoformat() if req.due_at else None,
        },
    )
    return access_policy_payload(policy)


@router.post("/enrollments/{enrollment_id}/access-policy/revoke", response_model=EnrollmentAccessPolicyResponse)
async def revoke_enrollment_access_policy(
    enrollment_id: UUID,
    req: EnrollmentAccessPolicyRevokeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    from datetime import UTC, datetime

    from app.models.assignment_access import AssignmentAccessCredential
    from app.modules.enrollments.access_service import access_policy_payload, get_access_policy

    policy = await get_access_policy(db, enrollment_id=enrollment_id, tenant_id=user.tenant_id, lock=True)
    if policy is None:
        raise HTTPException(status_code=404, detail="Enrollment access policy not found")
    now = datetime.now(UTC)
    policy.revoked_at = now
    policy.revoked_reason = req.reason
    credentials = await db.scalars(
        select(AssignmentAccessCredential)
        .where(
            AssignmentAccessCredential.enrollment_id == enrollment_id,
            AssignmentAccessCredential.tenant_id == user.tenant_id,
            AssignmentAccessCredential.revoked_at.is_(None),
        )
        .with_for_update()
    )
    for credential in credentials:
        credential.revoked_at = now
        credential.revoked_reason = f"policy_revoked:{req.reason}"
    await db.flush()
    from app.modules.audit.service import log_action

    await log_action(
        db,
        user.tenant_id,
        "revoke",
        "enrollment_access_policy",
        resource_id=enrollment_id,
        user_id=user.id,
        details={"reason": req.reason},
    )
    return access_policy_payload(policy)


@public_access_router.post("/{token}/exchange", response_model=AssignmentAccessExchangeResponse)
async def exchange_access_without_email(
    token: str, payload: AssignmentAccessExchangeRequest, db: AsyncSession = Depends(get_db)
):
    from app.modules.enrollments.access_service import establish_assignment_access_context, exchange_assignment_access

    tenant_id = await establish_assignment_access_context(db, token)
    if tenant_id is None:
        # Do not distinguish random, expired, revoked, or cross-tenant links.
        raise HTTPException(status_code=404, detail="Access link not found")
    from sqlalchemy import text

    await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)})
    from app.modules.enrollments.access_service import AssignmentWindowExpiredError, assignment_window_error

    try:
        result = await exchange_assignment_access(db, token, payload.pin)
    except AssignmentWindowExpiredError as exc:
        raise assignment_window_error(exc) from exc
    if result is None:
        raise HTTPException(status_code=401, detail="Access link or PIN is invalid")
    return result


@router.post("/{course_id}/enroll", response_model=EnrollmentResponse, status_code=201)
async def enroll_self(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Self-enrollment — student enrolls themselves in a course."""
    try:
        return await self_enroll(db, course_id, user.id, user.tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/enrollments/{enrollment_id}", status_code=204)
async def remove_enrollment(
    enrollment_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    try:
        await unenroll(db, enrollment_id, user.tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{course_id}/enrollment-stats")
async def enrollment_stats(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    """Get enrollment statistics for a course."""
    return await get_course_enrollment_stats(db, course_id, user.tenant_id)
