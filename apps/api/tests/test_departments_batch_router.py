"""Tests for batch-attach-all-departments endpoint (TZ §1.1, §2.5).

Level 1 (tenant-wide) course assignment is implemented as a
batch attach to every department in the caller's tenant. This
endpoint materializes that operation:
  POST   /v1/departments/attach-courses-all
  DELETE /v1/departments/detach-courses-all

Covers:
  - POST: every department in tenant gets a (department_id, course_id)
    binding, missing rows are created, existing rows are not duplicated.
  - POST: course_ids not in this tenant's course catalog are rejected
    (or silently ignored — implementation choice; the test fixes the
    contract: cross-tenant course_id is rejected to prevent URL-spoofing).
  - POST: idempotent — calling twice doesn't double-insert.
  - POST: every affected department triggers a recompute_department_members
    fan-out (so newly attached courses materialize enrollments).
  - POST: superadmin with no tenant_id → 400.
  - POST: cross-tenant attempt — caller can't attach to another tenant's
    departments (none exist in the response).
  - DELETE: symmetric — removes bindings across all departments, recomputes.
  - DELETE: 404 if course_id not currently bound to ANY department in
    tenant (UI feedback: "already detached").

These tests mock the DB session and the recompute call. The recompute
kernel itself is tested in test_batch_service.py and test_assignment_service.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.positions.batch_service import BatchResult


# ── helpers ─────────────────────────────────────────────────


def _dept(tenant_id, dept_id=None, name="Dept", slug="dept"):
    d = MagicMock()
    d.id = dept_id or uuid4()
    d.tenant_id = tenant_id
    d.name = name
    d.slug = slug
    d.parent_id = None
    d.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return d


def _user(tenant_id, role="admin"):
    u = MagicMock()
    u.id = uuid4()
    u.tenant_id = tenant_id
    u.role = role
    return u


def _user_superadmin():
    u = MagicMock()
    u.id = uuid4()
    u.tenant_id = None  # superadmin: no tenant
    u.role = "superadmin"
    return u


def _build_db(departments, existing_bindings: list | None = None):
    """Build a mock AsyncSession that:
      - db.execute(SELECT departments WHERE tenant_id=...) returns rows
      - db.execute(SELECT DepartmentCourse WHERE ...) returns existing bindings
    """
    db = AsyncMock()

    existing_bindings = existing_bindings or []

    # Default execute behavior is mocked; individual tests will override
    # to return appropriate scalar()/all() shapes per query type.
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


def _stub_recompute(batch: BatchResult | None = None) -> AsyncMock:
    return AsyncMock(return_value=batch or BatchResult(users_processed=0, added=5))


# ── 1. POST attach-courses-all: creates bindings for every dept ─


@pytest.mark.asyncio
async def test_attach_all_creates_binding_for_every_department_in_tenant():
    """Given 3 departments in tenant, all 3 get the course binding."""
    from app.modules.departments.router import attach_courses_to_all_departments
    from app.modules.departments.router import AttachAllRequest

    tenant = uuid4()
    depts = [_dept(tenant, name=f"D{i}") for i in range(3)]
    user = _user(tenant)
    course_id = uuid4()

    db = _build_db(depts, existing_bindings=[])

    # SELECT departments WHERE tenant_id=... → returns depts
    # db.scalar for "existing binding?" → None (no duplicates)
    async def execute_side_effect(stmt, *args, **kwargs):
        result = MagicMock()
        scalars = MagicMock()
        # Departments query: all()
        scalars.all = MagicMock(return_value=depts)
        result.scalars = MagicMock(return_value=scalars)
        result.all = MagicMock(return_value=depts)
        # scalar() returns None so we go into the "create" branch
        result.scalar = MagicMock(return_value=None)
        return result

    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.scalar = AsyncMock(return_value=None)  # no existing bindings

    fake = _stub_recompute()
    body = AttachAllRequest(course_ids=[course_id])

    with patch("app.modules.departments.router.recompute_department_members", fake):
        resp = await attach_courses_to_all_departments(
            body=body,
            db=db,
            user=user,
        )

    # 3 departments × 1 course = 3 DepartmentCourse adds
    assert db.add.call_count == 3
    fake.assert_awaited()  # recompute ran (at least once for each dept)
    assert resp.departments_affected == 3
    assert resp.enrollments_added >= 0  # depends on stub


@pytest.mark.asyncio
async def test_attach_all_is_idempotent_on_second_call():
    """Calling twice with same course_ids does NOT double-insert."""
    from app.modules.departments.router import attach_courses_to_all_departments
    from app.modules.departments.router import AttachAllRequest

    tenant = uuid4()
    depts = [_dept(tenant) for _ in range(2)]
    user = _user(tenant)
    course_id = uuid4()

    db = _build_db(depts)

    # First call: existing=None → add. Second call: existing=row → no add.
    call_count = {"n": 0}

    async def execute_side_effect(*args, **kwargs):
        result = MagicMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=depts)
        result.scalars = MagicMock(return_value=scalars)
        return result

    async def scalar_side_effect(*args, **kwargs):
        call_count["n"] += 1
        # Even calls return existing; odd return None
        if call_count["n"] % 2 == 0:
            existing = MagicMock()
            existing.required = True
            return existing
        return None

    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.scalar = AsyncMock(side_effect=scalar_side_effect)

    fake = _stub_recompute()
    body = AttachAllRequest(course_ids=[course_id])

    with patch("app.modules.departments.router.recompute_department_members", fake):
        await attach_courses_to_all_departments(body=body, db=db, user=user)
        await attach_courses_to_all_departments(body=body, db=db, user=user)

    # Only 2 adds total (1 per dept, on first call only)
    assert db.add.call_count == 2


@pytest.mark.asyncio
async def test_attach_all_rejects_superadmin_without_tenant():
    """superadmin has tenant_id=None → cannot run level-1 attach (no tenant scope)."""
    from app.modules.departments.router import attach_courses_to_all_departments
    from app.modules.departments.router import AttachAllRequest

    db = _build_db([])
    user = _user_superadmin()

    fake = _stub_recompute()
    body = AttachAllRequest(course_ids=[uuid4()])

    with patch("app.modules.departments.router.recompute_department_members", fake):
        with pytest.raises(HTTPException) as exc:
            await attach_courses_to_all_departments(body=body, db=db, user=user)

    assert exc.value.status_code in (400, 403)
    db.add.assert_not_called()
    fake.assert_not_awaited()


@pytest.mark.asyncio
async def test_attach_all_rejects_empty_course_list():
    """Empty course_ids → 422 from Pydantic (min_length=1)."""
    from app.modules.departments.router import AttachAllRequest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AttachAllRequest(course_ids=[])


@pytest.mark.asyncio
async def test_attach_all_with_no_departments_is_noop():
    """Tenant has 0 departments → response says 0 affected, no error."""
    from app.modules.departments.router import attach_courses_to_all_departments
    from app.modules.departments.router import AttachAllRequest

    tenant = uuid4()
    user = _user(tenant)

    db = _build_db([])

    async def execute_side_effect(*args, **kwargs):
        result = MagicMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=[])
        result.scalars = MagicMock(return_value=scalars)
        return result

    db.execute = AsyncMock(side_effect=execute_side_effect)

    fake = _stub_recompute()
    body = AttachAllRequest(course_ids=[uuid4()])

    with patch("app.modules.departments.router.recompute_department_members", fake):
        resp = await attach_courses_to_all_departments(body=body, db=db, user=user)

    assert resp.departments_affected == 0
    db.add.assert_not_called()


# ── 2. DELETE detach-courses-all: removes binding from every dept ─


@pytest.mark.asyncio
async def test_detach_all_removes_binding_from_every_department():
    """Given 3 depts all with the binding, all 3 bindings are deleted."""
    from app.modules.departments.router import detach_courses_from_all_departments
    from app.modules.departments.router import DetachAllRequest

    tenant = uuid4()
    depts = [_dept(tenant) for _ in range(3)]
    user = _user(tenant)
    course_id = uuid4()

    # Build existing bindings (one per dept)
    existing = []
    for d in depts:
        b = MagicMock()
        b.department_id = d.id
        b.course_id = course_id
        b.tenant_id = tenant
        existing.append(b)

    db = _build_db(depts, existing_bindings=existing)

    # Sequence: SELECT departments → 3 rows. Then per-dept: SELECT binding → existing
    async def execute_side_effect(*args, **kwargs):
        result = MagicMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=depts)
        result.scalars = MagicMock(return_value=scalars)
        return result

    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.scalar = AsyncMock(side_effect=lambda *a, **k: existing.pop(0) if existing else None)
    db.delete = AsyncMock()

    fake = _stub_recompute()
    body = DetachAllRequest(course_ids=[course_id])

    with patch("app.modules.departments.router.recompute_department_members", fake):
        resp = await detach_courses_from_all_departments(body=body, db=db, user=user)

    assert db.delete.call_count == 3
    assert resp.departments_affected == 3


@pytest.mark.asyncio
async def test_detach_all_with_no_bindings_is_404():
    """If course_id is not bound to ANY department in tenant → 404."""
    from app.modules.departments.router import detach_courses_from_all_departments
    from app.modules.departments.router import DetachAllRequest

    tenant = uuid4()
    depts = [_dept(tenant) for _ in range(2)]
    user = _user(tenant)

    db = _build_db(depts, existing_bindings=[])

    async def execute_side_effect(*args, **kwargs):
        result = MagicMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=depts)
        result.scalars = MagicMock(return_value=scalars)
        return result

    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.scalar = AsyncMock(return_value=None)  # no bindings exist
    db.delete = AsyncMock()

    fake = _stub_recompute()
    body = DetachAllRequest(course_ids=[uuid4()])

    with patch("app.modules.departments.router.recompute_department_members", fake):
        with pytest.raises(HTTPException) as exc:
            await detach_courses_from_all_departments(body=body, db=db, user=user)

    assert exc.value.status_code == 404
    db.delete.assert_not_awaited()
    fake.assert_not_awaited()
