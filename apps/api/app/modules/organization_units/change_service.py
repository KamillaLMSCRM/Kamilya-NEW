"""Serializable preview/confirmation adapter. Caller owns the transaction."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import Table, delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, InstrumentedAttribute

from app.models.courses import Course
from app.models.department import Department
from app.models.enrollment import Enrollment
from app.models.user_roles import UserRole
from app.models.users import User
from app.modules.cohorts.models import Cohort, CohortMember
from app.modules.positions.models import DepartmentCourse, Position, PositionCourse
from app.modules.staff_sync.models import StaffSyncIdentity
from app.modules.training_rules.models import OrganizationCourseRule

from .change_models import OrganizationChangePlan, TransferRetainedEnrollment
from .change_policy import build_change, fingerprint

type JSONObject = dict[str, Any]


class _MutableEmployee(Protocol):
    organization_unit_id: UUID | None
    position_id: UUID | None


class _MutableUnit(Protocol):
    parent_id: UUID | None


class _SnapshotModel(Protocol):
    tenant_id: InstrumentedAttribute[UUID]
    __table__: Table


def _json(value: object) -> object:
    if isinstance(value, UUID | datetime):
        return str(value)
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json(v) for v in value]
    return value


def _json_object(value: dict[str, object]) -> JSONObject:
    return cast(JSONObject, _json(value))


async def _rows(
    db: AsyncSession,
    model: type[DeclarativeBase],
    tenant_id: UUID,
    fields: tuple[str, ...],
) -> list[JSONObject]:
    typed_model = cast(type[_SnapshotModel], model)
    tenant_column = typed_model.tenant_id
    table = typed_model.__table__
    rows = (
        (
            await db.execute(
                select(*(getattr(model, f) for f in fields))
                .where(tenant_column == tenant_id)
                .order_by(*table.primary_key.columns)
                .limit(25001)
            )
        )
        .mappings()
        .all()
    )
    if len(rows) > 25000:
        raise ValueError("impact_snapshot_too_large")
    return [_json_object(dict(row)) for row in rows]


async def load_impact_snapshot(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
    data = {
        "units": await _rows(
            db,
            Department,
            tenant_id,
            (
                "id",
                "name",
                "parent_id",
                "unit_type",
                "is_active",
                "is_head_office",
                "head_user_id",
                "source_metadata",
                "external_key",
            ),
        ),
        "positions": await _rows(
            db, Position, tenant_id, ("id", "name", "department_id", "is_active", "source_metadata", "external_key")
        ),
        "users": await _rows(
            db,
            User,
            tenant_id,
            (
                "id",
                "first_name",
                "last_name",
                "personnel_number",
                "role",
                "organization_unit_id",
                "position_id",
                "is_active",
                "status",
            ),
        ),
        "courses": await _rows(db, Course, tenant_id, ("id", "title", "status", "current_release_id")),
        "enrollments": await _rows(
            db,
            Enrollment,
            tenant_id,
            ("id", "user_id", "course_id", "source", "status", "content_release_id", "completed_at"),
        ),
        "cohorts": await _rows(db, Cohort, tenant_id, ("id", "is_active", "responsible_user_id")),
        "members": await _rows(db, CohortMember, tenant_id, ("id", "cohort_id", "user_id")),
        "roles": await _rows(db, UserRole, tenant_id, ("id", "user_id", "role")),
        "identities": await _rows(
            db, StaffSyncIdentity, tenant_id, ("id", "source", "external_employee_id", "user_id")
        ),
        "retained": await _rows(db, TransferRetainedEnrollment, tenant_id, ("enrollment_id", "original_source")),
    }
    linked = {r["user_id"] for r in data["identities"]}
    for user in data["users"]:
        user["full_name"] = f'{user.pop("first_name")} {user.pop("last_name")}'.strip()
        user["hr_managed"] = user["id"] in linked
    rules = []
    for model, scope, ref in (
        (OrganizationCourseRule, "organization", None),
        (DepartmentCourse, "department", "department_id"),
        (PositionCourse, "position", "position_id"),
    ):
        fields = ("course_id", "required", ref) if ref else ("course_id", "required")
        for row in await _rows(db, model, tenant_id, fields):
            rules.append(
                {
                    "scope": scope,
                    "ref": row.get(ref) if ref else None,
                    "course_id": row["course_id"],
                    "required": row["required"],
                }
            )
    data["rules"] = rules
    return data


def _calculate(snapshot: JSONObject, command: JSONObject) -> JSONObject:
    result = build_change(snapshot, command)
    courses = {r["id"]: r for r in snapshot["courses"]}
    if any(not courses[r["course_id"]]["current_release_id"] for r in result["additions"]):
        raise ValueError("course_release_missing")
    return result


async def preview_change(db: AsyncSession, *, tenant_id: UUID, actor_id: UUID, command: JSONObject) -> JSONObject:
    count = await db.scalar(
        select(func.count())
        .select_from(OrganizationChangePlan)
        .where(
            OrganizationChangePlan.tenant_id == tenant_id,
            OrganizationChangePlan.actor_id == actor_id,
            OrganizationChangePlan.status == "ready",
            OrganizationChangePlan.expires_at > datetime.now(UTC),
        )
    )
    if count and count >= 50:
        raise ValueError("preview_limit")
    snapshot = await load_impact_snapshot(db, tenant_id)
    result = _calculate(snapshot, command)
    plan_id, expires = uuid4(), datetime.now(UTC) + timedelta(minutes=15)
    view = cast(JSONObject, result["view"]) | {"id": str(plan_id), "expires_at": expires.isoformat()}
    db.add(
        OrganizationChangePlan(
            id=plan_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            command=command,
            preview=view,
            fingerprint=fingerprint(snapshot),
            expires_at=expires,
            status="ready",
        )
    )
    await db.flush()
    return view


async def confirm_change(db: AsyncSession, *, tenant_id: UUID, actor_id: UUID, plan_id: UUID) -> JSONObject:
    plan = await db.scalar(
        select(OrganizationChangePlan)
        .where(
            OrganizationChangePlan.id == plan_id,
            OrganizationChangePlan.tenant_id == tenant_id,
            OrganizationChangePlan.actor_id == actor_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if plan is None:
        raise LookupError("plan_not_found")
    if plan.status == "succeeded":
        return dict(cast(JSONObject, plan.receipt))
    if plan.expires_at <= datetime.now(UTC):
        raise ValueError("preview_expired")
    snapshot = await load_impact_snapshot(db, tenant_id)
    if fingerprint(snapshot) != plan.fingerprint:
        raise ValueError("preview_stale")
    result = _calculate(snapshot, plan.command)
    unit = plan.command["organization_unit_id"]
    if plan.command["kind"] == "employee":
        employee_row = await db.scalar(
            select(User)
            .where(User.id == UUID(plan.command["target_id"]), User.tenant_id == tenant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if employee_row is None:
            raise LookupError("resource_not_found")
        employee = cast(_MutableEmployee, employee_row)
        employee.organization_unit_id = UUID(unit) if unit else None
        employee.position_id = UUID(plan.command["position_id"])
    else:
        unit_row = await db.scalar(
            select(Department)
            .where(Department.id == UUID(plan.command["target_id"]), Department.tenant_id == tenant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if unit_row is None:
            raise LookupError("resource_not_found")
        target_unit = cast(_MutableUnit, unit_row)
        target_unit.parent_id = UUID(unit) if unit else None
    courses = {r["id"]: r for r in snapshot["courses"]}
    for row in result["additions"]:
        db.add(
            Enrollment(
                id=uuid4(),
                tenant_id=tenant_id,
                user_id=UUID(row["user_id"]),
                course_id=UUID(row["course_id"]),
                source=row["source"],
                status="enrolled",
                content_release_id=UUID(courses[row["course_id"]]["current_release_id"]),
            )
        )
    for row in result["retained"]:
        await db.execute(
            insert(TransferRetainedEnrollment)
            .values(
                enrollment_id=UUID(row["enrollment_id"]),
                tenant_id=tenant_id,
                plan_id=plan.id,
                original_source=row["original_source"],
            )
            .on_conflict_do_nothing()
        )
    executed = datetime.now(UTC)
    receipt = {
        "plan_id": str(plan.id),
        "status": "succeeded",
        "affected_employees": len(result["affected_user_ids"]),
        "added": len(result["additions"]),
        "preserved": sum(r["user_id"] in result["affected_user_ids"] for r in snapshot["enrollments"]),
        "executed_at": executed.isoformat(),
    }
    plan.status, plan.receipt, plan.executed_at = "succeeded", receipt, executed
    await db.flush()
    return receipt


async def purge_change_plans(db: AsyncSession, tenant_id: UUID, *, dry_run: bool = True, batch_size: int = 100) -> int:
    """Owner-only bounded retention; never called by an HTTP/ordinary worker path.

    Requires the canonical administrative connection, not a session GUC. Caller
    owns commit/rollback. Durable markers outlive their nullable plan locator.
    """
    if not 1 <= batch_size <= 500:
        raise ValueError("invalid_retention_batch")
    if not await db.scalar(text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")):
        raise PermissionError("maintenance_owner_required")
    now = datetime.now(UTC)
    eligible = select(OrganizationChangePlan.id).where(
        OrganizationChangePlan.tenant_id == tenant_id,
        ((OrganizationChangePlan.status == "ready") & (OrganizationChangePlan.expires_at < now - timedelta(days=1)))
        | (
            (OrganizationChangePlan.status == "succeeded")
            & (OrganizationChangePlan.executed_at < now - timedelta(days=90))
        ),
    )
    eligible = (
        eligible.order_by(OrganizationChangePlan.created_at, OrganizationChangePlan.id)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    ids = list((await db.scalars(eligible)).all())
    if dry_run or not ids:
        return len(ids)
    result = cast(
        CursorResult[Any],
        await db.execute(
            delete(OrganizationChangePlan).where(
                OrganizationChangePlan.tenant_id == tenant_id,
                OrganizationChangePlan.id.in_(ids),
            )
        ),
    )
    return result.rowcount
