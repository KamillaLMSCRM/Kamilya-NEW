"""RED/GREEN contracts for the organization hierarchy v2 foundation."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.models.department import Department
from app.models.users import User
from app.modules.organization_units.domain import (
    OrganizationHierarchyError,
    OrganizationUnitRef,
    OrganizationUnitType,
    validate_organization_unit_hierarchy,
    validate_parent_assignment,
)
from app.modules.organization_units.schemas import (
    OrganizationUnitCreate,
    OrganizationUnitResponse,
    OrganizationUnitTreeResponse,
)

MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0161_organization_hierarchy_v2.py"


def _unit(
    *,
    tenant_id: UUID,
    unit_type: OrganizationUnitType = OrganizationUnitType.DEPARTMENT,
    parent_id: UUID | None = None,
    is_active: bool = True,
) -> OrganizationUnitRef:
    return OrganizationUnitRef(
        id=uuid4(),
        tenant_id=tenant_id,
        unit_type=unit_type,
        parent_id=parent_id,
        is_active=is_active,
    )


def test_v2_supports_all_unit_types_and_preserves_legacy_values():
    assert [member.value for member in OrganizationUnitType] == [
        "organization",
        "branch",
        "management",
        "division",
        "department",
        "sector",
        "team",
        "other",
    ]
    assert OrganizationUnitType("branch") is OrganizationUnitType.BRANCH
    assert OrganizationUnitType("department") is OrganizationUnitType.DEPARTMENT


def test_v2_parent_rules_are_type_neutral_for_active_same_tenant_units():
    tenant_id = uuid4()
    parent = _unit(tenant_id=tenant_id, unit_type=OrganizationUnitType.MANAGEMENT)

    for child_type in OrganizationUnitType:
        child = _unit(
            tenant_id=tenant_id,
            unit_type=child_type,
            parent_id=parent.id,
        )
        validate_parent_assignment(unit=child, parent=parent, parent_depth=1)

    root_department = _unit(
        tenant_id=tenant_id,
        unit_type=OrganizationUnitType.DEPARTMENT,
    )
    validate_parent_assignment(unit=root_department, parent=None, parent_depth=0)
    validate_organization_unit_hierarchy(unit=root_department, parent=None)


@pytest.mark.parametrize(
    ("reason", "parent_kwargs"),
    [
        ("parent_inactive", {"is_active": False}),
        ("cross_tenant_parent", {"tenant_id": uuid4()}),
    ],
)
def test_v2_rejects_inactive_or_cross_tenant_parent(reason, parent_kwargs):
    tenant_id = uuid4()
    child = _unit(tenant_id=tenant_id, parent_id=uuid4())
    parent = _unit(
        tenant_id=parent_kwargs.pop("tenant_id", tenant_id),
        is_active=parent_kwargs.pop("is_active", True),
    )
    with pytest.raises(OrganizationHierarchyError, match=reason):
        validate_parent_assignment(unit=child, parent=parent, parent_depth=1)


def test_v2_rejects_self_cycle_descendant_cycle_and_depth_nine():
    tenant_id = uuid4()
    unit = _unit(tenant_id=tenant_id, parent_id=uuid4())
    parent = _unit(tenant_id=tenant_id, parent_id=uuid4())

    with pytest.raises(OrganizationHierarchyError, match="self_parent"):
        validate_parent_assignment(
            unit=unit,
            parent=OrganizationUnitRef(
                id=unit.id,
                tenant_id=tenant_id,
                unit_type=OrganizationUnitType.TEAM,
                parent_id=None,
                is_active=True,
            ),
            parent_depth=1,
        )

    with pytest.raises(OrganizationHierarchyError, match="hierarchy_cycle"):
        validate_parent_assignment(
            unit=unit,
            parent=parent,
            descendant_ids={parent.id},
            parent_depth=2,
        )

    with pytest.raises(OrganizationHierarchyError, match="max_depth"):
        validate_parent_assignment(unit=unit, parent=parent, parent_depth=8)


def test_v2_schema_accepts_nested_department_and_new_types():
    payload = OrganizationUnitCreate(
        name="Section",
        unit_type=OrganizationUnitType.SECTOR,
        parent_id=uuid4(),
    )
    assert payload.unit_type is OrganizationUnitType.SECTOR
    assert payload.parent_id is not None
    nested_branch = OrganizationUnitCreate(
        name="Nested branch",
        unit_type=OrganizationUnitType.BRANCH,
        parent_id=payload.parent_id,
    )
    assert nested_branch.parent_id == payload.parent_id

    root = OrganizationUnitCreate(name="Head office", unit_type=OrganizationUnitType.DEPARTMENT)
    assert root.parent_id is None


def test_v2_models_expose_head_office_and_user_placement_columns():
    assert "is_head_office" in Department.__table__.columns
    assert Department.__table__.columns["is_head_office"].nullable is False
    assert "organization_unit_id" in User.__table__.columns
    assert User.__table__.columns["organization_unit_id"].nullable is True


def test_v2_response_schema_keeps_legacy_roots_and_adds_generic_root_projection():
    response = OrganizationUnitTreeResponse(branches=[], legacy_roots=[], summary={})
    assert response.roots == []
    assert OrganizationUnitResponse.model_fields["is_head_office"].default is False
    assert OrganizationUnitResponse.model_fields["depth"].default is None
    assert OrganizationUnitResponse.model_fields["breadcrumb"].default_factory is not None


def test_v2_migration_revises_0160_and_declares_expand_contract():
    source = MIGRATION.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assignments = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"revision", "down_revision"}
    }
    assert assignments == {"revision": "0161", "down_revision": "0160"}
    assert '"is_head_office"' in source
    assert '"organization_unit_id"' in source
    assert "UPDATE {users}" in source
    assert "FROM {schema}.positions AS p" in source
    assert re.search(r"\bp\.department\b", source) is None
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "tenant_organization_units_isolation" in source
    assert "TO lms_app" in source


def test_v2_migration_chain_keeps_0160_as_its_single_parent():
    revisions = {}
    for path in (MIGRATION.parent).glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        values = {}
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in {"revision", "down_revision"}
            ):
                try:
                    values[node.targets[0].id] = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    pass
        if "revision" in values:
            revisions[values["revision"]] = values.get("down_revision")

    assert revisions["0161"] == "0160"
    assert revisions["0160"] == "0159"
    assert list(revisions).count("0161") == 1


def test_v2_migration_replaces_old_checks_and_guards_destructive_downgrade():
    source = MIGRATION.read_text(encoding="utf-8")
    assert "ck_departments_branch_root" in source
    assert "ck_departments_department_parent" in source
    assert "DROP TRIGGER IF EXISTS trg_validate_organization_unit_ownership" in source
    assert "organization_unit_id IS NOT NULL" in source
    assert "parent_id IS NOT NULL" in source
    assert "is_head_office" in source
    assert "downgrade refused" in source
    assert "DO $$" in source
    assert "ALTER TABLE {departments} FORCE ROW LEVEL SECURITY" in source
    assert "WHERE id = NEW.id OR depth > 8" in source
