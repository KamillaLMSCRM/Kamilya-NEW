"""Pure hierarchy invariants for tenant-owned organization units.

The database and HTTP adapters resolve tenant-owned records before crossing
this seam. This module owns the structural rules so import, manual editing,
and future synchronization flows cannot implement different hierarchies.
"""

from __future__ import annotations

from collections.abc import Set
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class OrganizationUnitType(StrEnum):
    BRANCH = "branch"
    DEPARTMENT = "department"


class OrganizationHierarchyError(ValueError):
    """A stable hierarchy error that adapters can map to their own response."""


@dataclass(frozen=True, slots=True)
class OrganizationUnitRef:
    id: UUID
    tenant_id: UUID
    unit_type: OrganizationUnitType
    parent_id: UUID | None
    is_active: bool


def validate_parent_assignment(
    *,
    unit: OrganizationUnitRef,
    parent: OrganizationUnitRef | None,
    descendant_ids: Set[UUID] = frozenset(),
) -> None:
    """Validate the supported ``branch -> department`` hierarchy.

    ``descendant_ids`` is supplied by the repository adapter while moving an
    existing node. Keeping traversal outside this pure module lets both the
    PostgreSQL adapter and focused tests use the same structural interface.
    """

    if parent is not None and parent.id == unit.id:
        raise OrganizationHierarchyError("self_parent")
    if parent is not None and parent.tenant_id != unit.tenant_id:
        raise OrganizationHierarchyError("cross_tenant_parent")
    if parent is not None and parent.id in descendant_ids:
        raise OrganizationHierarchyError("hierarchy_cycle")

    if unit.unit_type is OrganizationUnitType.BRANCH:
        if unit.parent_id is not None or parent is not None:
            raise OrganizationHierarchyError("branch_must_be_root")
        return

    if parent is None or unit.parent_id != parent.id:
        raise OrganizationHierarchyError("department_requires_branch")
    if parent.unit_type is not OrganizationUnitType.BRANCH:
        raise OrganizationHierarchyError("department_requires_branch")
    if not parent.is_active:
        raise OrganizationHierarchyError("parent_inactive")
