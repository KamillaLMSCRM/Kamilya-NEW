"""Progress — API router"""
from uuid import UUID
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.db import get_db
from app.modules.progress.schemas import ProgressResponse, ProgressUpdate, CourseProgressResponse
from app.modules.progress.service import get_lesson_progress, update_lesson_progress, get_course_progress

router = APIRouter(prefix="/progress", tags=["progress"])


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
    return await update_lesson_progress(db, user.id, lesson_id, user.tenant_id, req.completed)


@router.get("/courses/{course_id}", response_model=CourseProgressResponse)
async def get_course_progress_endpoint(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return await get_course_progress(db, user.id, course_id, user.tenant_id)
