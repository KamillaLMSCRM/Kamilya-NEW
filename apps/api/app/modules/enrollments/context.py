"""Resolve the learner's current course delivery instance."""

from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enrollment import Enrollment


async def current_enrollment(db: AsyncSession, *, tenant_id: UUID, user_id: UUID, course_id: UUID) -> Enrollment | None:
    """Prefer the newest open occurrence, then the newest historical grant."""
    return await db.scalar(
        select(Enrollment)
        .where(
            Enrollment.tenant_id == tenant_id,
            Enrollment.user_id == user_id,
            Enrollment.course_id == course_id,
            Enrollment.status.in_(("enrolled", "in_progress", "completed")),
        )
        .order_by(
            case((Enrollment.status.in_(("enrolled", "in_progress")), 0), else_=1),
            Enrollment.enrolled_at.desc(),
            Enrollment.id.desc(),
        )
        .limit(1)
    )
