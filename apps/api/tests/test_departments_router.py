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
from app.models.department import Department
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
    """Department row not found AND auto-create failed → 404.

    After the slug-or-UUID fix (2026-06-30, plan
    `docs/plans/2026-06-30_nav-fixes-remaining.md`),
    `_resolve_department` for POST has `auto_create=True` — it
    creates the Department on the fly when neither UUID nor slug
    match. 404 only happens if the create itself fails (e.g. mock
    flush raises IntegrityError AND the second-lookup also returns
    None). This test exercises that narrow failure path.
    """
    from fastapi import HTTPException
    from sqlalchemy.exc import IntegrityError

    from app.modules.departments.router import attach_course_to_department

    db = AsyncMock()
    db.get = AsyncMock(return_value=None)  # UUID path miss
    db.scalar = AsyncMock(return_value=None)  # slug path miss + race-retry miss
    # db.flush raises IntegrityError (simulate unique-constraint race)
    # and remains raised on the second flush too — so the second
    # db.scalar retry returns None, and the helper returns None → 404.
    db.flush = AsyncMock(side_effect=IntegrityError("stmt", "params", Exception("orig")))
    db.rollback = AsyncMock()
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


# ── 3. Slug-or-UUID resolver (2026-06-30 fix) ──────────────
#
# Excel-imported tenants have empty `departments` table and
# `Position.department_id = NULL` for every row. The UI sends
# `d.id ?? d.slug` (the original Title-case department name like
# `"HR"`, `"IT"`, `"Маркетинг"`) because the outer-join in
# `/v1/admin/staff/structure` returns `id: null`. This block
# exercises the new resolver path: slug → auto-create Department
# → backfill Position.department_id.
# See `docs/plans/2026-06-30_nav-fixes-remaining.md` §"Шаги
# реализации".


@pytest.mark.asyncio
async def test_attach_by_slug_auto_creates_department():
    """Slug path: department row absent → create + backfill + attach."""
    from app.modules.departments.router import attach_course_to_department

    tenant = uuid4()
    user = _user(tenant_id=tenant, role="methodologist")
    course_id = uuid4()

    db = _mock_db_with_dept(None)  # no dept yet (UUID-path miss)
    db.get = AsyncMock(return_value=None)
    db.scalar = AsyncMock(return_value=None)  # slug-path miss → auto-create
    # Simulate the ORM assigning an id on flush (default=uuid.uuid4).
    def _add_with_id(obj):
        from datetime import datetime, timezone
        if obj.id is None:
            obj.id = uuid4()
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)
    db.add = MagicMock(side_effect=_add_with_id)
    # db.execute stays as set by _mock_db_with_dept — backfill and
    # _get_course_rows both need its iterable return.

    fake = _stub_recompute(BatchResult(users_processed=0, added=5))
    body = DepartmentCourseItem(course_id=course_id, required=True)
    with patch("app.modules.departments.router.recompute_department_members", fake):
        resp = await attach_course_to_department(
            department_id="HR",
            body=body,
            db=db,
            user=user,
        )

    # The new Department was added with the right slug + name.
    added_calls = [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], Department)]
    assert len(added_calls) == 1, f"expected 1 Department add, got {len(added_calls)}"
    new_dept = added_calls[0]
    assert new_dept.slug == "hr"
    assert new_dept.name == "HR"  # original casing preserved
    assert new_dept.tenant_id == tenant

    # Response reflects the new dept UUID.
    assert resp.id == new_dept.id
    assert resp.name == "HR"
    assert resp.slug == "hr"
    assert resp.re_enrolled == 5  # from BatchResult.added

    # The department_courses binding was added (2nd db.add call).
    dc_calls = [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], DepartmentCourse)]
    assert len(dc_calls) == 1
    assert dc_calls[0].department_id == new_dept.id
    assert dc_calls[0].course_id == course_id
    assert dc_calls[0].required is True

    # Backfill was issued (db.execute called for the UPDATE).
    assert db.execute.await_count >= 1

    # Recompute was awaited.
    fake.assert_awaited_once()


@pytest.mark.asyncio
async def test_attach_by_existing_slug_no_double_create():
    """Slug path: department already exists by slug → reuse, do not create."""
    from app.modules.departments.router import attach_course_to_department

    tenant = uuid4()
    existing_dept = _dept(tenant_id=tenant, name="HR", slug="hr")
    user = _user(tenant_id=tenant)
    course_id = uuid4()

    db = _mock_db_with_dept(None)  # UUID-path miss
    db.get = AsyncMock(return_value=None)  # "HR" is not a UUID
    db.scalar = AsyncMock(return_value=existing_dept)  # slug found
    db.add = MagicMock()
    # db.execute stays as set by _mock_db_with_dept — _get_course_rows
    # needs its iterable return.

    fake = _stub_recompute()
    body = DepartmentCourseItem(course_id=course_id, required=True)
    with patch("app.modules.departments.router.recompute_department_members", fake):
        resp = await attach_course_to_department(
            department_id="HR",
            body=body,
            db=db,
            user=user,
        )

    # No new Department was created.
    added = [c.args[0] for c in db.add.call_args_list]
    assert all(not isinstance(c, Department) for c in added), "must not create duplicate Department"

    # The existing dept is used.
    assert resp.id == existing_dept.id
    assert resp.slug == "hr"


