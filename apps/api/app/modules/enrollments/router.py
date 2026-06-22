"""Enrollments — API router"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_role
from app.core.db import get_db
from app.models.users import User
from app.modules.enrollments.schemas import EnrollmentCreate, EnrollmentResponse
from app.modules.enrollments.service import (
    get_enrolled_users,
    enroll_users,
    unenroll,
    self_enroll,
    get_course_enrollment_stats,
)

router = APIRouter(prefix="/courses", tags=["enrollments"])


@router.get("/{course_id}/enrollments", response_model=list[EnrollmentResponse])
async def list_enrollments(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await get_enrolled_users(db, course_id, user.tenant_id)


@router.post("/{course_id}/enrollments", response_model=list[EnrollmentResponse], status_code=201)
async def create_enrollments(
    course_id: UUID,
    req: EnrollmentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
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
    user: User = Depends(get_current_user),
):
    await unenroll(db, enrollment_id, user.tenant_id)


@router.get("/{course_id}/enrollment-stats")
async def enrollment_stats(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    """Get enrollment statistics for a course."""
    return await get_course_enrollment_stats(db, course_id, user.tenant_id)
