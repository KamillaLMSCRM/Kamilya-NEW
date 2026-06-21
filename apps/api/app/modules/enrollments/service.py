"""Enrollments — service"""
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
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


async def unenroll(db: AsyncSession, enrollment_id: UUID, tenant_id: UUID) -> None:
    from app.models.enrollment import Enrollment
    result = await db.execute(
        select(Enrollment).where(Enrollment.id == enrollment_id, Enrollment.tenant_id == tenant_id)
    )
    enrollment = result.scalar_one_or_none()
    if enrollment:
        await db.delete(enrollment)
