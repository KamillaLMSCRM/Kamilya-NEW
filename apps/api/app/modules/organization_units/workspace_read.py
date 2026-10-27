"""Tenant organization metadata and server-paginated employee roster."""

from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.models.department import Department
from app.models.users import User
from app.modules.positions.models import Position
from app.modules.staff_sync.models import StaffSyncIdentity

from .change_policy import ancestor_ids, hr_managed

type JSONObject = dict[str, Any]


async def workspace_units(db: AsyncSession, tenant_id: UUID) -> JSONObject:
    units = list(
        (
            await db.scalars(
                select(Department).where(Department.tenant_id == tenant_id).order_by(Department.name, Department.id)
            )
        ).all()
    )
    positions = list(
        (
            await db.scalars(
                select(Position).where(Position.tenant_id == tenant_id).order_by(Position.name, Position.id)
            )
        ).all()
    )
    mapping = {
        str(u.id): {
            "id": str(u.id),
            "name": u.name,
            "parent_id": str(u.parent_id) if u.parent_id else None,
            "unit_type": u.unit_type,
            "is_active": u.is_active,
            "is_head_office": u.is_head_office,
            "head_user_id": str(u.head_user_id) if u.head_user_id else None,
            "source_metadata": u.source_metadata,
            "hr_managed": hr_managed({"source_metadata": u.source_metadata}),
        }
        for u in units
    }
    return {
        "units": mapping,
        "positions": [
            {
                "id": str(p.id),
                "name": p.name,
                "is_active": p.is_active,
                "department_id": str(p.department_id) if p.department_id else None,
            }
            for p in positions
        ],
    }


def _employee_query(tenant_id: UUID, access: str) -> Select[Any]:
    query = select(
        User,
        Position.name.label("position_name"),
        func.coalesce(User.organization_unit_id, Position.department_id).label("effective_unit_id"),
        select(StaffSyncIdentity.id)
        .where(StaffSyncIdentity.tenant_id == tenant_id, StaffSyncIdentity.user_id == User.id)
        .exists()
        .label("hr_managed"),
    )
    query = query.outerjoin(Position, and_(Position.id == User.position_id, Position.tenant_id == tenant_id)).where(
        User.tenant_id == tenant_id, User.role == "student"
    )
    active = and_(User.is_active.is_(True), User.status == "active")
    if access == "active":
        query = query.where(active)
    elif access == "inactive":
        query = query.where(~active)
    return query


async def workspace_overview(db: AsyncSession, tenant_id: UUID, access: str) -> JSONObject:
    data = await workspace_units(db, tenant_id)
    rows = (
        await db.execute(
            _employee_query(tenant_id, access)
            .with_only_columns(func.coalesce(User.organization_unit_id, Position.department_id), func.count(User.id))
            .group_by(func.coalesce(User.organization_unit_id, Position.department_id))
        )
    ).all()
    counts = {str(uid) if uid else None: count for uid, count in rows}
    usage = (
        await db.execute(
            _employee_query(tenant_id, access)
            .with_only_columns(
                User.position_id, func.coalesce(User.organization_unit_id, Position.department_id), func.count(User.id)
            )
            .group_by(User.position_id, func.coalesce(User.organization_unit_id, Position.department_id))
        )
    ).all()
    usage_by_position: dict[str, dict[str, int]] = {}
    for pid, uid, count in usage:
        usage_by_position.setdefault(str(pid), {})[str(uid) if uid else "unplaced"] = count
    for position in data["positions"]:
        position["unit_counts"] = usage_by_position.get(position["id"], {})
        position["employee_count"] = sum(position["unit_counts"].values())
    mapping = data["units"]
    paths = {key: ancestor_ids(mapping, key) for key in mapping}
    subtree_counts = dict.fromkeys(mapping, 0)
    for key, path in paths.items():
        for ancestor in path:
            subtree_counts[ancestor] += counts.get(key, 0)
    for key, unit in mapping.items():
        path = paths[key]
        unit["breadcrumb"] = [mapping[p]["name"] for p in path]
        unit["direct_count"] = counts.get(key, 0)
        unit["subtree_count"] = subtree_counts[key]
        unit.pop("source_metadata")
    return {
        "units": list(mapping.values()),
        "positions": data["positions"],
        "total": sum(counts.values()),
        "unplaced_count": counts.get(None, 0),
    }


async def employee_roster(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    unit_id: UUID | None,
    unplaced: bool,
    scope: str,
    access: str,
    q: str,
    position_id: UUID | None,
    missing_position: bool,
    page: int,
    page_size: int,
) -> JSONObject:
    data = await workspace_units(db, tenant_id)
    mapping = data["units"]
    query = _employee_query(tenant_id, access)
    effective = func.coalesce(User.organization_unit_id, Position.department_id)
    if unit_id:
        if str(unit_id) not in mapping:
            raise LookupError("resource_not_found")
        ids = (
            [uid for uid in mapping if str(unit_id) in ancestor_ids(mapping, uid)]
            if scope == "subtree"
            else [str(unit_id)]
        )
        query = query.where(effective.in_([UUID(uid) for uid in ids]))
    elif unplaced:
        query = query.where(effective.is_(None))
    if position_id:
        if not any(p["id"] == str(position_id) for p in data["positions"]):
            raise LookupError("resource_not_found")
        query = query.where(User.position_id == position_id)
    elif missing_position:
        query = query.where(User.position_id.is_(None))
    if q.strip():
        # SQL wildcards are literal search characters, not an accidental full scan.
        # Production C collation does not fold Cyrillic with ILIKE (SQL-NAME-001).
        # Keep the existing ICU collation local to both comparison operands.
        needle = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(
            or_(
                func.lower(func.concat(User.first_name, " ", User.last_name).collate("und-x-icu")).like(
                    func.lower(literal(needle).collate("und-x-icu")), escape="\\"
                ),
                func.lower(User.personnel_number.collate("und-x-icu")).like(
                    func.lower(literal(needle).collate("und-x-icu")), escape="\\"
                ),
            )
        )
    total = int(await db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    page = min(page, max(1, (total + page_size - 1) // page_size))
    rows = (
        await db.execute(
            query.order_by(User.personnel_number.asc().nulls_last(), User.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items = [
        {
            "id": str(u.id),
            "full_name": f"{u.first_name} {u.last_name}".strip(),
            "personnel_number": u.personnel_number,
            "is_active": bool(u.is_active and u.status == "active"),
            "organization_unit_id": str(u.organization_unit_id) if u.organization_unit_id else None,
            "effective_unit_id": str(effective_id) if effective_id else None,
            "placement_source": "explicit"
            if u.organization_unit_id
            else "position_fallback"
            if effective_id
            else "none",
            "position_id": str(u.position_id) if u.position_id else None,
            "position_name": name,
            "hr_managed": bool(managed),
        }
        for u, name, effective_id, managed in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}
