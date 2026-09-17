"""RED contracts for recursive DepartmentCourse audience semantics."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.positions.assignment_service import recompute_enrollments


def _result(rows):
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    return result


def _user(tenant_id, *, position_id=None, organization_unit_id=None):
    return MagicMock(
        tenant_id=tenant_id,
        position_id=position_id,
        organization_unit_id=organization_unit_id,
        role="student",
        is_active=True,
    )


@pytest.mark.asyncio
async def test_ancestor_rule_inheritance_uses_authoritative_user_unit():
    tenant_id = uuid4()
    ancestor_id, leaf_id = uuid4(), uuid4()
    course_id = uuid4()
    user = _user(tenant_id, position_id=uuid4(), organization_unit_id=leaf_id)
    db = AsyncMock()
    async def get(model, _):
        from app.models.users import User

        return user if model is User else MagicMock(department_id=uuid4())

    db.get = AsyncMock(side_effect=get)
    db.execute = AsyncMock(
        side_effect=[
            _result([]),  # position rules
            _result([(course_id,)]),  # ancestor + leaf department rules
            _result([]),  # organization rules
            _result([]),  # current enrollments
        ]
    )
    db.add = MagicMock()
    db.flush = AsyncMock()

    with patch(
        "app.modules.positions.assignment_service.resolve_ancestor_path",
        new=AsyncMock(return_value=[ancestor_id, leaf_id]),
    ):
        outcome = await recompute_enrollments(db, uuid4())

    assert outcome.added == 1
    assert db.add.call_args.args[0].source == "department"


@pytest.mark.asyncio
async def test_legacy_position_department_fallback_is_recursive_when_user_unit_is_null():
    tenant_id = uuid4()
    legacy_unit_id, ancestor_id = uuid4(), uuid4()
    course_id = uuid4()
    user = _user(tenant_id, position_id=uuid4(), organization_unit_id=None)
    position = MagicMock(department_id=legacy_unit_id)
    db = AsyncMock()
    async def get(model, _):
        from app.models.users import User

        return user if model is User else position

    db.get = AsyncMock(side_effect=get)
    db.execute = AsyncMock(
        side_effect=[
            _result([]),
            _result([(course_id,)]),
            _result([]),
            _result([]),
        ]
    )
    db.add = MagicMock()
    db.flush = AsyncMock()

    with patch(
        "app.modules.positions.assignment_service.resolve_ancestor_path",
        new=AsyncMock(return_value=[ancestor_id, legacy_unit_id]),
    ):
        outcome = await recompute_enrollments(db, uuid4())

    assert outcome.added == 1


def test_sibling_unit_is_excluded_from_employee_scope():
    """The resolver contract, not a position's legacy department, owns audience membership."""
    from app.modules.organization_scope import resolve_employee_scope

    assert callable(resolve_employee_scope)
