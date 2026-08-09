"""Enrollment-instance-aware progress service."""

import uuid
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.progress import Progress
from app.modules.enrollments.context import current_enrollment
from app.modules.lessons.models import Lesson, Module


def _progress_instance_id(enrollment):
    return enrollment.id if enrollment and enrollment.recurring_assignment_id else None


async def _lesson_context(db, user_id, lesson_id, tenant_id):
    course_id = await db.scalar(
        select(Module.course_id)
        .join(Lesson, Lesson.module_id == Module.id)
        .where(Lesson.id == lesson_id, Lesson.tenant_id == tenant_id)
    )
    enrollment = (
        await current_enrollment(db, tenant_id=tenant_id, user_id=user_id, course_id=course_id) if course_id else None
    )
    return course_id, enrollment


async def get_lesson_progress(db: AsyncSession, user_id: UUID, lesson_id: UUID, tenant_id: UUID):
    _course_id, enrollment = await _lesson_context(db, user_id, lesson_id, tenant_id)
    return await db.scalar(
        select(Progress).where(
            Progress.user_id == user_id,
            Progress.lesson_id == lesson_id,
            Progress.tenant_id == tenant_id,
            Progress.enrollment_id == _progress_instance_id(enrollment),
        )
    )


async def update_lesson_progress(
    db: AsyncSession, user_id: UUID, lesson_id: UUID, tenant_id: UUID, completed: bool = True
):
    _course_id, enrollment = await _lesson_context(db, user_id, lesson_id, tenant_id)
    if enrollment is None:
        return None
    enrollment_id = _progress_instance_id(enrollment)
    conflict_target = (
        "(tenant_id, enrollment_id, lesson_id) WHERE enrollment_id IS NOT NULL"
        if enrollment_id
        else "(tenant_id, user_id, lesson_id) WHERE enrollment_id IS NULL"
    )
    result = await db.execute(
        text(
            f"""
            INSERT INTO progress (id,tenant_id,user_id,course_id,lesson_id,enrollment_id,
                completed,completion_percent,percent,completed_at,last_at)
            SELECT :id,:tenant_id,:user_id,m.course_id,l.id,:enrollment_id,:completed,
                CASE WHEN :completed THEN 100 ELSE 0 END,
                CASE WHEN :completed THEN 100 ELSE 0 END,
                CASE WHEN :completed THEN NOW() ELSE NULL END,NOW()
            FROM lessons l JOIN modules m ON m.id=l.module_id
            WHERE l.id=:lesson_id AND l.tenant_id=:tenant_id AND m.tenant_id=:tenant_id
            ON CONFLICT {conflict_target} DO UPDATE SET
                completed=EXCLUDED.completed,
                completion_percent=CASE WHEN EXCLUDED.completed THEN 100 ELSE progress.completion_percent END,
                percent=CASE WHEN EXCLUDED.completed THEN 100 ELSE progress.percent END,
                completed_at=CASE WHEN EXCLUDED.completed AND progress.completed_at IS NULL THEN NOW() ELSE progress.completed_at END,
                last_at=NOW()
            RETURNING id,user_id,lesson_id,tenant_id,completed,completion_percent,
                completed_at,last_at AS last_accessed_at
            """
        ),
        {
            "id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "user_id": user_id,
            "lesson_id": lesson_id,
            "completed": completed,
            "enrollment_id": enrollment_id,
        },
    )
    row = result.mappings().one_or_none()
    return dict(row) if row else None


async def get_course_progress(db: AsyncSession, user_id: UUID, course_id: UUID, tenant_id: UUID):
    enrollment = await current_enrollment(db, tenant_id=tenant_id, user_id=user_id, course_id=course_id)
    result = await db.execute(
        select(
            func.count(Progress.id).label("total"),
            func.count(Progress.id).filter(Progress.completed.is_(True)).label("completed"),
        )
        .join(Lesson, Progress.lesson_id == Lesson.id)
        .join(Module, Lesson.module_id == Module.id)
        .where(
            Module.course_id == course_id,
            Progress.tenant_id == tenant_id,
            Progress.user_id == user_id,
            Progress.enrollment_id == _progress_instance_id(enrollment),
        )
    )
    row = result.one()
    total, completed = row.total or 0, row.completed or 0
    return {
        "course_id": course_id,
        "total_lessons": total,
        "completed_lessons": completed,
        "percent": round(completed / total * 100, 1) if total else 0,
    }


async def get_completed_lesson_ids(db: AsyncSession, user_id: UUID, course_id: UUID, tenant_id: UUID) -> list[str]:
    enrollment = await current_enrollment(db, tenant_id=tenant_id, user_id=user_id, course_id=course_id)
    result = await db.scalars(
        select(Progress.lesson_id)
        .join(Lesson, Progress.lesson_id == Lesson.id)
        .join(Module, Lesson.module_id == Module.id)
        .where(
            Module.course_id == course_id,
            Progress.tenant_id == tenant_id,
            Progress.user_id == user_id,
            Progress.completed.is_(True),
            Progress.enrollment_id == _progress_instance_id(enrollment),
        )
    )
    return [str(item) for item in result.all()]
