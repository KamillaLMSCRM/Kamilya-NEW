"""Unit tests for the departments router (B1c).

Covers:
  - POST /v1/departments/{id}/courses — idempotent attach,
    flips `required` on existing binding, cross-tenant 404.
  - DELETE /v1/departments/{id}/courses/{course_id} — detach binding,
    404 when binding missing, cross-tenant 404.
  - fan-out: every successful mutation triggers
    `recompute_department_members` so changes propagate to holders.

DB and recompute kernel are mocked — the recompute kernel has its
own test suite; this file focuses on router semantics (binding
mutation, idempotency, RBAC behaviour expressed as the role check).
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.positions.batch_service import BatchResult
from app.modules.positions.models import DepartmentCourse
from app.modules.departments.router import DepartmentCourseItem


# ── helpers ─────────────────────────────────────────────────


def _dept(
    tenant_id=None,
    dept_id=None,
    name="Backend",
    slug="backend",
):
    dept = MagicMock()
    dept.id = dept_id or uuid4()
    dept.tenant_id = tenant_id or uuid4()
    dept.name = name
    dept.slug = slug
    dept.parent_id = None
    dept.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return dept


def _user(tenant_id=None, role="admin"):
    u = MagicMock()
    u.id = uuid4()
    u.tenant_id = tenant_id or uuid4()
    u.role = role
    return u


def _mock_db_with_dept(dept, *, course_bindings: list[tuple] | None = None):
    """Build a mock AsyncSession where db.get(Department, ...) returns `dept`.

    For SELECT ... course_id / required tuples, populate the result
    rows parameter as a list of (course_id, required) tuples.
    """
    db = AsyncMock()
    # db.get(Department, dept_id) → returns dept
    db.get = AsyncMock(return_value=dept)

    rows = course_bindings or []
    result_obj = MagicMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    result_obj.all = MagicMock(return_value=rows)
    result_obj.scalars = MagicMock(return_value=scalars)
    db.execute = AsyncMock(return_value=result_obj)

    db.add = MagicMock()
    db.delete = AsyncMock()
    db.flush = AsyncMock()
    return db


def _stub_recompute(batch: BatchResult | None = None) -> AsyncMock:
    fake = AsyncMock(return_value=batch or BatchResult(users_processed=0, added=3))
    return fake


# ── 1. POST: idempotent attach ──────────────────────────────


@pytest.mark.asyncio
async def test_attach_creates_binding_and_returns_201_state():
    from app.modules.departments.router import attach_course_to_department

    tenant = uuid4()
    dept = _dept(tenant_id=tenant)
    user = _user(tenant_id=tenant)
    course_id = uuid4()

    db = _mock_db_with_dept(dept)
    # First call to db.scalar(...) returns None (no existing binding).
    db.scalar = AsyncMock(return_value=None)

    fake = _stub_recompute()
    body = DepartmentCourseItem(course_id=course_id, required=True)
    with patch(
        "app.modules.departments.router.recompute_department_members",
        fake,
    ):
        resp = await attach_course_to_department(
            department_id=dept.id,
            body=body,
            db=db,
            user=user,
        )

    assert resp.id == dept.id
    assert resp.tenant_id == dept.tenant_id
    assert resp.re_enrolled == 3  # batch.added propagated to response

    # binding was added, flushed, recompute ran
    db.add.assert_called_once()
    added_obj = db.add.call_args[0][0]
    assert isinstance(added_obj, DepartmentCourse)
    assert added_obj.department_id == dept.id
    assert added_obj.course_id == course_id
    assert added_obj.required is True
    db.flush.assert_awaited()
    fake.assert_awaited_once()


@pytest.mark.asyncio
async def test_attach_existing_binding_mutates_required_in_place():
    """Idempotent re-attach: existing row is mutated, NOT re-inserted."""
    from app.modules.departments.router import attach_course_to_department

    tenant = uuid4()
    dept = _dept(tenant_id=tenant)
    user = _user(tenant_id=tenant)
    course_id = uuid4()

    existing = DepartmentCourse(
        department_id=dept.id,
        course_id=course_id,
        tenant_id=tenant,
        required=True,
    )
    db = _mock_db_with_dept(dept)
    db.scalar = AsyncMock(return_value=existing)

    fake = _stub_recompute()
    body = DepartmentCourseItem(course_id=course_id, required=False)
    with patch(
        "app.modules.departments.router.recompute_department_members",
        fake,
    ):
        resp = await attach_course_to_department(
            department_id=dept.id,
            body=body,
            db=db,
            user=user,
        )

    # No new binding added; existing flag flipped.
    db.add.assert_not_called()
    assert existing.required is False
    fake.assert_awaited_once()
    assert resp.re_enrolled == 3


@pytest.mark.asyncio
async def test_attach_404_for_cross_tenant_department():
    """Cross-tenant: department in another tenant → 404, not 403."""
    from fastapi import HTTPException

    from app.modules.departments.router import attach_course_to_department

    dept = _dept(tenant_id=uuid4())
    user = _user(tenant_id=uuid4())  # different tenant

    db = _mock_db_with_dept(dept)
    fake = _stub_recompute()
    body = DepartmentCourseItem(course_id=uuid4(), required=True)
    with patch("app.modules.departments.router.recompute_department_members", fake):
        with pytest.raises(HTTPException) as exc:
            await attach_course_to_department(
                department_id=dept.id,
                body=body,
                db=db,
                user=user,
            )

    assert exc.value.status_code == 404
    # Recompute MUST NOT run when department is wrong tenant.
    fake.assert_not_awaited()
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_attach_404_for_missing_department():
    """Department row not found at all → 404."""
    from fastapi import HTTPException

    from app.modules.departments.router import attach_course_to_department

    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    db.flush = AsyncMock()
    db.add = MagicMock()

    user = _user()
    fake = _stub_recompute()
    body = DepartmentCourseItem(course_id=uuid4(), required=True)
    with patch("app.modules.departments.router.recompute_department_members", fake):
        with pytest.raises(HTTPException) as exc:
            await attach_course_to_department(
                department_id=uuid4(),
                body=body,
                db=db,
                user=user,
            )
    assert exc.value.status_code == 404
    fake.assert_not_awaited()


# ── 2. DELETE: detach binding ───────────────────────────────


@pytest.mark.asyncio
async def test_detach_removes_binding_and_triggers_recompute():
    from app.modules.departments.router import detach_course_from_department

    tenant = uuid4()
    dept = _dept(tenant_id=tenant)
    user = _user(tenant_id=tenant)
    course_id = uuid4()

    binding = MagicMock(spec=DepartmentCourse)
    db = _mock_db_with_dept(dept)
    db.scalar = AsyncMock(return_value=binding)

    fake = _stub_recompute(BatchResult(users_processed=1, added=2, removed=4))
    with patch("app.modules.departments.router.recompute_department_members", fake):
        resp = await detach_course_from_department(
            department_id=dept.id,
            course_id=course_id,
            db=db,
            user=user,
        )

    db.delete.assert_awaited_once_with(binding)
    fake.assert_awaited_once()
    assert resp.re_enrolled == 2  # batch.added drives the response


@pytest.mark.asyncio
async def test_detach_404_when_binding_missing():
    """Idempotency note: detach returns 404 if binding doesn't exist —
    POST is idempotent, DELETE is explicit (UI distinguishes them)."""
    from fastapi import HTTPException

    from app.modules.departments.router import detach_course_from_department

    tenant = uuid4()
    dept = _dept(tenant_id=tenant)
    user = _user(tenant_id=tenant)

    db = _mock_db_with_dept(dept)
    db.scalar = AsyncMock(return_value=None)  # no binding

    fake = _stub_recompute()
    with patch("app.modules.departments.router.recompute_department_members", fake):
        with pytest.raises(HTTPException) as exc:
            await detach_course_from_department(
                department_id=dept.id,
                course_id=uuid4(),
                db=db,
                user=user,
            )

    assert exc.value.status_code == 404
    db.delete.assert_not_awaited()
    fake.assert_not_awaited()  # nothing to recompute → no fan-out


@pytest.mark.asyncio
async def test_detach_404_for_cross_tenant_department():
    from fastapi import HTTPException

    from app.modules.departments.router import detach_course_from_department

    dept = _dept(tenant_id=uuid4())
    user = _user(tenant_id=uuid4())  # different tenant

    db = _mock_db_with_dept(dept)
    fake = _stub_recompute()
    with patch("app.modules.departments.router.recompute_department_members", fake):
        with pytest.raises(HTTPException) as exc:
            await detach_course_from_department(
                department_id=dept.id,
                course_id=uuid4(),
                db=db,
                user=user,
            )

    assert exc.value.status_code == 404
    fake.assert_not_awaited()
    db.delete.assert_not_awaited()
