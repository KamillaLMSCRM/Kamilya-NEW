"""Admin dashboard API router"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import io

from app.core.auth import get_current_user
from app.core.db import get_db
from app.modules.admin.schemas import AdminDashboard, TenantStats
from app.modules.admin.service import get_admin_dashboard, get_tenant_stats
from app.modules.admin.export import (
    export_users_csv,
    export_courses_csv,
    export_enrollments_csv,
    export_quiz_results_csv,
)

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(user):
    if not hasattr(user, "role") or user.role not in ("admin", "org_admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin access required")


@router.get("/dashboard", response_model=AdminDashboard)
async def dashboard(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get admin dashboard (admin only)."""
    require_admin(user)
    return await get_admin_dashboard(db, user.tenant_id)


@router.get("/stats", response_model=TenantStats)
async def stats(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get tenant statistics (admin only)."""
    require_admin(user)
    return await get_tenant_stats(db, user.tenant_id)


@router.get("/export/users")
async def export_users(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Export users to CSV (admin only)."""
    require_admin(user)
    csv_data = await export_users_csv(db, user.tenant_id)
    return StreamingResponse(
        io.StringIO(csv_data),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=users.csv"},
    )


@router.get("/export/courses")
async def export_courses(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Export courses to CSV (admin only)."""
    require_admin(user)
    csv_data = await export_courses_csv(db, user.tenant_id)
    return StreamingResponse(
        io.StringIO(csv_data),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=courses.csv"},
    )


@router.get("/export/enrollments")
async def export_enrollments(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Export enrollments to CSV (admin only)."""
    require_admin(user)
    csv_data = await export_enrollments_csv(db, user.tenant_id)
    return StreamingResponse(
        io.StringIO(csv_data),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=enrollments.csv"},
    )


@router.get("/export/quiz-results")
async def export_quiz_results(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Export quiz results to CSV (admin only)."""
    require_admin(user)
    csv_data = await export_quiz_results_csv(db, user.tenant_id)
    return StreamingResponse(
        io.StringIO(csv_data),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=quiz_results.csv"},
    )
