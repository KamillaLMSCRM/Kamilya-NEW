"""Tenant-courses router — level-1 (tenant-wide) course assignment.

POST   /v1/tenants/{tenant_id}/courses        — attach a course to the whole tenant
DELETE /v1/tenants/{tenant_id}/courses/{course_id} — detach
GET    /v1/tenants/{tenant_id}/courses        — list (used by UI)

This is the broadest of the four assignment levels (Lesson 22):
  1. tenant (this router)
  2. department
  3. position
  4. manual (never auto-managed)

Every user in the tenant gets enrolled in the attached course
(unless position or department already overrides it, and
unless there's a manual enrollment that takes precedence).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.courses import Course
from app.models.tenant_courses import TenantCourse
from app.models.users import User
from app.modules.positions.batch_service import recompute_all_tenant_users

router = APIRouter(prefix="/tenants/{tenant_id}/courses", tags=["tenant-courses"])


class _TenantCourseItem(BaseModel):
    """Body for POST /v1/tenants/{id}/courses (B1a)."""

    model_config = ConfigDict(extra="forbid")

    course_id: UUID
    required: bool = True


class _TenantCourseOut(BaseModel):
    course_id: UUID
    required: bool
    course_title: str | None = None


class _TenantCourseListResponse(BaseModel):
    items: list[_TenantCourseOut]


async def _ensure_course_in_tenant(
    db: AsyncSession,
    tenant_id: UUID,
    course_id: UUID,
) -> Course:
    """Look up the course and verify it belongs to the tenant. 404 otherwise."""
    course = await db.get(Course, course_id)
    if course is None or course.tenant_id != tenant_id:
        raise HTTPException(
            status_code=404, detail="Course not found in this tenant"
        )
    return course


@router.post(
    "",
    response_model=_TenantCourseListResponse,
    status_code=201,
)
async def attach_course_to_tenant(
    tenant_id: UUID,
    body: _TenantCourseItem,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_role("methodologist", "admin", "superadmin")
    ),
):
    """Attach a course to the whole tenant (B1a, level 1).

    Idempotent: re-attaching an existing binding updates the
    `required` flag in place (same UX as position/department).

    Side effect: triggers a recompute for every user in the tenant.
    For a 1000-user tenant this can take a few seconds — the kernel
    is in-process, not Celery. (See batch_service.recompute_all_tenant_users
    TODO for a future Celery move.)
    """
    if user.tenant_id != tenant_id:
        # Hard 404 — never leak that the tenant exists.
        raise HTTPException(status_code=404, detail="Tenant not found")

    course = await _ensure_course_in_tenant(db, tenant_id, body.course_id)

    # Idempotent upsert. ON CONFLICT (tenant_id, course_id) DO UPDATE
    # updates the required flag if it changed.
    stmt = (
        pg_insert(TenantCourse)
        .values(
            tenant_id=tenant_id,
            course_id=body.course_id,
            required=body.required,
        )
        .on_conflict_do_update(
            index_elements=["tenant_id", "course_id"],
            set_={"required": body.required},
        )
    )
    await db.execute(stmt)

    # Fan-out: re-derive every user's enrollments in this tenant.
    batch = await recompute_all_tenant_users(db, tenant_id)
    await db.flush()

    return _TenantCourseListResponse(
        items=[
            _TenantCourseOut(
                course_id=body.course_id,
                required=body.required,
                course_title=course.title,
            ),
        ],
    )


@router.delete(
    "/{course_id}",
    response_model=_TenantCourseListResponse,
)
async def detach_course_from_tenant(
    tenant_id: UUID,
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_role("methodologist", "admin", "superadmin")
    ),
):
    """Detach a course from the whole tenant (B1a, level 1).

    Side effect: re-derives every user's enrollments. Completions
    are kept; in-progress enrollments with source='tenant' are
    removed (same as position/department detach).
    """
    if user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Tenant not found")

    binding = await db.scalar(
        select(TenantCourse).where(
            TenantCourse.tenant_id == tenant_id,
            TenantCourse.course_id == course_id,
        )
    )
    if binding is None:
        raise HTTPException(status_code=404, detail="Binding not found")

    await db.delete(binding)
    await db.flush()

    # Fan-out recompute — same shape as attach.
    batch = await recompute_all_tenant_users(db, tenant_id)
    await db.flush()

    # Return the (now empty) list for the tenant.
    return _TenantCourseListResponse(items=[])


@router.get(
    "",
    response_model=_TenantCourseListResponse,
)
async def list_tenant_courses(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(
        require_role("methodologist", "admin", "superadmin", "teacher")
    ),
):
    """List all tenant-wide course bindings for the tenant."""
    if user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Tenant not found")

    result = await db.execute(
        select(TenantCourse, Course)
        .outerjoin(Course, TenantCourse.course_id == Course.id)
        .where(TenantCourse.tenant_id == tenant_id)
        .order_by(TenantCourse.created_at.desc())
    )
    items: list[_TenantCourseOut] = []
    for binding, course in result.all():
        items.append(
            _TenantCourseOut(
                course_id=binding.course_id,
                required=binding.required,
                course_title=(course.title if course is not None else None),
            )
        )
    return _TenantCourseListResponse(items=items)
