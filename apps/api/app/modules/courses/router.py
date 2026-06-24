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


@router.post("/{course_id}/complete")
async def complete_course(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.models.enrollment import Enrollment
    from app.modules.certificates.service import issue_certificate
    from app.modules.audit.service import log_action

    result = await db.execute(
        select(Enrollment).where(
            Enrollment.course_id == course_id,
            Enrollment.user_id == user.id,
            Enrollment.tenant_id == user.tenant_id,
        )
    )
    enrollment = result.scalar_one_or_none()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Not enrolled")
    if enrollment.status == "completed":
        # Idempotent — but still return cert info
        return {"status": "already_completed", "course_id": str(course_id)}

    enrollment.status = "completed"
    enrollment.completed_at = datetime.now(timezone.utc)

    # Auto-issue certificate
    cert_number = None
    cert_id = None
    try:
        cert = await issue_certificate(
            db=db,
            user_id=user.id,
            course_id=course_id,
            tenant_id=user.tenant_id,
        )
        cert_number = cert.certificate_number
        cert_id = str(cert.id)
    except ValueError as e:
        # If issue fails (e.g. tenant integrity issue) — log and continue,
        # don't block course completion. User can request cert manually.
        import logging
        logging.getLogger(__name__).warning(f"Auto-issue cert failed: {e}")

    await log_action(
        db=db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        action="course.complete",
        resource_type="course",
        resource_id=str(course_id),
        details={"certificate_number": cert_number, "certificate_id": cert_id},
    )

    await db.commit()
    return {
        "status": "completed",
        "course_id": str(course_id),
        "certificate_number": cert_number,
        "certificate_id": cert_id,
    }
