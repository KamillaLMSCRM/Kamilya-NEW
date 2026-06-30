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
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.department import Department
from app.models.users import User
from app.modules.positions.batch_service import recompute_department_members
from app.modules.positions.models import DepartmentCourse, Position

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


async def _resolve_department(
    db: AsyncSession,
    locator: str,
    tenant_id,
    *,
    auto_create: bool,
) -> Department | None:
    """Resolve a Department by UUID or by slug.

    Excel-based staff import (see `users/staff_import_service.py:551`)
    writes the department **name as a string** into `Position.department`
    but never sets `Position.department_id` (FK). As a result, the
    `departments` table is empty for legacy Excel-imported tenants, and
    the original `POST /v1/departments/{id}/courses` endpoint
    (department_id: UUID) is unreachable from the UI (RuleTab falls
    back to `d.id ?? d.slug` and sends the slug — 422).

    This helper accepts either a UUID (canonical, fast path) or a
    department name (which we look up case-insensitively against
    `Department.slug`). For attach (auto_create=True), if neither
    matches, we **create** the Department row on the fly from the
    given name and backfill `Position.department_id` for any
    existing Position whose `department` matches the same lowercase
    slug. This unblocks all current prod tenants (verified 2026-06-30:
    0 positions have `department_id` set, 0 rows in `departments`).

    For detach (auto_create=False), a missing department is a 404
    (caller raises); we never invent a department just to delete from.

    Returns the Department, or None if not found and auto_create=False.
    """
    # Normalize: callers may pass a UUID object or a str. FastAPI
    # delivers path params as str, but unit tests sometimes pass a
    # bare UUID — handle both.
    if not isinstance(locator, str):
        locator = str(locator)

    # Fast path: UUID. Validating here is cheap and lets us use
    # db.get() for the indexed PK lookup.
    try:
        parsed_uuid = UUID(locator)
    except (ValueError, TypeError, AttributeError):
        parsed_uuid = None

    if parsed_uuid is not None:
        dept = await db.get(Department, parsed_uuid)
        if dept is not None and dept.tenant_id == tenant_id:
            return dept
        # UUID-shaped but doesn't exist OR belongs to another tenant.
        # In both cases fall through to slug lookup — the locator
        # might be a string that just *looks* like a UUID. If that
        # fails too, we return None / 404.
        if dept is None:
            # Could be a non-UUID-shaped string. Try slug.
            pass
        else:
            # UUID exists but wrong tenant. Don't leak existence —
            # treat as not found.
            return None

    slug = locator.strip().lower()
    if not slug:
        return None

    dept = await db.scalar(
        select(Department).where(
            Department.tenant_id == tenant_id,
            Department.slug == slug,
        )
    )
    if dept is not None:
        # Defence-in-depth: even though the WHERE clause filters by
        # tenant_id, double-check here. Catches both DB bugs and
        # unit-test mocks that bypass WHERE (see
        # `test_attach_by_slug_cross_tenant_404`). Returning the
        # wrong-tenant row would leak org-chart existence.
        if dept.tenant_id != tenant_id:
            return None
        return dept

    if not auto_create:
        return None

    # Auto-create: brand new Department for this tenant.
    # The display name keeps the original casing from the URL
    # (which the UI took from `Position.department` Title-case like
    # "HR", "IT", "Маркетинг"); the slug is the canonical lowercase.
    # `created_at` is filled by the DB via `server_default=func.now()`.
    new_dept = Department(
        tenant_id=tenant_id,
        slug=slug,
        name=locator.strip(),  # keep original casing for display
    )
    db.add(new_dept)
    try:
        await db.flush()
    except IntegrityError:
        # Race: another request created the same slug between our
        # SELECT and INSERT. Re-fetch.
        await db.rollback()
        dept = await db.scalar(
            select(Department).where(
                Department.tenant_id == tenant_id,
                Department.slug == slug,
            )
        )
        if dept is None:
            # Genuinely can't create; surface to caller as 404.
            return None
        return dept

    # Backfill: any Position whose free-text `department` matches
    # this slug (case-insensitive) and has no FK yet now points to
    # the new Department. This is the whole point — legacy Excel
    # rows finally get a FK, so /v1/admin/staff/structure outer-join
    # will start returning UUIDs from the next request onward.
    await db.execute(
        update(Position)
        .where(
            Position.tenant_id == tenant_id,
            Position.department_id.is_(None),
            func.lower(Position.department) == slug,
        )
        .values(department_id=new_dept.id)
    )
    await db.flush()
    return new_dept


