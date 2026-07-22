"""Enrollments — service"""
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.modules.lessons.models import Module, Lesson
from app.models.courses import Course


async def get_enrolled_users(db: AsyncSession, course_id: UUID, tenant_id: UUID):
    """List users enrolled in a course."""
    from app.models.enrollment import Enrollment
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
    return result.scalars().all()


async def enroll_users(db: AsyncSession, course_id: UUID, tenant_id: UUID, user_ids: list[UUID]):
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
    from app.models.enrollment import Enrollment
    from app.models.users import User
    from uuid import uuid4

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
            )
        )
        if existing.scalar_one_or_none():
            continue

        enrollment = Enrollment(
            id=uuid4(),
            course_id=course_id,
            user_id=uid,
            tenant_id=tenant_id,
            status="enrolled",
            source="manual",
        )
        db.add(enrollment)
        enrollments.append(enrollment)

    if enrollments:
        await db.flush()
    return enrollments


async def self_enroll(db: AsyncSession, course_id: UUID, user_id: UUID, tenant_id: UUID):
    """Self-enrollment — student enrolls themselves in a course."""
    from app.models.enrollment import Enrollment
    from app.models.courses import Course
    from uuid import uuid4

    # Check course exists and is published
    course_result = await db.execute(
        select(Course).where(Course.id == course_id, Course.tenant_id == tenant_id)
    )
    course = course_result.scalar_one_or_none()
    if not course:
        raise ValueError("Course not found")
    if course.status != "published":
        raise ValueError("Course is not published")

    # Check for existing enrollment
    existing = await db.execute(
        select(Enrollment).where(
            Enrollment.course_id == course_id,
            Enrollment.user_id == user_id,
            Enrollment.tenant_id == tenant_id,
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("Already enrolled in this course")

    enrollment = Enrollment(
        id=uuid4(),
        course_id=course_id,
        user_id=user_id,
        tenant_id=tenant_id,
        status="enrolled",
    )
    db.add(enrollment)
    await db.flush()
    return enrollment


async def unenroll(db: AsyncSession, enrollment_id: UUID, tenant_id: UUID) -> None:
    from app.models.enrollment import Enrollment
    result = await db.execute(
        select(Enrollment).where(Enrollment.id == enrollment_id, Enrollment.tenant_id == tenant_id)
    )
    enrollment = result.scalar_one_or_none()
    if enrollment:
        if enrollment.source != "manual":
            raise ValueError(
                "Rule-driven enrollments must be changed through department or position rules"
            )
        await db.delete(enrollment)


async def get_course_enrollment_stats(db: AsyncSession, course_id: UUID, tenant_id: UUID) -> dict:
    """Get enrollment statistics for a course."""
    from app.models.enrollment import Enrollment
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
