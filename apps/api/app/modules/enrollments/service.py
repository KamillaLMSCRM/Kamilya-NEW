"""Enrollments — service"""
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.modules.lessons.models import Module, Lesson


async def get_enrolled_users(db: AsyncSession, course_id: UUID, tenant_id: UUID):
    """List users enrolled in a course."""
    from app.models.enrollment import Enrollment
    result = await db.execute(
        select(Enrollment).where(
            Enrollment.course_id == course_id,
            Enrollment.tenant_id == tenant_id,
        )
    )
    return result.scalars().all()


async def enroll_users(db: AsyncSession, course_id: UUID, tenant_id: UUID, user_ids: list[UUID]):
    """Bulk enroll users."""
    from app.models.enrollment import Enrollment
    from uuid import uuid4
    enrollments = []
    for uid in user_ids:
        # Check for duplicate enrollment
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
        )
        db.add(enrollment)
        enrollments.append(enrollment)
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
