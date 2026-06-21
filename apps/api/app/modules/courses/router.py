from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from datetime import datetime, timezone

from app.core.auth import get_current_user
from app.core.db import get_db
from app.models.courses import Course
from app.modules.courses.schemas import CourseCreate, CourseUpdate, CourseResponse

router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("", response_model=list[CourseResponse])
async def list_courses(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Course).order_by(Course.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=CourseResponse, status_code=201)
async def create_course(
    req: CourseCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    course = Course(
        tenant_id=user.tenant_id,
        title=req.title,
        description=req.description,
        status=req.status,
        created_by=user.id,
    )
    db.add(course)
    await db.flush()
    await db.refresh(course)
    return course


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(course_id: UUID, db: AsyncSession = Depends(get_db)):
    course = await db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


@router.patch("/{course_id}", response_model=CourseResponse)
async def update_course(
    course_id: UUID,
    req: CourseUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    course = await db.get(Course, course_id)
    if not course or course.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Course not found")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(course, field, value)
    await db.flush()
    await db.refresh(course)
    return course


@router.post("/{course_id}/publish", response_model=CourseResponse)
async def publish_course(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    course = await db.get(Course, course_id)
    if not course or course.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Course not found")
    course.status = "published"
    course.published_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(course)
    return course


@router.post("/{course_id}/unpublish", response_model=CourseResponse)
async def unpublish_course(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    course = await db.get(Course, course_id)
    if not course or course.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Course not found")
    course.status = "draft"
    course.published_at = None
    await db.flush()
    await db.refresh(course)
    return course


@router.post("/{course_id}/duplicate", response_model=CourseResponse, status_code=201)
async def duplicate_course(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    course = await db.get(Course, course_id)
    if not course or course.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Course not found")
    new_course = Course(
        tenant_id=user.tenant_id,
        title=f"{course.title} (копия)",
        description=course.description,
        status="draft",
        created_by=user.id,
    )
    db.add(new_course)
    await db.flush()
    await db.refresh(new_course)
    return new_course


@router.delete("/{course_id}", status_code=204)
async def delete_course(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    course = await db.get(Course, course_id)
    if not course or course.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Course not found")
    await db.delete(course)
