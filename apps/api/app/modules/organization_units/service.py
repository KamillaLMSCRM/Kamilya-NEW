from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department
from app.modules.organization_scope import (
    OrganizationScopeNotFoundError,
    resolve_ancestor_path,
    validate_move,
)

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
        id=cast(UUID, unit.id),
        tenant_id=cast(UUID, unit.tenant_id),
        unit_type=OrganizationUnitType(cast(str, unit.unit_type)),
        parent_id=cast(UUID | None, unit.parent_id),
        is_active=cast(bool, unit.is_active),
        is_head_office=getattr(unit, "is_head_office", False),
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


async def _validate_head_user(
    db: AsyncSession,
    tenant_id: UUID,
    head_user_id: UUID | None,
) -> None:
    if head_user_id is None:
        return
    from app.models.users import User

    exists = await db.scalar(
        select(User.id).where(
            User.id == head_user_id,
            User.tenant_id == tenant_id,
            User.role == "methodologist",
            User.is_active.is_(True),
            User.status == "active",
        )
    )
    if exists is None:
        raise ValueError("head_user_must_be_active_tenant_methodologist")


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
    is_head_office: bool = False,
    head_user_id: UUID | None = None,
) -> Department:
    unit_id = uuid4()
    parent = None
    if parent_id is not None:
        try:
            parent = await get_organization_unit(db, tenant_id, parent_id, for_update=True)
        except OrganizationUnitNotFoundError as exc:
            raise ValueError("cross_tenant_parent") from exc
    parent_path = []
    if parent is not None:
        try:
            parent_path = await resolve_ancestor_path(db, tenant_id, cast(UUID, parent.id))
        except OrganizationScopeNotFoundError as exc:
            raise ValueError("cross_tenant_parent") from exc
    ref = OrganizationUnitRef(
        id=unit_id,
        tenant_id=tenant_id,
        unit_type=unit_type,
        parent_id=parent_id,
        is_active=True,
        is_head_office=is_head_office,
    )
    validate_parent_assignment(
        unit=ref,
        parent=_as_ref(parent) if parent else None,
        parent_depth=0 if parent is None else len(parent_path) - 1,
    )
    duplicate = await db.execute(
        select(Department.id)
        .where(
            Department.tenant_id == tenant_id,
            Department.normalized_name == normalize_unit_name(name),
            Department.unit_type == unit_type.value,
            Department.parent_id == parent_id if parent_id is not None else Department.parent_id.is_(None),
            Department.is_active.is_(True),
        )
        .limit(1)
    )
    if duplicate.scalar_one_or_none() is not None:
        raise ValueError("duplicate_sibling")
    if is_head_office:
        existing_head_office = await db.execute(
            select(Department.id)
            .where(
                Department.tenant_id == tenant_id,
                Department.is_head_office.is_(True),
                Department.parent_id.is_(None),
                Department.is_active.is_(True),
            )
            .limit(1)
        )
        if existing_head_office.scalar_one_or_none() is not None:
            raise ValueError("head_office_exists")
    await _validate_head_user(db, tenant_id, head_user_id)
    normalized_name = normalize_unit_name(name)
    parent_scope = cast(str, parent.slug) if parent else unit_type.value
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
        is_head_office=is_head_office,
        description=description.strip(),
        code=code.strip() if code else None,
        head_user_id=head_user_id,
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
    await validate_move(db, tenant_id, cast(UUID, unit.id), parent_id)
    requested_head_office = bool(patch.get("is_head_office", getattr(unit, "is_head_office", False)))
    if requested_head_office and parent_id is not None:
        raise ValueError("head_office_must_be_root")
    if requested_head_office and not getattr(unit, "is_head_office", False):
        existing_head_office = await db.execute(
            select(Department.id)
            .where(
                Department.tenant_id == tenant_id,
                Department.is_head_office.is_(True),
                Department.is_active.is_(True),
                Department.id != unit.id,
            )
            .limit(1)
        )
        if existing_head_office.scalar_one_or_none() is not None:
            raise ValueError("head_office_exists")
    if "name" in patch or "unit_type" in patch:
        normalized_name = normalize_unit_name(patch.get("name", unit.name))
        unit_type = patch.get("unit_type", unit.unit_type)
        duplicate = await db.execute(
            select(Department.id)
            .where(
                Department.tenant_id == tenant_id,
                Department.normalized_name == normalized_name,
                Department.unit_type == getattr(unit_type, "value", unit_type),
                Department.parent_id == parent_id if parent_id is not None else Department.parent_id.is_(None),
                Department.id != unit.id,
                Department.is_active.is_(True),
            )
            .limit(1)
        )
        if duplicate.scalar_one_or_none() is not None:
            raise ValueError("duplicate_sibling")
    if "name" in patch:
        unit.name = patch["name"].strip()
        unit.normalized_name = normalize_unit_name(unit.name)
    unit.parent_id = parent_id
    unit.is_head_office = requested_head_office
    if "head_user_id" in patch:
        await _validate_head_user(db, tenant_id, patch["head_user_id"])
        unit.head_user_id = patch["head_user_id"]
    for field in ("external_key", "description", "code"):
        if field in patch:
            value = patch[field]
            setattr(unit, field, value.strip() if isinstance(value, str) else value)
    await db.flush()
    return unit


