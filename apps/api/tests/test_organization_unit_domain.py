"""Behavior contract for the organization-unit hierarchy seam."""

from uuid import uuid4

import pytest

from app.modules.organization_units.domain import (
    OrganizationHierarchyError,
    OrganizationUnitRef,
    OrganizationUnitType,
    validate_parent_assignment,
)


def _unit(*, tenant_id, unit_type, parent_id=None, is_active=True):
    return OrganizationUnitRef(
        id=uuid4(),
        tenant_id=tenant_id,
        unit_type=unit_type,
        parent_id=parent_id,
        is_active=is_active,
    )


def test_branch_is_valid_only_as_an_active_root():
    tenant_id = uuid4()

    validate_parent_assignment(
        unit=_unit(tenant_id=tenant_id, unit_type=OrganizationUnitType.BRANCH),
        parent=None,
    )

    parent = _unit(tenant_id=tenant_id, unit_type=OrganizationUnitType.BRANCH)
    branch = _unit(
        tenant_id=tenant_id,
        unit_type=OrganizationUnitType.BRANCH,
        parent_id=parent.id,
    )
    with pytest.raises(OrganizationHierarchyError, match="branch_must_be_root"):
        validate_parent_assignment(unit=branch, parent=parent)


def test_department_requires_active_branch_parent_in_same_tenant():
    tenant_id = uuid4()
    branch = _unit(tenant_id=tenant_id, unit_type=OrganizationUnitType.BRANCH)
    department = _unit(
        tenant_id=tenant_id,
        unit_type=OrganizationUnitType.DEPARTMENT,
        parent_id=branch.id,
    )

    validate_parent_assignment(unit=department, parent=branch)

    with pytest.raises(OrganizationHierarchyError, match="department_requires_branch"):
        validate_parent_assignment(unit=department, parent=None)

    inactive_branch = _unit(
        tenant_id=tenant_id,
        unit_type=OrganizationUnitType.BRANCH,
        is_active=False,
    )
    inactive_child = _unit(
        tenant_id=tenant_id,
        unit_type=OrganizationUnitType.DEPARTMENT,
        parent_id=inactive_branch.id,
    )
    with pytest.raises(OrganizationHierarchyError, match="parent_inactive"):
        validate_parent_assignment(unit=inactive_child, parent=inactive_branch)


def test_department_cannot_be_nested_under_department_in_first_version():
    tenant_id = uuid4()
    parent = _unit(tenant_id=tenant_id, unit_type=OrganizationUnitType.DEPARTMENT)
    child = _unit(
        tenant_id=tenant_id,
        unit_type=OrganizationUnitType.DEPARTMENT,
        parent_id=parent.id,
    )

    with pytest.raises(OrganizationHierarchyError, match="department_requires_branch"):
        validate_parent_assignment(unit=child, parent=parent)


def test_parent_assignment_rejects_cross_tenant_self_parent_and_cycles():
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    branch = _unit(tenant_id=tenant_id, unit_type=OrganizationUnitType.BRANCH)
    department = _unit(
        tenant_id=tenant_id,
        unit_type=OrganizationUnitType.DEPARTMENT,
        parent_id=branch.id,
    )

    foreign_branch = _unit(
        tenant_id=other_tenant_id,
        unit_type=OrganizationUnitType.BRANCH,
    )
    with pytest.raises(OrganizationHierarchyError, match="cross_tenant_parent"):
        validate_parent_assignment(unit=department, parent=foreign_branch)

    self_parent = OrganizationUnitRef(
        id=department.id,
        tenant_id=tenant_id,
        unit_type=OrganizationUnitType.BRANCH,
        parent_id=None,
        is_active=True,
    )
    with pytest.raises(OrganizationHierarchyError, match="self_parent"):
        validate_parent_assignment(unit=department, parent=self_parent)

    with pytest.raises(OrganizationHierarchyError, match="hierarchy_cycle"):
        validate_parent_assignment(
            unit=department,
            parent=branch,
            descendant_ids={branch.id},
        )