@pytest.mark.asyncio
async def test_attach_by_uuid_still_works():
    """Canonical path: department_id is a UUID string → db.get + return."""
    from app.modules.departments.router import attach_course_to_department

    tenant = uuid4()
    dept = _dept(tenant_id=tenant)
    user = _user(tenant_id=tenant)
    course_id = uuid4()

    db = _mock_db_with_dept(dept)  # UUID path hit
    db.scalar = AsyncMock(return_value=None)  # binding lookup miss
    db.add = MagicMock()
    # db.execute stays as set by _mock_db_with_dept.

    fake = _stub_recompute()
    body = DepartmentCourseItem(course_id=course_id, required=True)
    with patch("app.modules.departments.router.recompute_department_members", fake):
        resp = await attach_course_to_department(
            department_id=str(dept.id),
            body=body,
            db=db,
            user=user,
        )

    assert resp.id == dept.id
    # Slug path NOT taken: `_resolve_department` returns from the
    # UUID path (db.get hit) before reaching the slug-fallback. The
    # only `db.scalar` call is the binding lookup after resolve.
    # We can't trivially assert which SELECT was used, but we can
    # assert that `db.get` was called once with the dept id —
    # confirming the UUID path was taken.
    db.get.assert_awaited_once_with(Department, dept.id)


@pytest.mark.asyncio
async def test_attach_by_uuid_wrong_tenant_404_no_slug_fallback():
    """UUID path: dept exists but tenant_id mismatches → 404 immediately.

    Important: we must NOT fall through to slug lookup in this case,
    because that would let tenant B probe tenant A''s department
    names by trying the slug path. UUID lookup is auth; slug lookup
    is convenience.
    """
    from fastapi import HTTPException

    from app.modules.departments.router import attach_course_to_department

    dept = _dept(tenant_id=uuid4())  # tenant A
    user = _user(tenant_id=uuid4())  # tenant B
    course_id = uuid4()

    db = AsyncMock()
    db.get = AsyncMock(return_value=dept)
    db.scalar = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    fake = _stub_recompute()
    body = DepartmentCourseItem(course_id=course_id, required=True)
    with patch("app.modules.departments.router.recompute_department_members", fake):
        with pytest.raises(HTTPException) as exc:
            await attach_course_to_department(
                department_id=str(dept.id),
                body=body,
                db=db,
                user=user,
            )
    assert exc.value.status_code == 404
    db.scalar.assert_not_awaited()  # no probe across tenants
    fake.assert_not_awaited()


@pytest.mark.asyncio
async def test_attach_by_slug_cross_tenant_404():
    """Slug path: locator matches a slug, but the matching dept belongs
    to another tenant → 404 (no cross-tenant access)."""
    from fastapi import HTTPException

    from app.modules.departments.router import attach_course_to_department

    other_tenant_dept = _dept(tenant_id=uuid4(), name="HR", slug="hr")
    user = _user(tenant_id=uuid4())  # different tenant

    db = AsyncMock()
    db.get = AsyncMock(return_value=None)  # not UUID
    db.scalar = AsyncMock(return_value=other_tenant_dept)  # found, but wrong tenant
    db.flush = AsyncMock()
    db.add = MagicMock()

    fake = _stub_recompute()
    body = DepartmentCourseItem(course_id=uuid4(), required=True)
    with patch("app.modules.departments.router.recompute_department_members", fake):
        with pytest.raises(HTTPException) as exc:
            await attach_course_to_department(
                department_id="HR",
                body=body,
                db=db,
                user=user,
            )
    assert exc.value.status_code == 404
    # No new Department was created for the wrong tenant.
    assert not any(isinstance(c.args[0], Department) for c in db.add.call_args_list)
    fake.assert_not_awaited()


@pytest.mark.asyncio
async def test_detach_by_unknown_slug_404_no_autocreate():
    """DELETE never auto-creates. Unknown slug → 404."""
    from fastapi import HTTPException

    from app.modules.departments.router import detach_course_from_department

    tenant = uuid4()
    user = _user(tenant_id=tenant)

    db = AsyncMock()
    db.get = AsyncMock(return_value=None)  # not a UUID
    db.scalar = AsyncMock(return_value=None)  # slug not found
    db.flush = AsyncMock()
    db.add = MagicMock()

    fake = _stub_recompute()
    with patch("app.modules.departments.router.recompute_department_members", fake):
        with pytest.raises(HTTPException) as exc:
            await detach_course_from_department(
                department_id="hr",
                course_id=uuid4(),
                db=db,
                user=user,
            )
    assert exc.value.status_code == 404
    # No Department was created.
    assert not any(isinstance(c.args[0], Department) for c in db.add.call_args_list)
    fake.assert_not_awaited()
