"""Idempotent data guarantees for the public demo sandbox."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.courses import Course
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.enrollments.service import enroll_users


async def ensure_demo_student_course(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    student_id: UUID,
) -> UUID | None:
    """Ensure the canonical demo learner can open a published course.

    Public demo data is long-lived and may be cleaned independently from the
    fixed demo identities. Locking the learner serializes concurrent logins,
    while the normal enrollment service creates release evidence and enforces
    the same tenant/status checks as a methodologist assignment.

    If several published courses exist, prefer the one already used by the
    most demo enrollments. This keeps the public learner on the established
    scenario without coupling the contract to a translated course title or a
    deployment-specific UUID.
    """
    locked_student_id = await db.scalar(
        select(User.id)
        .where(
            User.id == student_id,
            User.tenant_id == tenant_id,
            User.role == "student",
            User.is_active.is_(True),
            User.status == "active",
        )
        .with_for_update()
    )
    if locked_student_id is None:
        return None

    existing_course_id = await db.scalar(
        select(Course.id)
        .join(
            Enrollment,
            (Enrollment.course_id == Course.id)
            & (Enrollment.tenant_id == tenant_id),
        )
        .where(
            Course.tenant_id == tenant_id,
            Course.status == "published",
            Enrollment.user_id == student_id,
        )
        .limit(1)
    )
    if existing_course_id is not None:
        return existing_course_id

    course = await db.scalar(
        select(Course)
        .outerjoin(
            Enrollment,
            (Enrollment.course_id == Course.id)
            & (Enrollment.tenant_id == tenant_id),
        )
        .where(
            Course.tenant_id == tenant_id,
            Course.status == "published",
        )
        .group_by(Course.id)
        .order_by(
            func.count(Enrollment.id).desc(),
            Course.created_at.asc(),
            Course.id.asc(),
        )
        .limit(1)
    )
    if course is None:
        return None

    created = await enroll_users(db, course.id, tenant_id, [student_id])
    if created:
        return course.id

    # A concurrent or historical assignment may have become visible after
    # the initial check. Confirm the postcondition rather than returning a
    # successful login with an empty learner dashboard.
    return await db.scalar(
        select(Course.id)
        .join(
            Enrollment,
            (Enrollment.course_id == Course.id)
            & (Enrollment.tenant_id == tenant_id),
        )
        .where(
            Course.tenant_id == tenant_id,
            Course.status == "published",
            Enrollment.user_id == student_id,
        )
        .limit(1)
    )
