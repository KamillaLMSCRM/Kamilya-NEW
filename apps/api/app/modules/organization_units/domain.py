"""Pure hierarchy invariants for tenant-owned organization units.

The database and HTTP adapters resolve tenant-owned records before crossing
this seam. This module owns the structural rules so import, manual editing,
and future synchronization flows cannot implement different hierarchies.
"""

from __future__ import annotations

from collections.abc import Collection, Set
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class OrganizationUnitType(StrEnum):
    ORGANIZATION = "organization"
    BRANCH = "branch"
    MANAGEMENT = "management"
    DIVISION = "division"
    DEPARTMENT = "department"
    SECTOR = "sector"
    TEAM = "team"
    OTHER = "other"


class OrganizationHierarchyError(ValueError):
    """A stable hierarchy error that adapters can map to their own response."""


@dataclass(frozen=True, slots=True)
class OrganizationUnitRef:
    id: UUID
    tenant_id: UUID
    unit_type: OrganizationUnitType
    parent_id: UUID | None
    is_active: bool
    is_head_office: bool = False


def validate_organization_unit_hierarchy(
    *,
    unit: OrganizationUnitRef,
    parent: OrganizationUnitRef | None,
    descendant_ids: Collection[UUID] = frozenset(),
    ancestor_ids: Collection[UUID] = frozenset(),
    parent_depth: int | None = None,
    max_depth: int = 8,
) -> None:
    """Validate a tenant-owned move without querying storage.

    ``parent_depth`` is the 1-based depth of the proposed parent (zero for a
    root). ``ancestor_ids`` is an alternative explicit path input when the
    adapter has the parent ancestry but not a precomputed depth. The
    ``descendant_ids`` input is the unit's current subtree and prevents moving
    a node below one of its own descendants.

    This public v2 seam is type-neutral. The compatibility wrapper below keeps
    the old shape checks only for unchanged legacy callers that do not yet
    provide explicit ancestry/depth input.
    """

    if max_depth < 1:
        raise OrganizationHierarchyError("invalid_max_depth")
    if parent is not None and parent.id == unit.id:
        raise OrganizationHierarchyError("self_parent")
    if unit.id in ancestor_ids:
        raise OrganizationHierarchyError("hierarchy_cycle")
    if parent is not None and parent.tenant_id != unit.tenant_id:
        raise OrganizationHierarchyError("cross_tenant_parent")
    if parent is not None and not parent.is_active:
        raise OrganizationHierarchyError("parent_inactive")
    if parent is not None and parent.id in descendant_ids:
        raise OrganizationHierarchyError("hierarchy_cycle")

    if parent_depth is not None and parent_depth < 0:
        raise OrganizationHierarchyError("invalid_parent_depth")
    if parent is not None:
        effective_parent_depth = parent_depth
        if effective_parent_depth is None and ancestor_ids:
            effective_parent_depth = len(ancestor_ids) + 1
        if effective_parent_depth is not None and effective_parent_depth + 1 > max_depth:
            raise OrganizationHierarchyError("max_depth")

    if unit.is_head_office and (unit.parent_id is not None or parent is not None):
        raise OrganizationHierarchyError("head_office_must_be_root")
    if parent is None and parent_depth not in (None, 0):
        raise OrganizationHierarchyError("invalid_parent_depth")


def validate_parent_assignment(
    *,
    unit: OrganizationUnitRef,
    parent: OrganizationUnitRef | None,
    descendant_ids: Set[UUID] = frozenset(),
    ancestor_ids: Collection[UUID] = frozenset(),
    parent_depth: int | None = None,
    max_depth: int = 8,
) -> None:
    """Backward-compatible name for the pure v2 hierarchy validator."""

    if parent_depth is None and not ancestor_ids:
        # Existing service/import callers are migrated separately. Preserve
        # their v1 admission behavior while the database expand migration is
        # deployed; explicit v2 calls always use the generic seam.
        if unit.unit_type is OrganizationUnitType.BRANCH:
            if unit.parent_id is not None or parent is not None:
                raise OrganizationHierarchyError("branch_must_be_root")
        elif parent is None:
            raise OrganizationHierarchyError("department_requires_branch")
        elif unit.unit_type is OrganizationUnitType.DEPARTMENT and parent.unit_type is not OrganizationUnitType.BRANCH:
            raise OrganizationHierarchyError("department_requires_branch")

    validate_organization_unit_hierarchy(
        unit=unit,
        parent=parent,
        descendant_ids=descendant_ids,
        ancestor_ids=ancestor_ids,
        parent_depth=parent_depth,
        max_depth=max_depth,
    )