# ── Endpoints ────────────────────────────────────────────────


@router.post(
    "/{department_id}/courses",
    response_model=DepartmentResponse,
    status_code=201,
)
async def attach_course_to_department(
    department_id: str,
    body: DepartmentCourseItem,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "methodologist", "superadmin")),
):
    """Attach a course to a Department (B1c).

    `department_id` accepts either a UUID (canonical path) or a
    department name/slug. The slug path is the legacy Excel-import
    case (see `_resolve_department`): the UI sends
    `Position.department` (the original Title-case string like "HR",
    "IT", "Маркетинг") because the `departments` table is empty for
    Excel-imported tenants and `/v1/admin/staff/structure` returns
    `id: null`. The slug path auto-creates the Department row and
    backfills `Position.department_id` for all matching legacy rows.

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
    dept = await _resolve_department(
        db, department_id, user.tenant_id, auto_create=True
    )
    if dept is None:
        # 404 not 403 — see security-review §1.3.
        raise HTTPException(status_code=404, detail="Department not found")
    department_id = dept.id  # canonical UUID for the rest of the flow

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
    department_id: str,
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "methodologist", "superadmin")),
):
    """Detach a course from a Department (B1c).

    `department_id` accepts UUID or slug (see POST). Detach does NOT
    auto-create a missing Department — if you didn't attach, you can't
    detach. 404 in that case.

    Side effect: re-derive every member's enrollments. Completions are
    kept; in-progress enrollments sourced from this department are
    removed (B1a's symmetric add/remove semantics, see
    assignment_service.recompute_enrollments).

    Returns the current department state (same shape as POST). 404 if
    the binding doesn't exist — explicit so the UI can show "already
    detached" instead of silently succeeding.
    """
    dept = await _resolve_department(
        db, department_id, user.tenant_id, auto_create=False
    )
    if dept is None:
        raise HTTPException(status_code=404, detail="Department not found")
    department_id = dept.id

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


# ── Batch level-1 endpoints (TZ §1.1, §2.5) ──────────────
#
# Level 1 (tenant-wide) is implemented as a batch attach of a course
# to every department in the caller's tenant. There is no
# `tenant_courses` table by design (TZ §1.1: conscious decision v1.0
# to avoid an extra aggregation surface; the rule applies via
# department-level bindings that recompute propagates).
#
# Caveat documented in TZ: when a new department is later created,
# the methodologist must re-run the attach-all action so the new
# department inherits the "general" courses. v1.1 may add a
# `tenant_courses` table to fix this if it becomes a real problem.


class AttachAllRequest(BaseModel):
    """Body for POST /v1/departments/attach-courses-all.

    `course_ids` must be non-empty; bound at 100 to keep a single
    fan-out bounded (a department might have 10–50 positions, each
    with several holders; 100 courses × N holders could exceed the
    recompute budget for a single HTTP request).
    """

    course_ids: list[UUID] = Field(..., min_length=1, max_length=100)
    required: bool = True


class DetachAllRequest(BaseModel):
    """Body for DELETE /v1/departments/detach-courses-all."""

    course_ids: list[UUID] = Field(..., min_length=1, max_length=100)


class BatchLevelOneResponse(BaseModel):
    """Response for the batch level-1 endpoints.

    `departments_affected` is the count of departments whose binding
    set was actually mutated (skipped duplicates are NOT counted).
    `enrollments_added` is the aggregate of `batch.added` across
    every per-department recompute, so the UI can show a
    "✓ +N enrollments" inline.
    """

    model_config = ConfigDict(from_attributes=True)

    departments_affected: int
    enrollments_added: int = 0
    enrollments_removed: int = 0
    courses_processed: int


class DepartmentListItem(BaseModel):
    """One row of GET /v1/departments — used by the Company Courses tab
    and any other surface that needs to compute cross-department
    aggregates (e.g. "courses attached to every department").

    `course_ids` is the list of `course_id`s bound to this department
    via `department_courses`. The UI computes the intersection across
    all departments to get the "tenant-wide" set.
    """

    id: UUID
    name: str
    slug: str
    parent_id: UUID | None = None
    course_ids: list[UUID] = []


class DepartmentListResponse(BaseModel):
    """Response for GET /v1/departments."""

    departments: list[DepartmentListItem]


async def _list_tenant_departments(
    db: AsyncSession, tenant_id: UUID
) -> list[Department]:
    """Return every Department row for the given tenant. No
    pagination — the count is small (tens, not thousands) and
    this endpoint is the rare batch operation.
    """
    result = await db.execute(
        select(Department).where(Department.tenant_id == tenant_id)
    )
    return list(result.scalars().all())


@router.get("", response_model=DepartmentListResponse)
async def list_departments(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "methodologist", "superadmin")),
):
    """List all departments in the caller's tenant with their
    course_ids. Used by the «Курсы компании» tab to compute the
    tenant-wide set as intersection of course_ids.

    No pagination: a typical tenant has tens of departments, not
    thousands. If this assumption breaks (very large enterprises),
    paginate here + on the UI side.
    """
    if user.tenant_id is None:
        # superadmin without tenant scope — return empty list rather
        # than 400, because the "list all departments I can see" use
        # case for platform admins is out of v1.0 scope.
        return DepartmentListResponse(departments=[])

    depts = await _list_tenant_departments(db, user.tenant_id)
    if not depts:
        return DepartmentListResponse(departments=[])

    # 1 round-trip: all bindings for these departments.
    bindings_result = await db.execute(
        select(DepartmentCourse.department_id, DepartmentCourse.course_id).where(
            DepartmentCourse.tenant_id == user.tenant_id,
            DepartmentCourse.department_id.in_([d.id for d in depts]),
        )
    )
    bindings_by_dept: dict[UUID, list[UUID]] = {}
    for dept_id, course_id in bindings_result.all():
        bindings_by_dept.setdefault(dept_id, []).append(course_id)

    return DepartmentListResponse(
        departments=[
            DepartmentListItem(
                id=d.id,
                name=d.name,
                slug=d.slug,
                parent_id=d.parent_id,
                course_ids=bindings_by_dept.get(d.id, []),
            )
            for d in depts
        ]
    )


@router.post(
    "/attach-courses-all",
    response_model=BatchLevelOneResponse,
    status_code=200,
)
async def attach_courses_to_all_departments(
    body: AttachAllRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "methodologist", "superadmin")),
):
    """Level-1 attach: bind every course in `body.course_ids` to
    every Department in the caller's tenant.

    Per TZ §1.1 there is no `tenant_courses` table in v1.0 — level 1
    is materialized as N `department_courses` rows, one per dept.
    Each per-dept attach triggers
    `recompute_department_members` so the new rule fans out to
    every position holder in that department.

    Idempotent: re-running with the same course_ids is a no-op
    (existing bindings are detected, not duplicated).

    Superadmin: allowed, but `user.tenant_id` MUST be set. A
    superadmin without a tenant context (system-level admin) gets
    400 — level 1 is inherently a per-tenant operation and
    "every department" is undefined when there is no tenant.

    Cross-tenant: callers can only attach to departments in
    their own tenant. Course IDs are not validated against any
    catalog here — they're opaque UUIDs from the caller's
    course library; a course that does not belong to the tenant
    will simply not match any existing `recompute` rule, which
    is the correct behaviour (no enrollment is created for a
    course the tenant doesn't own).

    Returns a summary: how many departments were touched and the
    aggregate recompute rollup.
    """
    if user.tenant_id is None:
        # superadmin without tenant scope — cannot run level-1.
        raise HTTPException(
            status_code=400,
            detail="Level-1 attach requires a tenant context",
        )

    departments = await _list_tenant_departments(db, user.tenant_id)
    if not departments:
        return BatchLevelOneResponse(
            departments_affected=0,
            enrollments_added=0,
            enrollments_removed=0,
            courses_processed=len(body.course_ids),
        )

    affected = 0
    total_added = 0
    total_removed = 0

    for course_id in body.course_ids:
        for dept in departments:
            # Idempotent upsert — same pattern as the single-dept
            # endpoint above.
            existing = await db.scalar(
                select(DepartmentCourse).where(
                    DepartmentCourse.department_id == dept.id,
                    DepartmentCourse.course_id == course_id,
                )
            )
            if existing is None:
                db.add(
                    DepartmentCourse(
                        department_id=dept.id,
                        course_id=course_id,
                        tenant_id=user.tenant_id,
                        required=body.required,
                    )
                )
                affected += 1
            else:
                # Flip the flag in place if the caller changed it.
                existing.required = body.required

        await db.flush()

        # Fan-out for THIS course across all departments. We run
        # recompute per-department so each call respects the
        # recompute kernel's invariants (manual protected,
        # completed protected, in-progress removed, cross-tenant).
        for dept in departments:
            batch = await recompute_department_members(
                db, dept.id, user.tenant_id
            )
            total_added += batch.added
            total_removed += batch.removed
        await db.flush()

    return BatchLevelOneResponse(
        departments_affected=affected,
        enrollments_added=total_added,
        enrollments_removed=total_removed,
        courses_processed=len(body.course_ids),
    )


@router.delete(
    "/detach-courses-all",
    response_model=BatchLevelOneResponse,
)
async def detach_courses_from_all_departments(
    body: DetachAllRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "methodologist", "superadmin")),
):
    """Level-1 detach: remove `body.course_ids` from every Department
    in the caller's tenant.

    Symmetric to attach-courses-all. For each course, we look for
    an existing `department_courses` row in every department; rows
    that exist are deleted and that department's members are
    recomputed. If NONE of the course_ids are bound to ANY
    department in the tenant, returns 404 — the operation is a
    no-op and the UI should report "already detached".

    Symmetry note: this respects the recompute invariants
    (completed enrollments are protected, in-progress ones are
    removed). Methodologists should be aware that detaching a
    general course that is in-progress for some employees will
    remove those in-progress enrollments.
    """
    if user.tenant_id is None:
        raise HTTPException(
            status_code=400,
            detail="Level-1 detach requires a tenant context",
        )

    departments = await _list_tenant_departments(db, user.tenant_id)
    if not departments:
        # Tenant has no departments → 404 (nothing to detach from).
        raise HTTPException(
            status_code=404,
            detail="No departments in tenant",
        )

    total_affected = 0
    total_added = 0
    total_removed = 0
    found_any = False

    for course_id in body.course_ids:
        per_course_affected = 0
        for dept in departments:
            binding = await db.scalar(
                select(DepartmentCourse).where(
                    DepartmentCourse.department_id == dept.id,
                    DepartmentCourse.course_id == course_id,
                )
            )
            if binding is None:
                continue

            found_any = True
            await db.delete(binding)
            per_course_affected += 1

        if per_course_affected == 0:
            # This course_id is not bound to any department in the
            # tenant. Skip the recompute fan-out for it.
            continue

        await db.flush()
        total_affected += per_course_affected

        # Fan-out recompute for every department we just touched
        # (and any others whose state could change — recompute is
        # idempotent so we can safely fan out to all departments).
        for dept in departments:
            batch = await recompute_department_members(
                db, dept.id, user.tenant_id
            )
            total_added += batch.added
            total_removed += batch.removed
        await db.flush()

    if not found_any:
        # No course_id was bound anywhere in the tenant. Surface
        # this so the UI can show "already detached" instead of
        # silently succeeding.
        raise HTTPException(
            status_code=404,
            detail="None of the courses are bound to any department in this tenant",
        )

    return BatchLevelOneResponse(
        departments_affected=total_affected,
        enrollments_added=total_added,
        enrollments_removed=total_removed,
        courses_processed=len(body.course_ids),
    )
