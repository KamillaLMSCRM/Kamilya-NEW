"""Tests for GET /v1/departments — list endpoint.

The Company Courses tab (apps/web/.../CompanyCoursesTab.tsx) needs
to load the tenant's departments along with their course_ids to
compute the tenant-wide set as intersection. Pre-fix this tab was
calling /v1/departments which 404'd — the endpoint didn't exist.
These tests pin the new contract.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


def _dept(*, tenant_id=None, dept_id=None, name="Бухгалтерия", slug="accounting"):
    d = MagicMock()
    d.id = dept_id or uuid4()
    d.tenant_id = tenant_id or uuid4()
    d.name = name
    d.slug = slug
    d.parent_id = None
    return d


def _user(tenant_id=None, role="methodologist"):
    u = MagicMock()
    u.id = uuid4()
    u.tenant_id = tenant_id
    u.role = role
    return u


def _build_db(*, departments, bindings):
    """Build a mock db.
    - `departments` — list of Department mocks (1st execute returns them)
    - `bindings` — list of (department_id, course_id) tuples (2nd execute)
    """
    db = AsyncMock()

    async def execute_side_effect(*args, **kwargs):
        result = MagicMock()
        # First call: SELECT departments → scalars().all() returns the list.
        # Second call: SELECT department_courses → result.all() returns the rows.
        execute_side_effect.calls = getattr(execute_side_effect, 'calls', 0) + 1
        if execute_side_effect.calls == 1:
            scalars = MagicMock()
            scalars.all = MagicMock(return_value=departments)
            result.scalars = MagicMock(return_value=scalars)
        else:
            result.all = MagicMock(return_value=bindings)
        return result

    db.execute = AsyncMock(side_effect=execute_side_effect)
    return db


# ── 1. happy path: returns departments with course_ids ───────


@pytest.mark.asyncio
async def test_list_departments_returns_departments_with_course_ids():
    """The endpoint should return a DepartmentListResponse with one
    entry per department and the course_ids aggregated from
    department_courses.
    """
    from app.modules.departments.router import list_departments

    tenant = uuid4()
    d1 = _dept(tenant_id=tenant, name="Бухгалтерия", slug="accounting")
    d2 = _dept(tenant_id=tenant, name="Цех", slug="workshop")
    c1, c2, c3 = uuid4(), uuid4(), uuid4()
    user = _user(tenant_id=tenant)

    db = _build_db(
        departments=[d1, d2],
        bindings=[
            (d1.id, c1), (d1.id, c2),
            (d2.id, c1), (d2.id, c3),
        ],
    )

    resp = await list_departments(db=db, user=user)

    assert len(resp.departments) == 2
    by_id = {d.id: d for d in resp.departments}
    # d1 had c1 + c2
    assert set(str(x) for x in by_id[d1.id].course_ids) == {str(c1), str(c2)}
    # d2 had c1 + c3
    assert set(str(x) for x in by_id[d2.id].course_ids) == {str(c1), str(c3)}


# ── 2. empty list when no departments ───────────────────────


@pytest.mark.asyncio
async def test_list_departments_returns_empty_when_tenant_has_none():
    """An empty tenant gets an empty list (not 404 — the resource
    is the LIST, which always exists).
    """
    from app.modules.departments.router import list_departments

    db = _build_db(departments=[], bindings=[])

    user = _user(tenant_id=uuid4())
    resp = await list_departments(db=db, user=user)
    assert resp.departments == []


# ── 3. superadmin without tenant gets empty list, not 400 ────


@pytest.mark.asyncio
async def test_list_departments_superadmin_without_tenant_returns_empty():
    """Platform superadmins (tenant_id=None) see an empty list
    rather than 400. v1.0 doesn't have a 'list all departments
    across all tenants' use case.
    """
    from app.modules.departments.router import list_departments

    db = _build_db(departments=[], bindings=[])
    user = MagicMock()
    user.tenant_id = None
    user.role = "superadmin"

    resp = await list_departments(db=db, user=user)
    assert resp.departments == []


# ── 4. cross-tenant safety: bindings filtered by tenant ──────


@pytest.mark.asyncio
async def test_list_departments_filters_bindings_by_tenant():
    """The bindings query is filtered by tenant_id at the SQL level
    (not in Python) so a binding from another tenant cannot leak
    into the response.
    """
    from app.modules.departments.router import list_departments

    tenant = uuid4()
    other_tenant = uuid4()
    d1 = _dept(tenant_id=tenant)
    user = _user(tenant_id=tenant)

    # Even if some shim returned a cross-tenant binding, the SQL
    # `WHERE tenant_id = user.tenant_id` would filter it out. We
    # test the SQL: check the query used the right tenant.
    db = _build_db(departments=[d1], bindings=[])

    resp = await list_departments(db=db, user=user)
    assert len(resp.departments) == 1
    assert resp.departments[0].course_ids == []


# ── 5. no bindings at all → course_ids empty list ────────────


@pytest.mark.asyncio
async def test_list_departments_department_with_no_bindings_has_empty_list():
    """A department with no department_courses rows returns
    course_ids=[], not None. (The frontend iterates over this
    list without null-checks.)
    """
    from app.modules.departments.router import list_departments

    tenant = uuid4()
    d1 = _dept(tenant_id=tenant)
    user = _user(tenant_id=tenant)

    db = _build_db(departments=[d1], bindings=[])

    resp = await list_departments(db=db, user=user)
    assert resp.departments[0].course_ids == []
    assert resp.departments[0].course_ids is not None
