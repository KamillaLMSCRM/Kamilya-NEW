"""Unit coverage for position-level course rule endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.positions.batch_service import BatchResult
from app.modules.positions.models import PositionCourse
from app.modules.positions.router import _PositionCourseItem


def _position(tenant_id=None, pos_id=None):
    position = MagicMock()
    position.id = pos_id or uuid4()
    position.tenant_id = tenant_id or uuid4()
    position.name = "Backend Engineer"
    position.department = "Backend"
    position.level = "Senior"
    position.responsibilities = "Build services"
    position.requirements = "Python"
    position.employee_count = 2
    position.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return position


def _user(tenant_id=None):
    user = MagicMock()
    user.id = uuid4()
    user.tenant_id = tenant_id or uuid4()
    return user


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


@pytest.mark.asyncio
async def test_attach_creates_position_course_and_triggers_recompute():
    from app.modules.positions.router import attach_course_to_position

    tenant = uuid4()
    position = _position(tenant_id=tenant)
    user = _user(tenant_id=tenant)
    course_id = uuid4()
    db = _mock_db(position, course_rows=[(course_id,)])
    db.scalar = AsyncMock(side_effect=[course_id, None])

    recompute = AsyncMock(return_value=BatchResult(users_processed=2, added=5))
    prepare = AsyncMock(return_value=position)
    record = AsyncMock()
    with (
        patch("app.modules.positions.router.recompute_position_holders", recompute),
        patch(
            "app.modules.positions.router.qualification_service.prepare_external_change",
            prepare,
        ),
        patch(
            "app.modules.positions.router.qualification_service.record_external_change",
            record,
        ),
    ):
        response = await attach_course_to_position(
            position_id=position.id,
            body=_PositionCourseItem(course_id=course_id, required=True),
            db=db,
            user=user,
        )

    db.add.assert_called_once()
    binding = db.add.call_args[0][0]
    assert isinstance(binding, PositionCourse)
    assert binding.position_id == position.id
    assert binding.course_id == course_id
    assert binding.tenant_id == tenant
    assert binding.required is True
    recompute.assert_awaited_once_with(db, position.id, tenant)
    record.assert_awaited_once()
    assert response.re_enrolled == 5


@pytest.mark.asyncio
async def test_attach_existing_binding_mutates_required_only():
    from app.modules.positions.router import attach_course_to_position

    tenant = uuid4()
    position = _position(tenant_id=tenant)
    user = _user(tenant_id=tenant)
    course_id = uuid4()
    existing = PositionCourse(
        position_id=position.id,
        course_id=course_id,
        tenant_id=tenant,
        required=True,
    )
    db = _mock_db(position, course_rows=[(course_id,)])
    db.scalar = AsyncMock(side_effect=[course_id, existing])

    recompute = AsyncMock(return_value=BatchResult())
    record = AsyncMock()
    with (
        patch("app.modules.positions.router.recompute_position_holders", recompute),
        patch(
            "app.modules.positions.router.qualification_service.prepare_external_change",
            AsyncMock(return_value=position),
        ),
        patch(
            "app.modules.positions.router.qualification_service.record_external_change",
            record,
        ),
    ):
        await attach_course_to_position(
            position_id=position.id,
            body=_PositionCourseItem(course_id=course_id, required=False),
            db=db,
            user=user,
        )

    db.add.assert_not_called()
    assert existing.required is False
    recompute.assert_awaited_once()
    record.assert_awaited_once()


@pytest.mark.asyncio
async def test_attach_404_cross_tenant():
    from app.modules.positions.router import attach_course_to_position

    position = _position(tenant_id=uuid4())
    user = _user(tenant_id=uuid4())
    db = _mock_db(position)
    recompute = AsyncMock(return_value=BatchResult())
    prepare = AsyncMock(
        side_effect=HTTPException(status_code=404, detail="Position not found")
    )

    with (
        patch("app.modules.positions.router.recompute_position_holders", recompute),
        patch(
            "app.modules.positions.router.qualification_service.prepare_external_change",
            prepare,
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await attach_course_to_position(
                position_id=position.id,
                body=_PositionCourseItem(course_id=uuid4(), required=True),
                db=db,
                user=user,
            )

    assert exc.value.status_code == 404
    db.add.assert_not_called()
    recompute.assert_not_awaited()


@pytest.mark.asyncio
async def test_attach_404_for_course_outside_tenant():
    from app.modules.positions.router import attach_course_to_position

    tenant = uuid4()
    position = _position(tenant_id=tenant)
    user = _user(tenant_id=tenant)
    db = _mock_db(position)
    db.scalar = AsyncMock(return_value=None)
    recompute = AsyncMock(return_value=BatchResult())
    record = AsyncMock()

    with (
        patch("app.modules.positions.router.recompute_position_holders", recompute),
        patch(
            "app.modules.positions.router.qualification_service.prepare_external_change",
            AsyncMock(return_value=position),
        ),
        patch(
            "app.modules.positions.router.qualification_service.record_external_change",
            record,
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await attach_course_to_position(
                position_id=position.id,
                body=_PositionCourseItem(course_id=uuid4(), required=True),
                db=db,
                user=user,
            )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Course not found"
    db.add.assert_not_called()
    recompute.assert_not_awaited()
    record.assert_not_awaited()


@pytest.mark.asyncio
async def test_detach_removes_binding_and_triggers_recompute():
    from app.modules.positions.router import detach_course_from_position

    tenant = uuid4()
    position = _position(tenant_id=tenant)
    user = _user(tenant_id=tenant)
    course_id = uuid4()
    binding = MagicMock(spec=PositionCourse)
    db = _mock_db(position)
    db.scalar = AsyncMock(return_value=binding)

    recompute = AsyncMock(
        return_value=BatchResult(users_processed=3, added=1, removed=6)
    )
    record = AsyncMock()
    with (
        patch("app.modules.positions.router.recompute_position_holders", recompute),
        patch(
            "app.modules.positions.router.qualification_service.prepare_external_change",
            AsyncMock(return_value=position),
        ),
        patch(
            "app.modules.positions.router.qualification_service.record_external_change",
            record,
        ),
    ):
        response = await detach_course_from_position(
            position_id=position.id,
            course_id=course_id,
            db=db,
            user=user,
        )

    db.delete.assert_awaited_once_with(binding)
    recompute.assert_awaited_once()
    record.assert_awaited_once()
    assert response.re_enrolled == 1


@pytest.mark.asyncio
async def test_detach_404_when_binding_missing():
    from app.modules.positions.router import detach_course_from_position

    tenant = uuid4()
    position = _position(tenant_id=tenant)
    user = _user(tenant_id=tenant)
    db = _mock_db(position)
    db.scalar = AsyncMock(return_value=None)
    recompute = AsyncMock(return_value=BatchResult())
    record = AsyncMock()

    with (
        patch("app.modules.positions.router.recompute_position_holders", recompute),
        patch(
            "app.modules.positions.router.qualification_service.prepare_external_change",
            AsyncMock(return_value=position),
        ),
        patch(
            "app.modules.positions.router.qualification_service.record_external_change",
            record,
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await detach_course_from_position(
                position_id=position.id,
                course_id=uuid4(),
                db=db,
                user=user,
            )

    assert exc.value.status_code == 404
    db.delete.assert_not_awaited()
    recompute.assert_not_awaited()
    record.assert_not_awaited()
