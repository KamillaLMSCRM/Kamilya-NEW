"""Resolve the learner's current course delivery instance."""

from typing import cast
from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enrollment import Enrollment
from app.modules.enrollments.occurrences import is_current_occurrence


def scoped_enrollment_id(enrollment: Enrollment | None) -> UUID | None:
    """Return the occurrence key for state that must not leak across cycles.

    Historic first-generation manual assignments used NULL-scoped progress and
    retain that contract. Recurring and manually repeated assignments are true
    occurrences and therefore use their exact enrollment ID.
    """
    if enrollment is None:
        return None
    if (
        getattr(enrollment, "recurring_assignment_id", None)
        or getattr(enrollment, "learning_path_assignment_id", None)
        or getattr(enrollment, "previous_enrollment_id", None)
    ):
        return cast(UUID, enrollment.id)
    return None


async def current_enrollment(db: AsyncSession, *, tenant_id: UUID, user_id: UUID, course_id: UUID) -> Enrollment | None:
    """Prefer the newest open occurrence, then the newest historical grant."""
    return await db.scalar(
        select(Enrollment)
        .where(
            Enrollment.tenant_id == tenant_id,
            Enrollment.user_id == user_id,
            Enrollment.course_id == course_id,
            Enrollment.status.in_(("enrolled", "in_progress", "completed")),
            is_current_occurrence(),
        )
        .order_by(
            case((Enrollment.status.in_(("enrolled", "in_progress")), 0), else_=1),
            Enrollment.enrolled_at.desc(),
            Enrollment.id.desc(),
        )
        .limit(1)
    )
