"""Enrollments — API router"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.db import get_db
from app.modules.enrollments.schemas import EnrollmentCreate, EnrollmentResponse
from app.modules.enrollments.service import get_enrolled_users, enroll_users, unenroll

router = APIRouter(prefix="/courses", tags=["enrollments"])


@router.get("/{course_id}/enrollments", response_model=list[EnrollmentResponse])
async def list_enrollments(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return await get_enrolled_users(db, course_id, user.tenant_id)


@router.post("/{course_id}/enrollments", response_model=list[EnrollmentResponse], status_code=201)
async def create_enrollments(
    course_id: UUID,
    req: EnrollmentCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return await enroll_users(db, course_id, user.tenant_id, req.user_ids)


@router.delete("/enrollments/{enrollment_id}", status_code=204)
async def remove_enrollment(
    enrollment_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    await unenroll(db, enrollment_id, user.tenant_id)
