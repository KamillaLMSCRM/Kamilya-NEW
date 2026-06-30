"""Departments — API router (B1c).

Parallel of `positions/router.py` for course attachment at the
department level. Recompute semantics mirror the position flow:

  POST   /v1/departments/{id}/courses         attach a course (idempotent)
  DELETE /v1/departments/{id}/courses/{cid}   detach a course

Side effects:
  - The binding row is mutated in `department_courses` (UPSERT or DELETE).
  - `recompute_department_members` fans out to every user whose
    position belongs to this department — i.e. the rule propagates
    through the position→user graph and materializes Enrollment rows.

RBAC: only admin / methodologist / superadmin can attach/detach — the
endpoints use `require_role` (see app.core.auth). Students cannot bind
rules even via the API.

Why a separate router and not nested under /positions? The URL is
`/v1/departments/{id}/courses` per the api-design convention (resource
hierarchy max 3 levels deep). Co-locating with positions would have
required `/v1/positions/positions-of-department/{id}/...` which is
ugly and breaks the symmetric mental model. We pay one router file.
"""
from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.department import Department
from app.models.users import User
from app.modules.positions.batch_service import recompute_department_members
from app.modules.positions.models import DepartmentCourse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/departments", tags=["departments"])


# ── Schemas ─────────────────────────────────────────────────


class DepartmentCourseItem(BaseModel):
    """Body for POST /v1/departments/{id}/courses.

    Same shape as `_PositionCourseItem` in positions/router.py so the
    frontend can reuse the form component. `required` default is True
    so omitting it matches the "counted toward ready_percent" semantic.
    """

    course_id: UUID
    required: bool = True


class DepartmentCourseRow(BaseModel):
    """One row of the department's course list (GET response)."""

    course_id: UUID
    required: bool


class DepartmentResponse(BaseModel):
    """Response for POST/DELETE /v1/departments/{id}/courses.

    Returns the current state of the department after the mutation,
    including the live course_ids and the recompute rollup so the UI
    can show "✓ привязано, +N enrollments" inline.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    slug: str
    parent_id: UUID | None = None
    courses: list[DepartmentCourseRow]
    re_enrolled: int | None = None  # only set on mutation responses
    created_at: datetime


# ── Helpers ─────────────────────────────────────────────────


async def _get_course_rows(db: AsyncSession, department_id: UUID) -> list[DepartmentCourseRow]:
    """Return the department's course bindings, ordered by created_at."""
    result = await db.execute(
        select(DepartmentCourse.course_id, DepartmentCourse.required)
        .where(DepartmentCourse.department_id == department_id)
        .order_by(DepartmentCourse.created_at.asc())
    )
    return [
        DepartmentCourseRow(course_id=row[0], required=row[1])
        for row in result.all()
    ]


# ── Endpoints ────────────────────────────────────────────────


@router.post(
    "/{department_id}/courses",
    response_model=DepartmentResponse,
    status_code=201,
)
async def attach_course_to_department(
    department_id: UUID,
    body: DepartmentCourseItem,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "methodologist", "superadmin")),
):
    """Attach a course to a Department (B1c).

    Idempotent: attaching a course that's already linked returns 200
    (not 409) with the current state — that way the UI's "save" button
    can be re-clicked without surprises. If the binding exists and the
    caller flips `required`, we mutate the flag in place.

    Side effect: triggers a fan-out recompute through the kernel for
    every member of every position in this department via
    `recompute_department_members`. The recompute is idempotent so a
    second attach to the same course+department is a safe no-op.

    RBAC: admin / methodologist / superadmin. Students are rejected.

    Cross-tenant: a department that doesn't belong to the caller's
    tenant returns 404 (not 403) — never leak existence of resources
    in other tenants.
    """
    dept = await db.get(Department, department_id)
    if dept is None or dept.tenant_id != user.tenant_id:
        # 404 not 403 — see security-review §1.3.
        raise HTTPException(status_code=404, detail="Department not found")

    # Idempotent upsert. We avoid touching unique-constraint ON CONFLICT
    # because SQLAlchemy doesn't carry the constraint name into the
    # INSERT; a SELECT-then-INSERT keeps the path portable and the
    # duplicate case cheap (1 extra round-trip on first attach, 0 on
    # re-attach because we short-circuit).
    existing = await db.scalar(
        select(DepartmentCourse).where(
            DepartmentCourse.department_id == department_id,
            DepartmentCourse.course_id == body.course_id,
        )
    )
    if existing is None:
        db.add(
            DepartmentCourse(
                department_id=department_id,
                course_id=body.course_id,
                tenant_id=user.tenant_id,
                required=body.required,
            )
        )
        await db.flush()
    else:
        existing.required = body.required
        await db.flush()

    # Fan-out: re-derive every member's enrollments from the rules.
    batch = await recompute_department_members(db, department_id, user.tenant_id)
    await db.flush()

    courses = await _get_course_rows(db, department_id)
    return DepartmentResponse(
        id=dept.id,
        tenant_id=dept.tenant_id,
        name=dept.name,
        slug=dept.slug,
        parent_id=dept.parent_id,
        courses=courses,
        re_enrolled=batch.added,
        created_at=dept.created_at,
    )


@router.delete(
    "/{department_id}/courses/{course_id}",
    response_model=DepartmentResponse,
)
async def detach_course_from_department(
    department_id: UUID,
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "methodologist", "superadmin")),
):
    """Detach a course from a Department (B1c).

    Side effect: re-derive every member's enrollments. Completions are
    kept; in-progress enrollments sourced from this department are
    removed (B1a's symmetric add/remove semantics, see
    assignment_service.recompute_enrollments).

    Returns the current department state (same shape as POST). 404 if
    the binding doesn't exist — explicit so the UI can show "already
    detached" instead of silently succeeding.
    """
    dept = await db.get(Department, department_id)
    if dept is None or dept.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Department not found")

    binding = await db.scalar(
        select(DepartmentCourse).where(
            DepartmentCourse.department_id == department_id,
            DepartmentCourse.course_id == course_id,
        )
    )
    if binding is None:
        raise HTTPException(status_code=404, detail="Binding not found")

    await db.delete(binding)
    await db.flush()

    batch = await recompute_department_members(db, department_id, user.tenant_id)
    await db.flush()

    courses = await _get_course_rows(db, department_id)
    return DepartmentResponse(
        id=dept.id,
        tenant_id=dept.tenant_id,
        name=dept.name,
        slug=dept.slug,
        parent_id=dept.parent_id,
        courses=courses,
        re_enrolled=batch.added,
        created_at=dept.created_at,
    )
