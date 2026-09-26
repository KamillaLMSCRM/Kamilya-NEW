"""Resolve one reporting principal to a bounded tenant audience."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department
from app.models.users import User
from app.modules.cohorts.models import Cohort, CohortMember
from app.modules.organization_scope import resolve_descendants
from app.modules.positions.models import Position
from app.modules.training_responsibility.policy import (
    ReportingScopeMode,
    decide_reporting_scope,
)


@dataclass(frozen=True, slots=True)
class ReportingScope:
    mode: ReportingScopeMode
    user_ids: frozenset[UUID] | None
    organization_unit_ids: tuple[UUID, ...] = ()
    cohort_ids: tuple[UUID, ...] = ()


async def resolve_reporting_scope(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    user_id: UUID,
    role: str,
) -> ReportingScope:
    """Return tenant-wide, restricted, or denied reporting access.

    A restricted audience is the union of active organization subtrees headed
    by the principal and active employee groups assigned to that principal.
    Tenant predicates remain explicit even though RLS is also authoritative.
    """

    if role in {"admin", "superadmin"}:
        return ReportingScope(mode=ReportingScopeMode.TENANT, user_ids=None)

    unit_ids = tuple(
        (await db.scalars(
            select(Department.id).where(
                Department.tenant_id == tenant_id,
                Department.head_user_id == user_id,
                Department.is_active.is_(True),
            )
        )).all()
    )
    cohort_ids = tuple(
        (await db.scalars(
            select(Cohort.id).where(
                Cohort.tenant_id == tenant_id,
                Cohort.responsible_user_id == user_id,
                Cohort.is_active.is_(True),
            )
        )).all()
    )
    mode = decide_reporting_scope(
        role,
        has_responsibilities=bool(unit_ids or cohort_ids),
    )
    if mode is not ReportingScopeMode.RESTRICTED:
        return ReportingScope(mode=mode, user_ids=None)

    descendant_ids = (
        await resolve_descendants(
            db,
            tenant_id,
            unit_ids,
            include_self=True,
            active_only=False,
        )
        if unit_ids
        else set()
    )
    audience: set[UUID] = set()
    if descendant_ids:
        rows = await db.scalars(
            select(User.id)
            .outerjoin(
                Position,
                (Position.id == User.position_id) & (Position.tenant_id == tenant_id),
            )
            .where(
                User.tenant_id == tenant_id,
                User.role == "student",
                or_(
                    User.organization_unit_id.in_(descendant_ids),
                    (User.organization_unit_id.is_(None))
                    & (Position.department_id.in_(descendant_ids)),
                ),
            )
        )
        audience.update(rows.all())
    if cohort_ids:
        rows = await db.scalars(
            select(CohortMember.user_id).where(
                CohortMember.tenant_id == tenant_id,
                CohortMember.cohort_id.in_(cohort_ids),
            )
        )
        audience.update(rows.all())

    return ReportingScope(
        mode=mode,
        user_ids=frozenset(audience),
        organization_unit_ids=unit_ids,
        cohort_ids=cohort_ids,
    )
