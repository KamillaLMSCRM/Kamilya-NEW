"""Student dashboard API router"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_tenant_user
from app.core.db import get_db
from app.models.enrollment import Enrollment
from app.modules.student.schemas import CourseProgress, StudentDashboard
from app.modules.student.service import get_course_progress_detail, get_student_dashboard

router = APIRouter(
    prefix="/student",
    tags=["student"],
    dependencies=[Depends(require_tenant_user())],
)


@router.get("/dashboard", response_model=StudentDashboard)
async def dashboard(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get student dashboard with enrolled courses and progress."""
    data = await get_student_dashboard(
        db,
        user.id,
        user.tenant_id,
        enrollment_id=getattr(user, "assignment_access_enrollment_id", None),
    )
    data["full_name"] = f"{user.first_name} {user.last_name}" if hasattr(user, "first_name") else ""
    return StudentDashboard(**data)


@router.get("/courses/{course_id}/progress", response_model=CourseProgress)
async def course_progress(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get detailed course progress with modules and lessons."""
    assignment_enrollment_id = getattr(user, "assignment_access_enrollment_id", None)
    if assignment_enrollment_id is not None:
        assigned_course_id = await db.scalar(
            select(Enrollment.course_id).where(
                Enrollment.id == assignment_enrollment_id,
                Enrollment.tenant_id == user.tenant_id,
                Enrollment.user_id == user.id,
            )
        )
        if assigned_course_id != course_id:
            raise HTTPException(status_code=404, detail="Course not found")
    data = await get_course_progress_detail(db, user.id, course_id, user.tenant_id)
    if not data:
        raise HTTPException(status_code=404, detail="Course not found")
    return CourseProgress(**data)
