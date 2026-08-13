"""Progress — API router"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_tenant_user
from app.core.db import get_db
from app.modules.progress.schemas import CourseProgressResponse, ProgressResponse, ProgressUpdate
from app.modules.progress.service import (
    get_completed_lesson_ids,
    get_course_progress,
    get_lesson_progress,
    update_lesson_progress,
)


async def _require_window_for_lesson(db, lesson_id, user):
    from sqlalchemy import select

    from app.modules.enrollments.access_service import (
        AssignmentWindowExpiredError,
        assignment_window_error,
        require_active_enrollment_window,
    )
    from app.modules.lessons.models import Lesson, Module

    course_id = await db.scalar(
        select(Module.course_id).join(Lesson, Lesson.module_id == Module.id).where(Lesson.id == lesson_id)
    )
    if course_id is None:
        return
    try:
        await require_active_enrollment_window(
            db,
            user_id=user.id,
            tenant_id=user.tenant_id,
            course_id=course_id,
            enrollment_id=getattr(user, "assignment_access_enrollment_id", None),
        )
    except AssignmentWindowExpiredError as exc:
        raise assignment_window_error(exc) from exc


router = APIRouter(
    prefix="/progress",
    tags=["progress"],
    dependencies=[Depends(require_tenant_user())],
)


@router.get("/lessons/{lesson_id}", response_model=ProgressResponse | None)
async def get_lesson_progress_endpoint(
    lesson_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    await _require_window_for_lesson(db, lesson_id, user)
    return await get_lesson_progress(db, user.id, lesson_id, user.tenant_id)


@router.put("/lessons/{lesson_id}", response_model=ProgressResponse)
async def update_lesson_progress_endpoint(
    lesson_id: UUID,
    req: ProgressUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    await _require_window_for_lesson(db, lesson_id, user)
    progress = await update_lesson_progress(db, user.id, lesson_id, user.tenant_id, req.completed)
    if progress is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found")
    return progress


@router.get("/courses/{course_id}", response_model=CourseProgressResponse)
async def get_course_progress_endpoint(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    from app.modules.enrollments.access_service import (
        AssignmentWindowExpiredError,
        assignment_window_error,
        require_active_enrollment_window,
    )

    try:
        await require_active_enrollment_window(
            db,
            user_id=user.id,
            tenant_id=user.tenant_id,
            course_id=course_id,
            enrollment_id=getattr(user, "assignment_access_enrollment_id", None),
        )
    except AssignmentWindowExpiredError as exc:
        raise assignment_window_error(exc) from exc
    return await get_course_progress(db, user.id, course_id, user.tenant_id)


@router.get("/courses/{course_id}/completed-ids")
async def get_completed_lesson_ids_endpoint(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get list of completed lesson IDs for a course."""
    from app.modules.enrollments.access_service import (
        AssignmentWindowExpiredError,
        assignment_window_error,
        require_active_enrollment_window,
    )

    try:
        await require_active_enrollment_window(
            db,
            user_id=user.id,
            tenant_id=user.tenant_id,
            course_id=course_id,
            enrollment_id=getattr(user, "assignment_access_enrollment_id", None),
        )
    except AssignmentWindowExpiredError as exc:
        raise assignment_window_error(exc) from exc
    ids = await get_completed_lesson_ids(db, user.id, course_id, user.tenant_id)
    return {"completed_lesson_ids": ids}
