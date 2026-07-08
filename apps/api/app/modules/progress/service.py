"""Progress — service"""
import uuid
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
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
    result = await db.execute(
        text(
            """
            INSERT INTO progress (
                id,
                tenant_id,
                user_id,
                course_id,
                lesson_id,
                completed,
                completion_percent,
                percent,
                completed_at,
                last_at
            )
            SELECT
                :id,
                :tenant_id,
                :user_id,
                m.course_id,
                l.id,
                :completed,
                CASE WHEN :completed THEN 100 ELSE 0 END,
                CASE WHEN :completed THEN 100 ELSE 0 END,
                CASE WHEN :completed THEN NOW() ELSE NULL END,
                NOW()
            FROM lessons l
            JOIN modules m ON m.id = l.module_id
            WHERE l.id = :lesson_id
              AND l.tenant_id = :tenant_id
              AND m.tenant_id = :tenant_id
            ON CONFLICT (tenant_id, user_id, lesson_id)
            DO UPDATE SET
                completed = EXCLUDED.completed,
                completion_percent = CASE
                    WHEN EXCLUDED.completed THEN 100
                    ELSE progress.completion_percent
                END,
                percent = CASE
                    WHEN EXCLUDED.completed THEN 100
                    ELSE progress.percent
                END,
                completed_at = CASE
                    WHEN EXCLUDED.completed AND progress.completed_at IS NULL THEN NOW()
                    ELSE progress.completed_at
                END,
                last_at = NOW()
            RETURNING
                id,
                user_id,
                lesson_id,
                tenant_id,
                completed,
                completion_percent,
                completed_at,
                last_at AS last_accessed_at
            """
        ),
        {
            "id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "user_id": user_id,
            "lesson_id": lesson_id,
            "completed": completed,
        },
    )
    row = result.mappings().one_or_none()
    return dict(row) if row else None


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
