from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department

from .domain import (
    OrganizationUnitRef,
    OrganizationUnitType,
    validate_parent_assignment,
)


class OrganizationUnitNotFoundError(LookupError):
    pass


UNASSIGNED_LEGACY_UNIT_ID = UUID(int=0)


def normalize_unit_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().casefold().split())


def _slug_part(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-") or "unit"


def _as_ref(unit: Department) -> OrganizationUnitRef:
    return OrganizationUnitRef(
        id=unit.id,
        tenant_id=unit.tenant_id,
        unit_type=OrganizationUnitType(unit.unit_type),
        parent_id=unit.parent_id,
        is_active=unit.is_active,
    )


async def list_organization_units(db: AsyncSession, tenant_id: UUID) -> list[Department]:
    result = await db.execute(
        select(Department)
        .where(Department.tenant_id == tenant_id, Department.is_active.is_(True))
        .order_by(Department.unit_type, Department.normalized_name, Department.id)
    )
    return list(result.scalars().all())


async def get_organization_unit(
    db: AsyncSession,
    tenant_id: UUID,
    unit_id: UUID,
    *,
    for_update: bool = False,
) -> Department:
    statement = select(Department).where(
        Department.id == unit_id,
        Department.tenant_id == tenant_id,
    )
    if for_update:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    unit = result.scalar_one_or_none()
    if unit is None:
        raise OrganizationUnitNotFoundError("organization unit not found")
    return unit


async def create_organization_unit(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    name: str,
    unit_type: OrganizationUnitType,
    parent_id: UUID | None,
    external_key: str | None,
    description: str,
    code: str | None,
) -> Department:
    unit_id = uuid4()
    parent = None
    if parent_id is not None:
        parent = await get_organization_unit(db, tenant_id, parent_id, for_update=True)
    ref = OrganizationUnitRef(
        id=unit_id,
        tenant_id=tenant_id,
        unit_type=unit_type,
        parent_id=parent_id,
        is_active=True,
    )
    validate_parent_assignment(unit=ref, parent=_as_ref(parent) if parent else None)
    normalized_name = normalize_unit_name(name)
    parent_scope = parent.slug if parent else unit_type.value
    slug = f"{_slug_part(parent_scope)}--{_slug_part(name)}--{str(unit_id)[:8]}"
    unit = Department(
        id=unit_id,
        tenant_id=tenant_id,
        name=name.strip(),
        slug=slug,
        unit_type=unit_type.value,
        normalized_name=normalized_name,
        external_key=external_key.strip() if external_key else None,
        parent_id=parent_id,
        is_active=True,
        archived_at=None,
        source_metadata={"origin": "manual"},
        legacy_root=False,
        description=description.strip(),
        code=code.strip() if code else None,
    )
    db.add(unit)
    await db.flush()
    return unit


async def update_organization_unit(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    unit_id: UUID,
    patch: dict[str, Any],
) -> Department:
    unit = await get_organization_unit(db, tenant_id, unit_id, for_update=True)
    parent_id = patch.get("parent_id", unit.parent_id)
    parent = None
    if parent_id is not None:
        parent = await get_organization_unit(db, tenant_id, parent_id, for_update=True)
    validate_parent_assignment(
        unit=OrganizationUnitRef(
            id=unit.id,
            tenant_id=tenant_id,
            unit_type=OrganizationUnitType(unit.unit_type),
            parent_id=parent_id,
            is_active=unit.is_active,
        ),
        parent=_as_ref(parent) if parent else None,
    )
    if "name" in patch:
        unit.name = patch["name"].strip()
        unit.normalized_name = normalize_unit_name(unit.name)
    unit.parent_id = parent_id
    for field in ("external_key", "description", "code"):
        if field in patch:
            value = patch[field]
            setattr(unit, field, value.strip() if isinstance(value, str) else value)
    await db.flush()
    return unit


async def archive_organization_unit(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    unit_id: UUID,
    reason: str,
) -> Department:
    from app.modules.positions.models import Position

    unit = await get_organization_unit(db, tenant_id, unit_id, for_update=True)
    child_result = await db.execute(
        select(Department.id)
        .where(
            Department.tenant_id == tenant_id,
            Department.parent_id == unit.id,
            Department.is_active.is_(True),
        )
        .limit(1)
    )
    if child_result.scalar_one_or_none() is not None:
        raise ValueError("archive child departments first")
    position_result = await db.execute(
        select(Position.id)
        .where(
            Position.tenant_id == tenant_id,
            Position.department_id == unit.id,
            Position.is_active.is_(True),
        )
        .limit(1)
    )
    if position_result.scalar_one_or_none() is not None:
        raise ValueError("organization unit still has active positions")
    unit.is_active = False
    unit.archived_at = datetime.now(UTC)
    metadata = dict(unit.source_metadata or {})
    metadata["archive_reason"] = reason.strip()
    unit.source_metadata = metadata
    await db.flush()
    return unit


def build_tree(
    units: list[Department],
    *,
    positions_by_unit: dict[UUID, list[dict[str, Any]]] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Build the tenant's unit tree and attach its staff projections.

    ``positions_by_unit`` is optional to keep the pure hierarchy helper useful
    to import/domain tests.  The HTTP service supplies it from tenant-scoped
    queries.  No position or employee object is loaded through a relationship
    here, which avoids accidental cross-tenant lazy loads.
    """
    positions_by_unit = positions_by_unit or {}
    nodes = {
        unit.id: {
            "id": unit.id,
            "name": unit.name,
            "slug": unit.slug,
            "unit_type": unit.unit_type,
            "parent_id": unit.parent_id,
            "external_key": unit.external_key,
            "is_active": unit.is_active,
            "legacy_root": unit.legacy_root,
            "description": unit.description,
            "code": unit.code,
            "created_at": unit.created_at,
            "children": [],
            "department_count": 0,
            "position_count": len(positions_by_unit.get(unit.id, [])),
            "employee_count": sum(item.get("employee_count", 0) for item in positions_by_unit.get(unit.id, [])),
            "ready_percent": 0,
            "positions": positions_by_unit.get(unit.id, []),
        }
        for unit in units
    }
    for unit in units:
        if unit.parent_id in nodes:
            nodes[unit.parent_id]["children"].append(nodes[unit.id])
    for node in nodes.values():
        node["children"].sort(key=lambda child: (normalize_unit_name(child["name"]), str(child["id"])))

    def roll_up(node: dict) -> tuple[int, int, int]:
        """Return (departments, positions, employees) below this node."""
        child_departments = 0
        child_positions = 0
        child_employees = 0
        for child in node["children"]:
            nested = roll_up(child)
            child_departments += (1 if child["unit_type"] == "department" else 0) + nested[0]
            child_positions += nested[1] + len(child.get("positions", []))
            child_employees += nested[2] + sum(item.get("employee_count", 0) for item in child.get("positions", []))
        node["department_count"] = child_departments
        node["position_count"] = len(node.get("positions", [])) + child_positions
        node["employee_count"] = (
            sum(item.get("employee_count", 0) for item in node.get("positions", [])) + child_employees
        )
        return child_departments, child_positions, child_employees

    branches = [nodes[u.id] for u in units if u.unit_type == "branch" and u.parent_id is None]
    # Existing flat records are department roots.  Include every non-branch
    # root, not only rows carrying the legacy_root flag, so old tenants cannot
    # disappear from the structure summary after a partial migration.
    legacy = [nodes[u.id] for u in units if u.unit_type != "branch" and u.parent_id is None]
    for root in (*branches, *legacy):
        roll_up(root)
    branches.sort(key=lambda node: (normalize_unit_name(node["name"]), str(node["id"])))
    legacy.sort(key=lambda node: (normalize_unit_name(node["name"]), str(node["id"])))
    return branches, legacy


async def load_structure_projections(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    units: Iterable[Department],
) -> dict[UUID, list[dict[str, Any]]]:
    """Load positions and tenant-local employee lists for the unit tree.

    Positions normally point to a normalized department via ``department_id``.
    For legacy rows, the old text department is matched only when it maps to a
    single unit name; ambiguous names are intentionally left unassigned rather
    than guessed into the wrong branch.
    """
    from app.models.enrollment import Enrollment
    from app.models.users import User
    from app.modules.positions.models import Position, PositionCourse

    unit_list = list(units)
    unit_by_id = {unit.id: unit for unit in unit_list}
    by_name: dict[str, list[Department]] = {}
    for unit in unit_list:
        by_name.setdefault(normalize_unit_name(unit.name), []).append(unit)

    position_result = await db.execute(
        select(Position)
        .where(Position.tenant_id == tenant_id, Position.is_active.is_(True))
        .order_by(Position.name, Position.id)
    )
    positions = list(position_result.scalars().all())
    position_ids = [position.id for position in positions]

    user_result = await db.execute(
        select(User)
        .where(
            User.tenant_id == tenant_id,
            User.position_id.in_(position_ids) if position_ids else User.position_id.is_(None),
        )
        .order_by(User.last_name, User.first_name, User.id)
    )
    employees_by_position: dict[UUID, list[User]] = {}
    for employee in user_result.scalars().all():
        if employee.position_id is not None:
            employees_by_position.setdefault(employee.position_id, []).append(employee)

    required_courses_by_position: dict[UUID, set[UUID]] = {}
    if position_ids:
        rules_result = await db.execute(
            select(PositionCourse.position_id, PositionCourse.course_id).where(
                PositionCourse.tenant_id == tenant_id,
                PositionCourse.required.is_(True),
                PositionCourse.position_id.in_(position_ids),
            )
        )
        for position_id, course_id in rules_result.all():
            required_courses_by_position.setdefault(position_id, set()).add(course_id)

    employee_ids = [employee.id for employees in employees_by_position.values() for employee in employees]
    enrollments_by_employee: dict[UUID, list[tuple[UUID, bool]]] = {}
    if employee_ids:
        enrollment_result = await db.execute(
            select(Enrollment.user_id, Enrollment.course_id, Enrollment.completed_at).where(
                Enrollment.tenant_id == tenant_id,
                Enrollment.user_id.in_(employee_ids),
            )
        )
        for employee_id, course_id, completed_at in enrollment_result.all():
            enrollments_by_employee.setdefault(employee_id, []).append((course_id, completed_at is not None))

    result: dict[UUID, list[dict[str, Any]]] = {}
    for position in positions:
        unit = unit_by_id.get(position.department_id)
        if unit is None:
            candidates = by_name.get(normalize_unit_name(position.department or ""), [])
            if len(candidates) == 1:
                unit = candidates[0]
        unit_id = unit.id if unit is not None else None
        if unit_id is None:
            # Keep the payload tenant-safe; an orphan legacy position is not
            # silently attached to a same-named unit in another branch.
            unit_id = UNASSIGNED_LEGACY_UNIT_ID

        required_courses = required_courses_by_position.get(position.id, set())
        employee_nodes: list[dict[str, Any]] = []
        assigned_total = 0
        completed_total = 0
        for employee in employees_by_position.get(position.id, []):
            enrollments = enrollments_by_employee.get(employee.id, [])
            enrolled_courses = {course_id for course_id, _ in enrollments}
            assigned_courses = required_courses | enrolled_courses
            completed_courses = {course_id for course_id, complete in enrollments if complete} & assigned_courses
            assigned = len(assigned_courses)
            completed = len(completed_courses)
            assigned_total += assigned
            completed_total += completed
            employee_nodes.append(
                {
                    "id": employee.id,
                    "full_name": f"{employee.last_name} {employee.first_name}".strip(),
                    "personnel_number": employee.personnel_number,
                    "is_active": employee.is_active,
                    "assigned_courses": assigned,
                    "completed_courses": completed,
                    "ready_percent": int(completed * 100 / assigned) if assigned else 0,
                }
            )

        result.setdefault(unit_id, []).append(
            {
                "id": position.id,
                "name": position.name,
                "department": unit.name if unit is not None else (position.department or "Не распределено"),
                "department_slug": unit.slug if unit is not None else None,
                "employee_count": len(employee_nodes),
                "ready_percent": int(completed_total * 100 / assigned_total) if assigned_total else 0,
                "employees": employee_nodes,
            }
        )
    return result
