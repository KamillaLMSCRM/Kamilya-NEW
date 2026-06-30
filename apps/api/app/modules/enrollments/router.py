"""Enrollments — API router"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.auth import get_current_user, require_role, require_tenant_user
from app.core.db import get_db
from app.models.users import User
from app.models.enrollment import Enrollment
from app.modules.enrollments.schemas import EnrollmentCreate, EnrollmentResponse
from app.modules.enrollments.service import (
    get_enrolled_users,
    enroll_users,
    unenroll,
    self_enroll,
    get_course_enrollment_stats,
)

router = APIRouter(
    prefix="/courses",
    tags=["enrollments"],
    dependencies=[Depends(require_tenant_user())],
)

stats_router = APIRouter(prefix="/enrollments", tags=["enrollments"])


@stats_router.get("/stats")
async def global_enrollment_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Global enrollment statistics for dashboard."""
    total_result = await db.execute(
        select(func.count(Enrollment.id)).where(Enrollment.tenant_id == user.tenant_id)
    )
    total = total_result.scalar() or 0

    completed_result = await db.execute(
        select(func.count(Enrollment.id)).where(
            Enrollment.tenant_id == user.tenant_id,
            Enrollment.status == "completed",
        )
    )
    completed = completed_result.scalar() or 0

    return {"total": total, "completed": completed}


# ADR-0012: enrollment management is shared between admin (tenant
# infrastructure) and methodologist (teacher) — direct user→course
# assignment is part of the content domain (TZ_COURSE_ASSIGNMENT_ACCESS_v1
# §1.2 level-4 manual override), not pure admin scope. Students keep
# the self-enrollment path below; everyone else is rejected.

_ENROLLMENT_MANAGER_ROLES = ("superadmin", "admin", "org_admin", "teacher")


@router.get("/{course_id}/enrollments", response_model=list[EnrollmentResponse])
async def list_enrollments(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    return await get_enrolled_users(db, course_id, user.tenant_id)


@router.post("/{course_id}/enrollments", response_model=list[EnrollmentResponse], status_code=201)
async def create_enrollments(
    course_id: UUID,
    req: EnrollmentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    return await enroll_users(db, course_id, user.tenant_id, req.user_ids)


@router.post("/{course_id}/enroll", response_model=EnrollmentResponse, status_code=201)
async def enroll_self(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Self-enrollment — student enrolls themselves in a course."""
    try:
        return await self_enroll(db, course_id, user.id, user.tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/enrollments/{enrollment_id}", status_code=204)
async def remove_enrollment(
    enrollment_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    await unenroll(db, enrollment_id, user.tenant_id)


@router.get("/{course_id}/enrollment-stats")
async def enrollment_stats(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_MANAGER_ROLES)),
):
    """Get enrollment statistics for a course."""
    return await get_course_enrollment_stats(db, course_id, user.tenant_id)
