"""Central course access policy for authoring and learner flows."""
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.courses import Course
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.lessons.models import Lesson, Module


AUTHORING_ROLES = {"methodologist", "teacher", "superadmin"}


async def require_course_access(
    db: AsyncSession,
    course_id: UUID,
    user: User,
) -> Course:
    """Return a tenant course only when the current role may read it.

    Authors can inspect drafts. Learners can read only a published course
    backed by an enrollment. A 404 is intentional for learner denials so a
    guessed UUID does not reveal course existence or publication state.
    """
    result = await db.execute(
        select(Course).where(
            Course.id == course_id,
            Course.tenant_id == user.tenant_id,
        )
    )
    course = result.scalar_one_or_none()
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")

    if user.role in AUTHORING_ROLES:
        return course

    if user.role != "student" or course.status != "published":
        raise HTTPException(status_code=404, detail="Course not found")

    enrollment_result = await db.execute(
        select(Enrollment.id).where(
            Enrollment.course_id == course.id,
            Enrollment.user_id == user.id,
            Enrollment.tenant_id == user.tenant_id,
        )
    )
    if enrollment_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


async def require_module_access(
    db: AsyncSession,
    module_id: UUID,
    user: User,
) -> Module:
    result = await db.execute(
        select(Module).where(
            Module.id == module_id,
            Module.tenant_id == user.tenant_id,
        )
    )
    module = result.scalar_one_or_none()
    if module is None:
        raise HTTPException(status_code=404, detail="Module not found")
    await require_course_access(db, module.course_id, user)
    return module


async def require_lesson_access(
    db: AsyncSession,
    lesson_id: UUID,
    user: User,
) -> Lesson:
    result = await db.execute(
        select(Lesson, Module.course_id)
        .join(Module, Module.id == Lesson.module_id)
        .where(
            Lesson.id == lesson_id,
            Lesson.tenant_id == user.tenant_id,
            Module.tenant_id == user.tenant_id,
        )
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Lesson not found")
    lesson, course_id = row
    await require_course_access(db, course_id, user)
    return lesson
