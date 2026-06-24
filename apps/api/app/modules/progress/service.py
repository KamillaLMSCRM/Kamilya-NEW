"""Progress — service"""
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.progress import Progress
from app.modules.lessons.models import Module, Lesson


async def get_lesson_progress(db: AsyncSession, user_id: UUID, lesson_id: UUID, tenant_id: UUID):
    result = await db.execute(
        select(Progress).where(
            Progress.user_id == user_id,
            Progress.lesson_id == lesson_id,
            Progress.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def update_lesson_progress(
    db: AsyncSession, user_id: UUID, lesson_id: UUID, tenant_id: UUID, completed: bool = True
):
    # Resolve course_id from lesson
    lesson_result = await db.execute(
        select(Module.course_id).join(Lesson, Lesson.module_id == Module.id).where(Lesson.id == lesson_id)
    )
    course_id = lesson_result.scalar_one_or_none()

    progress = await get_lesson_progress(db, user_id, lesson_id, tenant_id)
    if progress:
        progress.completed = completed
        progress.completion_percent = 100 if completed else progress.completion_percent
        if completed and not progress.completed_at:
            progress.completed_at = datetime.now(timezone.utc)
        progress.last_accessed_at = datetime.now(timezone.utc)
    else:
        progress = Progress(
            user_id=user_id,
            lesson_id=lesson_id,
            course_id=course_id,
            tenant_id=tenant_id,
            completed=completed,
            completion_percent=100 if completed else 0,
            percent=100 if completed else 0,
            completed_at=datetime.now(timezone.utc) if completed else None,
            last_accessed_at=datetime.now(timezone.utc),
        )
        db.add(progress)
    await db.flush()
    return progress


async def get_course_progress(db: AsyncSession, user_id: UUID, course_id: UUID, tenant_id: UUID):
    """Calculate overall progress for a course."""
    result = await db.execute(
        select(
            func.count(Progress.id).label("total"),
            func.count(Progress.id).filter(Progress.completed == True).label("completed"),
        )
        .join(Lesson, Progress.lesson_id == Lesson.id)
        .join(Module, Lesson.module_id == Module.id)
        .where(Module.course_id == course_id, Progress.tenant_id == tenant_id, Progress.user_id == user_id)
    )
    row = result.one_or_none()
    if not row:
        return {"course_id": course_id, "total_lessons": 0, "completed_lessons": 0, "percent": 0}
    total = row.total or 0
    completed = row.completed or 0
    return {
        "course_id": course_id,
        "total_lessons": total,
        "completed_lessons": completed,
        "percent": round((completed / total * 100) if total > 0 else 0, 1),
    }


async def get_completed_lesson_ids(
    db: AsyncSession, user_id: UUID, course_id: UUID, tenant_id: UUID
) -> list[str]:
    """Get list of completed lesson IDs for a course."""
    result = await db.execute(
        select(Progress.lesson_id)
        .join(Lesson, Progress.lesson_id == Lesson.id)
        .join(Module, Lesson.module_id == Module.id)
        .where(
            Module.course_id == course_id,
            Progress.tenant_id == tenant_id,
            Progress.user_id == user_id,
            Progress.completed == True,
        )
    )
    return [str(lid) for lid in result.scalars().all()]
