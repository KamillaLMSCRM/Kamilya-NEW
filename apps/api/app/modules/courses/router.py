from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from datetime import datetime, timezone
from typing import Optional

from app.core.auth import get_current_user, require_role
from app.core.db import get_db
from app.models.users import User
from app.models.courses import Course
from app.modules.courses.schemas import CourseCreate, CourseUpdate, CourseResponse
from app.modules.audit.service import log_action

router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("", response_model=list[CourseResponse])
async def list_courses(
    status: Optional[str] = Query(None, description="Filter by status: draft, published, archived"),
    q: Optional[str] = Query(None, description="Search in title and description"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Course).where(Course.tenant_id == user.tenant_id)
    if status:
        query = query.where(Course.status == status)
    if q:
        search = f"%{q}%"
        query = query.where(
            (Course.title.ilike(search)) | (Course.description.ilike(search))
        )
    query = query.order_by(Course.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("", response_model=CourseResponse, status_code=201)
async def create_course(
    req: CourseCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
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
    await log_action(
        db, user.tenant_id, "create", "course",
        resource_id=str(course.id), user_id=user.id,
        details={"title": course.title},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return course


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id)
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


@router.patch("/{course_id}", response_model=CourseResponse)
async def update_course(
    course_id: UUID,
    req: CourseUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    result = await db.execute(
        select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id)
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(course, field, value)
    await db.flush()
    await db.refresh(course)
    await log_action(
        db, user.tenant_id, "update", "course",
        resource_id=str(course.id), user_id=user.id,
        details=req.model_dump(exclude_unset=True),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return course


@router.post("/{course_id}/publish", response_model=CourseResponse)
async def publish_course(
    course_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    result = await db.execute(
        select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id)
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    course.status = "published"
    course.published_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(course)
    await log_action(
        db, user.tenant_id, "publish", "course",
        resource_id=str(course.id), user_id=user.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return course


@router.post("/{course_id}/unpublish", response_model=CourseResponse)
async def unpublish_course(
    course_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    result = await db.execute(
        select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id)
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    course.status = "draft"
    course.published_at = None
    await db.flush()
    await db.refresh(course)
    await log_action(
        db, user.tenant_id, "unpublish", "course",
        resource_id=str(course.id), user_id=user.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return course


@router.post("/{course_id}/duplicate", response_model=CourseResponse, status_code=201)
async def duplicate_course(
    course_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin", "teacher")),
):
    result = await db.execute(
        select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id)
    )
    course = result.scalar_one_or_none()
    if not course:
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
    await log_action(
        db, user.tenant_id, "duplicate", "course",
        resource_id=str(new_course.id), user_id=user.id,
        details={"original_id": str(course.id), "title": new_course.title},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return new_course


@router.delete("/{course_id}", status_code=204)
async def delete_course(
    course_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("superadmin", "admin", "org_admin")),
):
    result = await db.execute(
        select(Course).where(Course.id == course_id, Course.tenant_id == user.tenant_id)
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    await log_action(
        db, user.tenant_id, "delete", "course",
        resource_id=str(course.id), user_id=user.id,
        details={"title": course.title},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.delete(course)
    await db.commit()
