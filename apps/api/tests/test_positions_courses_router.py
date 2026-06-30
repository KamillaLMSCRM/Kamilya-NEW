"""Unit tests for the position course attach/detach endpoints (B1c).

Mirrors test_departments_router.py but for the position-level rule
binding endpoints added in B1c:

  POST   /v1/positions/{id}/courses         attach (idempotent)
  DELETE /v1/positions/{id}/courses/{cid}   detach

Covers:
  - happy path POST creates a PositionCourse and fans out
  - existing binding: `required` is mutated, NOT re-inserted
  - DELETE removes the binding and fans out
  - cross-tenant: 404 (NOT 403) on both
  - missing binding on DELETE: 404

DB is mocked; recompute kernel is mocked. The kernel has its own
test suite (test_assignment_service.py) — we focus on router wiring.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.positions.batch_service import BatchResult
from app.modules.positions.models import PositionCourse
# Re-use the same body schema; defined locally in the positions module.
from app.modules.positions.router import _PositionCourseItem


def _position(tenant_id=None, pos_id=None):
    p = MagicMock()
    p.id = pos_id or uuid4()
    p.tenant_id = tenant_id or uuid4()
    p.name = "Backend Engineer"
    p.department = "Backend"
    p.level = "Senior"
    p.responsibilities = "..."
    p.requirements = "..."
    p.employee_count = 2
    p.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return p


def _user(tenant_id=None):
    u = MagicMock()
    u.id = uuid4()
    u.tenant_id = tenant_id or uuid4()
    return u


def _mock_db(position_obj, *, course_rows=None):
    db = AsyncMock()
    db.get = AsyncMock(return_value=position_obj)

    rows = course_rows or []
    result_obj = MagicMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    result_obj.all = MagicMock(return_value=rows)
    result_obj.scalars = MagicMock(return_value=scalars)
    db.execute = AsyncMock(return_value=result_obj)

    db.add = MagicMock()
    db.delete = AsyncMock()
    db.flush = AsyncMock()
    db.scalar = AsyncMock()
    return db


# ── 1. POST: happy path ──────────────────────────────────────


@pytest.mark.asyncio
async def test_attach_creates_position_course_and_triggers_recompute():
    from app.modules.positions.router import attach_course_to_position

    tenant = uuid4()
    pos = _position(tenant_id=tenant)
    user = _user(tenant_id=tenant)
    course_id = uuid4()

    db = _mock_db(pos, course_rows=[(course_id,)])
    db.scalar = AsyncMock(return_value=None)  # no existing binding

    fake = AsyncMock(return_value=BatchResult(users_processed=2, added=5))
    body = _PositionCourseItem(course_id=course_id, required=True)
    with patch("app.modules.positions.router.recompute_position_holders", fake):
        resp = await attach_course_to_position(
            position_id=pos.id,
            body=body,
            db=db,
            user=user,
        )

    db.add.assert_called_once()
    binding = db.add.call_args[0][0]
    assert isinstance(binding, PositionCourse)
    assert binding.position_id == pos.id
    assert binding.course_id == course_id
    # No tenant_id on PositionCourse (junction table — see migration 0013d
    # RLS final which excluded position_courses from RLS; tenant comes
    # via position_id → positions.tenant_id).
    assert binding.required is True

    fake.assert_awaited_once_with(db, pos.id, tenant)
    assert resp.re_enrolled == 5


@pytest.mark.asyncio
async def test_attach_existing_binding_mutates_required_only():
    """Re-attach with a different `required` flag updates in place;
    DB sees 0 inserts, just one .required assignment."""
    from app.modules.positions.router import attach_course_to_position

    tenant = uuid4()
    pos = _position(tenant_id=tenant)
    user = _user(tenant_id=tenant)
    course_id = uuid4()

    existing = PositionCourse(
        position_id=pos.id,
        course_id=course_id,
        required=True,
    )
    db = _mock_db(pos, course_rows=[(course_id,)])
    db.scalar = AsyncMock(return_value=existing)

    fake = AsyncMock(return_value=BatchResult())
    body = _PositionCourseItem(course_id=course_id, required=False)
    with patch("app.modules.positions.router.recompute_position_holders", fake):
        await attach_course_to_position(
            position_id=pos.id,
            body=body,
            db=db,
            user=user,
        )

    db.add.assert_not_called()
    assert existing.required is False
    fake.assert_awaited_once()


@pytest.mark.asyncio
async def test_attach_404_cross_tenant():
    """Cross-tenant must be 404, never 403 (security-review §1.3)."""
    from fastapi import HTTPException

    from app.modules.positions.router import attach_course_to_position

    pos = _position(tenant_id=uuid4())
    user = _user(tenant_id=uuid4())

    db = _mock_db(pos)
    fake = AsyncMock(return_value=BatchResult())
    body = _PositionCourseItem(course_id=uuid4(), required=True)
    with patch("app.modules.positions.router.recompute_position_holders", fake):
        with pytest.raises(HTTPException) as exc:
            await attach_course_to_position(
                position_id=pos.id,
                body=body,
                db=db,
                user=user,
            )

    assert exc.value.status_code == 404
    db.add.assert_not_called()
    fake.assert_not_awaited()


# ── 2. DELETE ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_detach_removes_binding_and_triggers_recompute():
    from app.modules.positions.router import detach_course_from_position

    tenant = uuid4()
    pos = _position(tenant_id=tenant)
    user = _user(tenant_id=tenant)
    course_id = uuid4()

    binding = MagicMock(spec=PositionCourse)
    db = _mock_db(pos)
    db.scalar = AsyncMock(return_value=binding)

    fake = AsyncMock(return_value=BatchResult(users_processed=3, added=1, removed=6))
    with patch("app.modules.positions.router.recompute_position_holders", fake):
        resp = await detach_course_from_position(
            position_id=pos.id,
            course_id=course_id,
            db=db,
            user=user,
        )

    db.delete.assert_awaited_once_with(binding)
    fake.assert_awaited_once()
    assert resp.re_enrolled == 1  # batch.added → response


@pytest.mark.asyncio
async def test_detach_404_when_binding_missing():
    """Detach of an already-detached binding returns 404 so the UI can show
    a "binding not found" toast rather than silently doing nothing."""
    from fastapi import HTTPException

    from app.modules.positions.router import detach_course_from_position

    tenant = uuid4()
    pos = _position(tenant_id=tenant)
    user = _user(tenant_id=tenant)

    db = _mock_db(pos)
    db.scalar = AsyncMock(return_value=None)

    fake = AsyncMock(return_value=BatchResult())
    with patch("app.modules.positions.router.recompute_position_holders", fake):
        with pytest.raises(HTTPException) as exc:
            await detach_course_from_position(
                position_id=pos.id,
                course_id=uuid4(),
                db=db,
                user=user,
            )
    assert exc.value.status_code == 404
    db.delete.assert_not_awaited()
    fake.assert_not_awaited()