async def preview_organization_unit_move(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    unit_id: UUID,
    parent_id: UUID | None,
) -> dict[str, Any]:
    """Validate a move and summarize its tenant-local consequences.

    The preview deliberately uses the same ``validate_move`` seam as the write
    path.  A preview that succeeds therefore cannot disagree with the cycle or
    maximum-depth checks applied when the PATCH is committed.
    """

    from app.models.users import User
    from app.modules.positions.models import Position

    scope = await validate_move(db, tenant_id, unit_id, parent_id)
    affected_ids = tuple(scope.descendant_ids)
    affected_positions = int(
        await db.scalar(
            select(func.count(Position.id)).where(
                Position.tenant_id == tenant_id,
                Position.department_id.in_(affected_ids),
                Position.is_active.is_(True),
            )
        )
        or 0
    )
    affected_employees = int(
        await db.scalar(
            select(func.count(User.id)).where(
                User.tenant_id == tenant_id,
                User.organization_unit_id.in_(affected_ids),
                User.is_active.is_(True),
            )
        )
        or 0
    )
    resulting_depth = 0 if parent_id is None else scope.parent_depth + 1
    return {
        "unit_id": scope.unit_id,
        "parent_id": scope.parent_id,
        "affected_units": len(scope.descendant_ids),
        "affected_positions": affected_positions,
        "affected_employees": affected_employees,
        "resulting_depth": resulting_depth,
        "subtree_height": scope.subtree_height,
    }


