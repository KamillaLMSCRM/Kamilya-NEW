"""Student dashboard API router"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.db import get_db
from app.modules.student.schemas import StudentDashboard, CourseProgress
from app.modules.student.service import get_student_dashboard, get_course_progress_detail

router = APIRouter(prefix="/student", tags=["student"])


@router.get("/dashboard", response_model=StudentDashboard)
async def dashboard(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get student dashboard with enrolled courses and progress."""
    data = await get_student_dashboard(db, user.id, user.tenant_id)
    data["full_name"] = f"{user.first_name} {user.last_name}" if hasattr(user, "first_name") else ""
    return StudentDashboard(**data)


@router.get("/courses/{course_id}/progress", response_model=CourseProgress)
async def course_progress(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get detailed course progress with modules and lessons."""
    data = await get_course_progress_detail(db, user.id, course_id, user.tenant_id)
    if not data:
        raise HTTPException(status_code=404, detail="Course not found")
    return CourseProgress(**data)
