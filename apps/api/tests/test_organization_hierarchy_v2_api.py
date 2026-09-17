"""RED contracts for the organization hierarchy v2 API/service seams."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.modules.organization_scope import MoveScope
from app.modules.organization_units.domain import OrganizationUnitType
from app.modules.organization_units.service import (
    build_tree,
    create_organization_unit,
    preview_organization_unit_move,
    update_organization_unit,
)
from app.modules.positions.models import Position
from app.modules.users.staff_import_router import (
    ManualStaffCreateRequest,
    _resolve_manual_hierarchy,
)
from app.modules.users.staff_import_service import create_manual_staff_member


def _unit(
    name: str,
    kind: str,
    *,
    parent_id: UUID | None = None,
    is_head_office: bool = False,
):
    unit = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        name=name,
        slug=name.casefold().replace(" ", "-"),
        unit_type=kind,
        parent_id=parent_id,
        external_key=None,
        is_active=True,
        legacy_root=parent_id is None,
        is_head_office=is_head_office,
        description="",
        code=None,
        created_at=datetime(2026, 9, 17, tzinfo=UTC),
    )
    return unit


def test_four_level_tree_has_depth_breadcrumb_head_office_and_recursive_rollups():
    tenant_id = uuid4()
    root = _unit("Central Office", "organization", is_head_office=True)
    root.tenant_id = tenant_id
    management = _unit("Management", "management", parent_id=root.id)
    division = _unit("Division", "division", parent_id=management.id)
    sector = _unit("Sector", "sector", parent_id=division.id)
    for unit in (management, division, sector):
        unit.tenant_id = tenant_id

    position_id = uuid4()
    branches, legacy_roots = build_tree(
        [sector, root, division, management],
        positions_by_unit={
            sector.id: [{"id": position_id, "name": "Analyst", "employee_count": 2}],
        },
    )

    assert branches == []
    assert len(legacy_roots) == 1
    node = legacy_roots[0]
    assert node["is_head_office"] is True
    assert node["depth"] == 0
    assert node["breadcrumb"] == ["Central Office"]
    assert node["children"][0]["depth"] == 1
    assert node["children"][0]["breadcrumb"] == ["Central Office", "Management"]
    assert node["children"][0]["children"][0]["depth"] == 2
    leaf = node["children"][0]["children"][0]["children"][0]
    assert leaf["depth"] == 3
    assert leaf["breadcrumb"] == ["Central Office", "Management", "Division", "Sector"]
    assert node["position_count"] == 1
    assert node["employee_count"] == 2


@pytest.mark.asyncio
async def test_create_root_unit_uses_slots_safe_domain_reference():
    tenant_id = uuid4()
    db = AsyncMock()
    duplicate_result = MagicMock()
    duplicate_result.scalar_one_or_none.return_value = None
    db.execute.return_value = duplicate_result
    db.add = MagicMock()
    db.flush = AsyncMock()

    created = await create_organization_unit(
        db,
        tenant_id=tenant_id,
        name="Operations",
        unit_type=OrganizationUnitType.MANAGEMENT,
        parent_id=None,
        external_key=None,
        description="",
        code=None,
    )

    assert created.tenant_id == tenant_id
    assert created.parent_id is None
    db.add.assert_called_once_with(created)


@pytest.mark.asyncio
async def test_nested_move_preserves_unit_id_and_validates_descendant_scope():
    tenant_id = uuid4()
    current = _unit("Division", "division")
    current.tenant_id = tenant_id
    child = _unit("Sector", "sector", parent_id=current.id)
    child.tenant_id = tenant_id
    new_parent = _unit("Management", "management")
    new_parent.tenant_id = tenant_id

    async def get_unit(_db, _tenant_id, unit_id, *, for_update=False):
        return {current.id: current, new_parent.id: new_parent, child.id: child}[unit_id]

    db = AsyncMock()
    with (
        patch("app.modules.organization_units.service.get_organization_unit", side_effect=get_unit),
        patch(
            "app.modules.organization_units.service.validate_move",
            new=AsyncMock(
                return_value=MoveScope(
                    unit_id=current.id,
                    parent_id=new_parent.id,
                    descendant_ids=frozenset({current.id, child.id}),
                    parent_depth=0,
                    subtree_height=1,
                )
            ),
        ),
    ):
        moved = await update_organization_unit(
            db,
            tenant_id=tenant_id,
            unit_id=current.id,
            patch={"parent_id": new_parent.id},
        )

    assert moved.id == current.id
    assert moved.parent_id == new_parent.id
    assert child.parent_id == current.id


@pytest.mark.asyncio
async def test_move_preview_uses_write_validator_and_reports_affected_scope():
    tenant_id = uuid4()
    unit_id = uuid4()
    child_id = uuid4()
    parent_id = uuid4()
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[3, 7])
    scope = MoveScope(
        unit_id=unit_id,
        parent_id=parent_id,
        descendant_ids=frozenset({unit_id, child_id}),
        parent_depth=2,
        subtree_height=1,
    )

    with patch(
        "app.modules.organization_units.service.validate_move",
        new=AsyncMock(return_value=scope),
    ) as validate:
        preview = await preview_organization_unit_move(
            db,
            tenant_id=tenant_id,
            unit_id=unit_id,
            parent_id=parent_id,
        )

    validate.assert_awaited_once_with(db, tenant_id, unit_id, parent_id)
    assert preview == {
        "unit_id": unit_id,
        "parent_id": parent_id,
        "affected_units": 2,
        "affected_positions": 3,
        "affected_employees": 7,
        "resulting_depth": 3,
        "subtree_height": 1,
    }


@pytest.mark.asyncio
async def test_manual_employee_accepts_nullable_unit_but_requires_position():
    payload = ManualStaffCreateRequest(
        personnel_number="EMP-001",
        first_name="A",
        last_name="B",
        organization_unit_id=None,
        position_id=uuid4(),
    )
    assert payload.organization_unit_id is None
    with pytest.raises((HTTPException, ValueError)):
        ManualStaffCreateRequest(
            personnel_number="EMP-002",
            first_name="A",
            last_name="B",
            organization_unit_id=None,
        )


@pytest.mark.asyncio
async def test_manual_resolution_does_not_mutate_position_department_when_unit_selected():
    tenant_id = uuid4()
    unit = SimpleNamespace(id=uuid4(), tenant_id=tenant_id, name="Unit", is_active=True)
    position = Position(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Shared position",
        department="Legacy unit",
        department_id=uuid4(),
    )
    old_department_id = position.department_id
    db = AsyncMock()
    db.scalar.side_effect = [unit, position]
    payload = ManualStaffCreateRequest(
        personnel_number="EMP-003",
        first_name="A",
        last_name="B",
        organization_unit_id=unit.id,
        position_id=position.id,
    )

    department_name, position_name = await _resolve_manual_hierarchy(db, tenant_id, payload)

    assert (department_name, position_name) == ("Unit", "Shared position")
    assert position.department_id == old_department_id


@pytest.mark.asyncio
async def test_manual_create_can_reuse_one_position_in_two_units_without_reassignment():
    tenant_id = uuid4()
    position = Position(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Shared position",
        department="Legacy unit",
        department_id=uuid4(),
    )
    db = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    db.scalar = AsyncMock(side_effect=[position])
    org_unit_id = uuid4()

    with (
        patch("app.modules.users.staff_import_service._load_staff_indexes", new=AsyncMock(
            return_value=(
                {},
                {},
                {},
                {org_unit_id: SimpleNamespace(id=org_unit_id, tenant_id=tenant_id, name="Unit", is_active=True)},
                {("", "shared position"): position},
                {position.id: position},
            )
        )),
        patch("app.modules.positions.batch_service.apply_rules_for_users", new=AsyncMock()),
    ):
        result = await create_manual_staff_member(
            db,
            tenant_id,
            personnel_number="EMP-004",
            first_name="A",
            last_name="B",
            department="",
            position="Shared position",
            position_id=position.id,
            organization_unit_id=org_unit_id,
            apply_rules=False,
        )

    assert result["created"] == 1
    created_user = next(call.args[0] for call in db.add.call_args_list if hasattr(call.args[0], "position_id"))
    assert created_user.position_id == position.id
    assert created_user.organization_unit_id is not None
    assert position.department_id != created_user.organization_unit_id