async def archive_organization_unit(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    unit_id: UUID,
    reason: str,
) -> Department:
    from app.models.users import User
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
    employee_result = await db.execute(
        select(User.id)
        .where(
            User.tenant_id == tenant_id,
            User.organization_unit_id == unit.id,
            User.is_active.is_(True),
        )
        .limit(1)
    )
    if employee_result.scalar_one_or_none() is not None:
        raise ValueError("organization unit still has active employees")
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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build the tenant's unit tree and attach its staff projections.

    ``positions_by_unit`` is optional to keep the pure hierarchy helper useful
    to import/domain tests.  The HTTP service supplies it from tenant-scoped
    queries.  No position or employee object is loaded through a relationship
    here, which avoids accidental cross-tenant lazy loads.
    """
    positions_by_unit = positions_by_unit or {}
    nodes: dict[UUID, dict[str, Any]] = {
        cast(UUID, unit.id): {
            "id": cast(UUID, unit.id),
            "name": unit.name,
            "slug": unit.slug,
            "unit_type": unit.unit_type,
            "parent_id": unit.parent_id,
            "external_key": unit.external_key,
            "is_active": unit.is_active,
            "legacy_root": unit.legacy_root,
            "is_head_office": getattr(unit, "is_head_office", False),
            "head_user_id": getattr(unit, "head_user_id", None),
            "description": unit.description,
            "code": unit.code,
            "created_at": unit.created_at,
            "children": [],
            "department_count": 0,
            "position_count": len(positions_by_unit.get(cast(UUID, unit.id), [])),
            "employee_count": sum(
                item.get("employee_count", 0) for item in positions_by_unit.get(cast(UUID, unit.id), [])
            ),
            "ready_percent": 0,
            "positions": positions_by_unit.get(cast(UUID, unit.id), []),
        }
        for unit in units
    }
    for unit in units:
        runtime_parent_id = cast(UUID | None, unit.parent_id)
        runtime_unit_id = cast(UUID, unit.id)
        if runtime_parent_id in nodes:
            nodes[runtime_parent_id]["children"].append(nodes[runtime_unit_id])
    for node in nodes.values():
        node["children"].sort(key=lambda child: (normalize_unit_name(child["name"]), str(child["id"])))

    roots = [node for node in nodes.values() if node["parent_id"] not in nodes]

    def annotate(node: dict[str, Any], *, depth: int, breadcrumb: list[str]) -> None:
        node["depth"] = depth
        node["breadcrumb"] = [*breadcrumb, node["name"]]
        for child in node["children"]:
            annotate(child, depth=depth + 1, breadcrumb=node["breadcrumb"])

    def roll_up(node: dict[str, Any]) -> tuple[int, int, int]:
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

    root_ids = {node["id"] for node in roots}
    branches = [nodes[cast(UUID, u.id)] for u in units if u.unit_type == "branch" and cast(UUID, u.id) in root_ids]
    # The second collection contains every non-branch root for compatibility
    # with the historical two-list helper.  The HTTP adapter must expose only
    # nodes carrying ``legacy_root`` through its legacy projection; generic
    # organization/management roots belong exclusively to ``roots``.
    other_roots = [nodes[cast(UUID, u.id)] for u in units if u.unit_type != "branch" and cast(UUID, u.id) in root_ids]
    for root in roots:
        annotate(root, depth=0, breadcrumb=[])
        roll_up(root)
    branches.sort(key=lambda node: (normalize_unit_name(node["name"]), str(node["id"])))
    other_roots.sort(key=lambda node: (normalize_unit_name(node["name"]), str(node["id"])))
    return branches, other_roots


async def get_organization_unit_projection(
    db: AsyncSession,
    tenant_id: UUID,
    unit_id: UUID,
) -> dict[str, Any]:
    """Return one unit with its tenant-safe depth and breadcrumb metadata."""

    await get_organization_unit(db, tenant_id, unit_id)
    units = await list_organization_units(db, tenant_id)
    by_id = {cast(UUID, candidate.id): candidate for candidate in units}
    path_ids = await resolve_ancestor_path(db, tenant_id, unit_id)
    branches, other_roots = build_tree(units)
    node = next(node for root in branches + other_roots for node in _walk_tree(root) if node["id"] == unit_id)
    node["breadcrumb"] = [cast(str, by_id[path_id].name) for path_id in path_ids if path_id in by_id]
    node["depth"] = len(node["breadcrumb"]) - 1
    return node


def _walk_tree(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield node
    for child in node.get("children", []):
        yield from _walk_tree(child)


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
    unit_by_id = {cast(UUID, unit.id): unit for unit in unit_list}
    by_name: dict[str, list[Department]] = {}
    for unit in unit_list:
        by_name.setdefault(normalize_unit_name(cast(str, unit.name)), []).append(unit)

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
            employees_by_position.setdefault(cast(UUID, employee.position_id), []).append(employee)

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
        resolved_unit: Department | None = unit_by_id.get(cast(UUID, position.department_id))
        if resolved_unit is None:
            candidates = by_name.get(normalize_unit_name(position.department or ""), [])
            if len(candidates) == 1:
                resolved_unit = candidates[0]
        fallback_unit_id = cast(UUID, resolved_unit.id) if resolved_unit is not None else None
        if fallback_unit_id is None:
            # Keep the payload tenant-safe; an orphan legacy position is not
            # silently attached to a same-named unit in another branch.
            fallback_unit_id = UNASSIGNED_LEGACY_UNIT_ID

        runtime_position_id = cast(UUID, position.id)
        required_courses = required_courses_by_position.get(runtime_position_id, set())
        employee_groups: dict[UUID, list[dict[str, Any]]] = {}
        for employee in employees_by_position.get(runtime_position_id, []):
            enrollments = enrollments_by_employee.get(cast(UUID, employee.id), [])
            enrolled_courses = {course_id for course_id, _ in enrollments}
            assigned_courses = required_courses | enrolled_courses
            completed_courses = {course_id for course_id, complete in enrollments if complete} & assigned_courses
            assigned = len(assigned_courses)
            completed = len(completed_courses)
            employee_unit_id = getattr(employee, "organization_unit_id", None)
            if isinstance(employee_unit_id, UUID) and employee_unit_id not in unit_by_id:
                employee_unit_id = UNASSIGNED_LEGACY_UNIT_ID
            elif not isinstance(employee_unit_id, UUID):
                employee_unit_id = fallback_unit_id
            employee_groups.setdefault(employee_unit_id, []).append(
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

        if not employee_groups:
            employee_groups[fallback_unit_id] = []
        for employee_unit_id, employee_nodes in employee_groups.items():
            target_unit = unit_by_id.get(employee_unit_id)
            assigned_total = sum(item["assigned_courses"] for item in employee_nodes)
            completed_total = sum(item["completed_courses"] for item in employee_nodes)
            result.setdefault(employee_unit_id, []).append(
                {
                    "id": position.id,
                    "name": position.name,
                    "department": target_unit.name
                    if target_unit is not None
                    else (position.department or "Не распределено"),
                    "department_slug": target_unit.slug if target_unit is not None else None,
                    "employee_count": len(employee_nodes),
                    "ready_percent": int(completed_total * 100 / assigned_total) if assigned_total else 0,
                    "employees": employee_nodes,
                }
            )
    return result
