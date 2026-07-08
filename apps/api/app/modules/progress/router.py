"""Progress — API router"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_tenant_user
from app.core.db import get_db
from app.modules.progress.schemas import ProgressResponse, ProgressUpdate, CourseProgressResponse
from app.modules.progress.service import (
    get_lesson_progress,
    update_lesson_progress,
    get_course_progress,
    get_completed_lesson_ids,
)

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
    return await get_lesson_progress(db, user.id, lesson_id, user.tenant_id)


@router.put("/lessons/{lesson_id}", response_model=ProgressResponse)
async def update_lesson_progress_endpoint(
    lesson_id: UUID,
    req: ProgressUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
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
    return await get_course_progress(db, user.id, course_id, user.tenant_id)


@router.get("/courses/{course_id}/completed-ids")
async def get_completed_lesson_ids_endpoint(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get list of completed lesson IDs for a course."""
    ids = await get_completed_lesson_ids(db, user.id, course_id, user.tenant_id)
    return {"completed_lesson_ids": ids}
