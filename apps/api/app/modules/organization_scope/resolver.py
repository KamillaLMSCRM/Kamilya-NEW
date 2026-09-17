"""Deep module for tenant-safe organization hierarchy scopes.

The storage adapter intentionally loads the tenant's active hierarchy once and
performs traversal here. This keeps recursive details, inactive-node semantics,
and tenant filtering out of assignment, reporting, and API consumers. The
bounded tenant-local read is also usable by database-free unit-test fakes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department
from app.modules.organization_units.domain import (
    OrganizationUnitRef,
    OrganizationUnitType,
    validate_organization_unit_hierarchy,
)


class OrganizationScopeNotFoundError(LookupError):
    """A requested unit is not visible in the supplied tenant scope."""


@dataclass(frozen=True)
class MoveScope:
    """Validated move context returned to CRUD services."""

    unit_id: UUID
    parent_id: UUID | None
    descendant_ids: frozenset[UUID]
    parent_depth: int
    subtree_height: int


async def _tenant_units(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    active_only: bool,
) -> list[Department]:
    statement = select(Department).where(Department.tenant_id == tenant_id)
    if active_only:
        statement = statement.where(Department.is_active.is_(True))
    result = await db.execute(statement)
    return [
        unit
        for unit in result.scalars().all()
        if unit.tenant_id == tenant_id and (not active_only or unit.is_active)
    ]


def _children_by_parent(units: Iterable[Department]) -> dict[UUID, list[Department]]:
    children: dict[UUID, list[Department]] = {}
    for unit in units:
        if unit.parent_id is not None:
            children.setdefault(unit.parent_id, []).append(unit)
    return children


async def resolve_descendants(
    db: AsyncSession,
    tenant_id: UUID,
    unit_ids: Iterable[UUID],
    *,
    include_self: bool = True,
    active_only: bool = True,
) -> set[UUID]:
    """Return the visible recursive subtree for tenant-local ``unit_ids``."""

    units = await _tenant_units(db, tenant_id, active_only=active_only)
    by_id = {unit.id: unit for unit in units}
    children = _children_by_parent(units)
    requested = [unit_id for unit_id in unit_ids if unit_id in by_id]
    resolved: set[UUID] = set(requested if include_self else ())
    stack = list(requested)
    while stack:
        current_id = stack.pop()
        for child in children.get(current_id, ()):
            if child.id in resolved:
                continue
            resolved.add(child.id)
            stack.append(child.id)
    if not include_self:
        resolved.difference_update(requested)
    return resolved


async def resolve_ancestor_path(
    db: AsyncSession,
    tenant_id: UUID,
    unit_id: UUID,
    *,
    active_only: bool = True,
) -> list[UUID]:
    """Return the tenant-local root-to-unit path, including ``unit_id``.

    Unknown or cross-tenant IDs intentionally have the same not-found result so
    the resolver cannot disclose another tenant's hierarchy.
    """

    units = await _tenant_units(db, tenant_id, active_only=active_only)
    by_id = {unit.id: unit for unit in units}
    current = by_id.get(unit_id)
    if current is None:
        raise OrganizationScopeNotFoundError("organization_unit_not_found")

    path: list[UUID] = []
    seen: set[UUID] = set()
    while current is not None:
        if current.id in seen:
            raise ValueError("hierarchy_cycle")
        seen.add(current.id)
        if not active_only or current.is_active:
            path.append(current.id)
        current = by_id.get(current.parent_id) if current.parent_id is not None else None
    path.reverse()
    return path


async def resolve_ancestor_paths(
    db: AsyncSession,
    tenant_id: UUID,
    unit_ids: Iterable[UUID],
    *,
    active_only: bool = True,
) -> dict[UUID, list[UUID]]:
    """Resolve many root-to-unit paths with one tenant-scoped hierarchy read."""

    units = await _tenant_units(db, tenant_id, active_only=active_only)
    by_id = {unit.id: unit for unit in units}
    paths: dict[UUID, list[UUID]] = {}
    for unit_id in dict.fromkeys(unit_ids):
        current = by_id.get(unit_id)
        if current is None:
            raise OrganizationScopeNotFoundError("organization_unit_not_found")
        path: list[UUID] = []
        seen: set[UUID] = set()
        while current is not None:
            if current.id in seen:
                raise ValueError("hierarchy_cycle")
            seen.add(current.id)
            path.append(current.id)
            current = by_id.get(current.parent_id) if current.parent_id is not None else None
        path.reverse()
        paths[unit_id] = path
    return paths


async def resolve_descendant_memberships(
    db: AsyncSession,
    tenant_id: UUID,
    root_ids: Iterable[UUID],
    *,
    active_only: bool = True,
) -> dict[UUID, UUID]:
    """Map each visible descendant to its most specific selected root.

    The value preserves the audience root chosen by the methodologist.  When
    selected roots overlap, the closest selected ancestor wins; equal-distance
    ties preserve the caller's order.
    """

    units = await _tenant_units(db, tenant_id, active_only=active_only)
    by_id = {unit.id: unit for unit in units}
    children = _children_by_parent(units)
    roots = [unit_id for unit_id in dict.fromkeys(root_ids) if unit_id in by_id]
    memberships: dict[UUID, tuple[int, int, UUID]] = {}
    for order, root_id in enumerate(roots):
        stack = [(root_id, 0)]
        seen: set[UUID] = set()
        while stack:
            unit_id, distance = stack.pop()
            if unit_id in seen:
                continue
            seen.add(unit_id)
            candidate = (distance, order, root_id)
            current = memberships.get(unit_id)
            if current is None or candidate[:2] < current[:2]:
                memberships[unit_id] = candidate
            stack.extend((child.id, distance + 1) for child in children.get(unit_id, ()))
    return {unit_id: value[2] for unit_id, value in memberships.items()}


async def resolve_employee_scope(
    db: AsyncSession,
    tenant_id: UUID,
    unit_ids: Iterable[UUID],
) -> set[UUID]:
    """Return active unit IDs whose users belong to the supplied audience."""

    return await resolve_descendants(db, tenant_id, unit_ids, include_self=True, active_only=True)


async def validate_move(
    db: AsyncSession,
    tenant_id: UUID,
    unit_id: UUID,
    parent_id: UUID | None,
    *,
    max_depth: int = 8,
) -> MoveScope:
    """Validate a move and return the computed subtree/depth context."""

    all_units = await _tenant_units(db, tenant_id, active_only=False)
    by_id = {unit.id: unit for unit in all_units}
    unit = by_id.get(unit_id)
    if unit is None:
        raise OrganizationScopeNotFoundError("organization_unit_not_found")
    parent = by_id.get(parent_id) if parent_id is not None else None
    if parent_id is not None and parent is None:
        # Unknown and cross-tenant parents deliberately share this stable error.
        raise ValueError("cross_tenant_parent")

    descendants: set[UUID] = set()
    children = _children_by_parent(all_units)
    stack = [unit.id]
    distances = {unit.id: 0}
    while stack:
        current_id = stack.pop()
        descendants.add(current_id)
        for child in children.get(current_id, ()):
            if child.id in distances:
                raise ValueError("hierarchy_cycle")
            distances[child.id] = distances[current_id] + 1
            stack.append(child.id)

    parent_path: list[UUID] = []
    if parent is not None:
        current = parent
        seen: set[UUID] = set()
        while current is not None:
            if current.id in seen:
                raise ValueError("hierarchy_cycle")
            seen.add(current.id)
            parent_path.append(current.id)
            current = by_id.get(current.parent_id) if current.parent_id is not None else None
        parent_path.reverse()

    parent_depth = len(parent_path) - 1 if parent_path else 0
    subtree_height = max(distances.values(), default=0)
    validate_organization_unit_hierarchy(
        unit=OrganizationUnitRef(
            id=unit.id,
            tenant_id=unit.tenant_id,
            unit_type=OrganizationUnitType(unit.unit_type),
            parent_id=parent_id,
            is_active=unit.is_active,
            is_head_office=getattr(unit, "is_head_office", False),
        ),
        parent=(
            OrganizationUnitRef(
                id=parent.id,
                tenant_id=parent.tenant_id,
                unit_type=OrganizationUnitType(parent.unit_type),
                parent_id=parent.parent_id,
                is_active=parent.is_active,
                is_head_office=getattr(parent, "is_head_office", False),
            )
            if parent is not None
            else None
        ),
        descendant_ids=descendants,
        ancestor_ids=parent_path,
        parent_depth=parent_depth,
        max_depth=max_depth,
    )
    if parent_depth + 1 + subtree_height > max_depth:
        raise ValueError("max_depth")
    return MoveScope(
        unit_id=unit.id,
        parent_id=parent_id,
        descendant_ids=frozenset(descendants),
        parent_depth=parent_depth,
        subtree_height=subtree_height,
    )
