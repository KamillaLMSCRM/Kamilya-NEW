"""Tenant-scoped storage reads for the mandatory-training matrix."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.courses.models import Course
from app.modules.enrollments.occurrences import is_current_occurrence
from app.modules.mandatory_training.requirements import EnrollmentAssignment
from app.modules.mandatory_training.schemas import MandatoryTrainingFilter
from app.modules.organization_scope import resolve_ancestor_paths, resolve_descendants
from app.modules.positions.models import Position


@dataclass(frozen=True, slots=True)
class EmployeeContext:
    user: User
    position_name: str | None
    organization_unit_id: UUID | None
    organization_unit_path_ids: tuple[UUID, ...]
    organization_unit_path_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CourseContext:
    title: str
    delivery_type: str


async def list_employee_contexts(
    db: AsyncSession,
    tenant_id: UUID,
    filters: MandatoryTrainingFilter,
    *,
    max_users: int,
) -> list[EmployeeContext]:
    stmt = (
        select(User, Position.name)
        .outerjoin(
            Position,
            (Position.id == User.position_id) & (Position.tenant_id == tenant_id),
        )
        .where(User.tenant_id == tenant_id, User.role == "student")
        .order_by(User.last_name, User.first_name, User.id)
        .limit(max_users + 1)
    )
    if not filters.include_inactive:
        stmt = stmt.where(User.is_active.is_(True), User.status == "active")
    if filters.responsible_user_ids is not None:
        stmt = stmt.where(
            User.id.in_(filters.responsible_user_ids)
            if filters.responsible_user_ids
            else false()
        )
    if filters.position_id is not None:
        stmt = stmt.where(User.position_id == filters.position_id)
    if filters.search:
        pattern = f"%{filters.search.strip()}%"
        stmt = stmt.where(
            or_(
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
                User.personnel_number.ilike(pattern),
                User.email.ilike(pattern),
            )
        )
    if filters.organization_unit_id is not None:
        unit_scope = await resolve_descendants(
            db,
            tenant_id,
            [filters.organization_unit_id],
            include_self=True,
            active_only=not filters.include_inactive,
        )
        stmt = stmt.where(
            or_(
                User.organization_unit_id.in_(unit_scope),
                (User.organization_unit_id.is_(None)) & (Position.department_id.in_(unit_scope)),
            )
        )

    rows = list((await db.execute(stmt)).all())
    if len(rows) > max_users:
        raise ValueError("mandatory_training_scope_too_large")

    unresolved_position_ids = {
        user.position_id
        for user, _ in rows
        if user.organization_unit_id is None
        and isinstance(user.position_id, UUID)
    }
    legacy_units: dict[UUID, UUID] = {}
    if unresolved_position_ids:
        legacy_rows = await db.execute(
            select(Position.id, Position.department_id).where(
                Position.tenant_id == tenant_id,
                Position.id.in_(unresolved_position_ids),
            )
        )
        legacy_units.update(
            (position_id, department_id)
            for position_id, department_id in legacy_rows.all()
            if isinstance(department_id, UUID)
        )

    placement_by_user = {
        user.id: (
            user.organization_unit_id
            if isinstance(user.organization_unit_id, UUID)
            else legacy_units.get(user.position_id)
        )
        for user, _ in rows
    }
    placements = {
        placement_id
        for placement_id in placement_by_user.values()
        if isinstance(placement_id, UUID)
    }
    paths = await resolve_ancestor_paths(db, tenant_id, placements) if placements else {}
    all_unit_ids = {unit_id for path in paths.values() for unit_id in path}
    unit_names: dict[UUID, str] = {}
    if all_unit_ids:
        unit_rows = await db.execute(
            select(Department.id, Department.name).where(
                Department.tenant_id == tenant_id,
                Department.id.in_(all_unit_ids),
            )
        )
        unit_names = {
            unit_id: unit_name
            for unit_id, unit_name in unit_rows.all()
        }

    contexts: list[EmployeeContext] = []
    for user, position_name in rows:
        placement_id = placement_by_user[user.id]
        path = tuple(paths.get(placement_id, ())) if placement_id else ()
        contexts.append(EmployeeContext(
            user=user,
            position_name=position_name,
            organization_unit_id=placement_id,
            organization_unit_path_ids=path,
            organization_unit_path_names=tuple(unit_names.get(unit_id, "") for unit_id in path),
        ))
    return contexts


async def list_current_enrollments(
    db: AsyncSession,
    tenant_id: UUID,
    user_ids: Iterable[UUID],
) -> dict[UUID, list[EnrollmentAssignment]]:
    ids = tuple(dict.fromkeys(user_ids))
    if not ids:
        return {}
    rows = await db.execute(
        select(
            Enrollment.user_id,
            Enrollment.id,
            Enrollment.course_id,
            Enrollment.source,
            Enrollment.status,
        ).where(
            Enrollment.tenant_id == tenant_id,
            Enrollment.user_id.in_(ids),
            Enrollment.status.notin_(("cancelled", "superseded")),
            is_current_occurrence(),
        )
    )
    result: dict[UUID, list[EnrollmentAssignment]] = {}
    for user_id, enrollment_id, course_id, source, status in rows.all():
        result.setdefault(user_id, []).append(EnrollmentAssignment(
            enrollment_id=enrollment_id,
            course_id=course_id,
            source=source,
            status=status,
        ))
    return result


async def load_course_contexts(
    db: AsyncSession,
    tenant_id: UUID,
    course_ids: Iterable[UUID],
) -> dict[UUID, CourseContext]:
    ids = tuple(dict.fromkeys(course_ids))
    if not ids:
        return {}
    rows = await db.execute(
        select(Course.id, Course.title, Course.delivery_type).where(
            Course.tenant_id == tenant_id,
            Course.id.in_(ids),
        )
    )
    return {
        course_id: CourseContext(title=title, delivery_type=delivery_type)
        for course_id, title, delivery_type in rows.all()
    }


async def load_source_names(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    position_ids: Iterable[UUID],
    unit_ids: Iterable[UUID],
) -> tuple[dict[UUID, str], dict[UUID, str]]:
    positions: dict[UUID, str] = {}
    units: dict[UUID, str] = {}
    position_scope = tuple(dict.fromkeys(position_ids))
    unit_scope = tuple(dict.fromkeys(unit_ids))
    if position_scope:
        position_rows = (await db.execute(
            select(Position.id, Position.name).where(
                Position.tenant_id == tenant_id,
                Position.id.in_(position_scope),
            )
        )).all()
        positions = {
            position_id: position_name
            for position_id, position_name in position_rows
        }
    if unit_scope:
        unit_rows = (await db.execute(
            select(Department.id, Department.name).where(
                Department.tenant_id == tenant_id,
                Department.id.in_(unit_scope),
            )
        )).all()
        units = {
            unit_id: unit_name
            for unit_id, unit_name in unit_rows
        }
    return positions, units
