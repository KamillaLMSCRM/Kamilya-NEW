"""Atomic application of one approved staff import proposal."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department
from app.models.staff_import_session import StaffImportSession, StaffImportSessionEvent
from app.models.users import User
from app.modules.organization_units.service import normalize_unit_name
from app.modules.positions.batch_service import apply_rules_for_users
from app.modules.positions.models import Position
from app.modules.staff_import_legacy_adapter import LEGACY_ROOT_EXTERNAL_KEY
from app.modules.staff_import_matching import (
    ImportHierarchyConflictError,
    normalize_import_key,
    topologically_order_organization_units,
)

from .persistence import get_import_session, record_to_domain
from .schemas import ImportSessionState, MatchAction, OrganizationUnitProposal
from .state_machine import apply_transition, compute_proposal_hash


class ImportCommitConflictError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GenericUnitCommitPlanItem:
    proposal: OrganizationUnitProposal
    existing: Department | None


def build_generic_unit_commit_plan(
    proposals: Sequence[OrganizationUnitProposal],
    *,
    existing_units: Sequence[Department],
) -> tuple[GenericUnitCommitPlanItem, ...]:
    """Validate generic units and resolve stable existing identities pre-write."""

    existing_by_external: dict[str, Department] = {}
    for unit in existing_units:
        key = normalize_import_key(unit.external_key)
        if not key:
            continue
        if key in existing_by_external:
            raise ImportCommitConflictError(f"ambiguous parent external key: {unit.external_key}")
        existing_by_external[key] = unit

    try:
        ordered = topologically_order_organization_units(
            proposals,
            known_external_keys=existing_by_external,
        )
    except ImportHierarchyConflictError as exc:
        raise ImportCommitConflictError(str(exc)) from exc

    incoming_keys = {normalize_import_key(item.external_key) for item in ordered}
    resolved_existing_by_key: dict[str, Department] = {}
    plan: list[GenericUnitCommitPlanItem] = []
    for proposal in ordered:
        if proposal.is_head_office and proposal.parent_external_key is not None:
            raise ImportCommitConflictError("head office must be a root organization unit")
        key = normalize_import_key(proposal.external_key)
        existing = existing_by_external.get(key)
        if existing is not None:
            existing_type = getattr(existing.unit_type, "value", existing.unit_type)
            if existing_type != proposal.unit_type.value:
                raise ImportCommitConflictError(f"organization unit type mismatch: {proposal.external_key}")
        else:
            parent_key = normalize_import_key(proposal.parent_external_key)
            parent = resolved_existing_by_key.get(parent_key) or existing_by_external.get(parent_key)
            if parent_key and parent_key in incoming_keys and parent_key not in resolved_existing_by_key:
                parent = None
            normalized_name = normalize_unit_name(proposal.name)
            candidates = [
                unit
                for unit in existing_units
                if unit.parent_id == (parent.id if parent is not None else None)
                and normalize_unit_name(unit.name) == normalized_name
                and getattr(unit.unit_type, "value", unit.unit_type) == proposal.unit_type.value
            ]
            if len(candidates) > 1:
                raise ImportCommitConflictError(f"ambiguous organization unit {proposal.name}")
            existing = candidates[0] if candidates else None
        plan.append(GenericUnitCommitPlanItem(proposal=proposal, existing=existing))
        if existing is not None:
            resolved_existing_by_key[key] = existing
    return tuple(plan)


def _slug_part(value: str) -> str:
    return "-".join(normalize_unit_name(value).split())[:80] or "unit"


def _is_legacy_compatibility_root(external_key: str) -> bool:
    return external_key == LEGACY_ROOT_EXTERNAL_KEY or external_key.startswith("legacy:root-department:")


def _active_action(action: MatchAction) -> bool:
    return action not in {MatchAction.SKIP, MatchAction.CONFLICT}


async def _tenant_units(db: AsyncSession, tenant_id: UUID) -> list[Department]:
    result = await db.execute(select(Department).where(Department.tenant_id == tenant_id).with_for_update())
    return list(result.scalars().all())


def _one_or_none(values: list[Any], *, conflict: str) -> Any:
    if len(values) > 1:
        raise ImportCommitConflictError(conflict)
    return values[0] if values else None


async def commit_approved_import_session(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    session_id: UUID,
    actor_id: UUID,
    revision: str,
    now: datetime | None = None,
) -> StaffImportSession:
    record = await get_import_session(
        db,
        tenant_id=tenant_id,
        session_id=session_id,
        for_update=True,
    )
    if record.state == ImportSessionState.COMMITTED.value:
        if record.approved_revision != revision:
            raise ImportCommitConflictError("committed revision differs from request")
        return record
    domain = record_to_domain(record)
    if domain.state is not ImportSessionState.APPROVED or domain.proposal is None:
        raise ImportCommitConflictError("only an approved proposal can be committed")
    if domain.approved_revision != revision or domain.proposal.revision != revision:
        raise ImportCommitConflictError("approved proposal revision mismatch")
    if domain.proposal.revision_hash != compute_proposal_hash(domain.proposal):
        raise ImportCommitConflictError("approved proposal hash mismatch")

    # Validate and resolve the complete generic graph while the proposal is
    # still approved. Invalid parent references and cycles therefore cannot
    # move the session to COMMITTING or create any rows.
    existing_units = await _tenant_units(db, tenant_id)
    generic_plan = (
        build_generic_unit_commit_plan(domain.proposal.organization_units, existing_units=existing_units)
        if domain.proposal.organization_units
        else None
    )

    timestamp = now or datetime.now(UTC)
    committing = apply_transition(domain, ImportSessionState.COMMITTING, now=timestamp)
    record.state = committing.state.value
    db.add(
        StaffImportSessionEvent(
            tenant_id=tenant_id,
            session_id=record.id,
            actor_id=actor_id,
            from_state=ImportSessionState.APPROVED.value,
            to_state=ImportSessionState.COMMITTING.value,
            event_type="commit_started",
            event_metadata={"revision": revision},
        )
    )
    await db.flush()

    counts = {
        "branches_created": 0,
        "branches_updated": 0,
        "departments_created": 0,
        "departments_updated": 0,
        "positions_created": 0,
        "positions_updated": 0,
        "staff_created": 0,
        "staff_updated": 0,
        "unchanged": 0,
        "skipped": 0,
    }
    affected_user_ids: set[UUID] = set()
    units = existing_units
    units_by_external = {unit.external_key: unit for unit in units if unit.external_key}
    resolved_units: dict[str, Department] = {}

    if generic_plan is not None:
        for plan_item in generic_plan:
            proposal = plan_item.proposal
            parent_key = normalize_import_key(proposal.parent_external_key)
            parent = resolved_units.get(parent_key) or next(
                (
                    unit
                    for key, unit in units_by_external.items()
                    if normalize_import_key(key) == parent_key
                ),
                None,
            )
            if parent_key and parent is None:
                raise ImportCommitConflictError(
                    f"approved organization unit parent is missing: {proposal.parent_external_key}"
                )
            unit = plan_item.existing
            if unit is None:
                unit_id = uuid4()
                scope = parent.slug if parent is not None else "root"
                unit = Department(
                    id=unit_id,
                    tenant_id=tenant_id,
                    name=proposal.name,
                    slug=f"{_slug_part(scope)}--{_slug_part(proposal.name)}--{str(unit_id)[:8]}",
                    unit_type=proposal.unit_type.value,
                    normalized_name=normalize_unit_name(proposal.name),
                    external_key=proposal.external_key,
                    parent_id=parent.id if parent is not None else None,
                    is_active=True,
                    source_metadata={"origin": "adaptive_import", "session_id": str(record.id)},
                    legacy_root=_is_legacy_compatibility_root(proposal.external_key),
                    is_head_office=proposal.is_head_office,
                    description="",
                )
                db.add(unit)
                units.append(unit)
                counts["organization_units_created"] = counts.get("organization_units_created", 0) + 1
                count_key = f"{proposal.unit_type.value}s_created"
                if count_key in counts:
                    counts[count_key] += 1
            else:
                changed = (
                    unit.name != proposal.name
                    or unit.parent_id != (parent.id if parent is not None else None)
                    or unit.unit_type != proposal.unit_type.value
                    or unit.external_key != proposal.external_key
                    or unit.is_head_office != proposal.is_head_office
                    or unit.legacy_root != _is_legacy_compatibility_root(proposal.external_key)
                )
                unit.name = proposal.name
                unit.normalized_name = normalize_unit_name(proposal.name)
                unit.unit_type = proposal.unit_type.value
                unit.parent_id = parent.id if parent is not None else None
                unit.external_key = proposal.external_key
                unit.is_active = True
                unit.is_head_office = proposal.is_head_office
                unit.legacy_root = _is_legacy_compatibility_root(proposal.external_key)
                if changed:
                    counts["organization_units_updated"] = counts.get("organization_units_updated", 0) + 1
                    count_key = f"{proposal.unit_type.value}s_updated"
                    if count_key in counts:
                        counts[count_key] += 1
                else:
                    counts["unchanged"] += 1
            units_by_external[proposal.external_key] = unit
            resolved_units[proposal.external_key] = unit
            await db.flush()

    for proposal in (() if generic_plan is not None else domain.proposal.branches):
        if not _active_action(proposal.action):
            counts["skipped"] += 1
            continue
        unit = units_by_external.get(proposal.external_key)
        if unit is None:
            normalized = normalize_unit_name(proposal.branch_name)
            unit = _one_or_none(
                [u for u in units if u.parent_id is None and u.normalized_name == normalized],
                conflict=f"ambiguous branch {proposal.branch_name}",
            )
        if unit is None:
            unit_id = uuid4()
            unit = Department(
                id=unit_id,
                tenant_id=tenant_id,
                name=proposal.branch_name,
                slug=f"branch--{_slug_part(proposal.branch_name)}--{str(unit_id)[:8]}",
                unit_type="branch",
                normalized_name=normalize_unit_name(proposal.branch_name),
                external_key=proposal.external_key,
                is_active=True,
                source_metadata={"origin": "adaptive_import", "session_id": str(record.id)},
                legacy_root=False,
                description="",
            )
            db.add(unit)
            units.append(unit)
            counts["branches_created"] += 1
        else:
            changed = (
                unit.name != proposal.branch_name
                or unit.unit_type != "branch"
                or unit.external_key != proposal.external_key
                or unit.parent_id is not None
                or unit.legacy_root
            )
            unit.name = proposal.branch_name
            unit.normalized_name = normalize_unit_name(proposal.branch_name)
            unit.unit_type = "branch"
            unit.parent_id = None
            unit.external_key = proposal.external_key
            unit.legacy_root = False
            unit.is_active = True
            if changed:
                counts["branches_updated"] += 1
            else:
                counts["unchanged"] += 1
        units_by_external[proposal.external_key] = unit
        resolved_units[proposal.external_key] = unit
        await db.flush()

    for proposal in (() if generic_plan is not None else domain.proposal.departments):
        if not _active_action(proposal.action):
            counts["skipped"] += 1
            continue
        parent = None
        legacy_root = proposal.branch_external_key == LEGACY_ROOT_EXTERNAL_KEY
        if not legacy_root:
            parent = resolved_units.get(proposal.branch_external_key) or units_by_external.get(
                proposal.branch_external_key
            )
            if parent is None or parent.unit_type != "branch":
                raise ImportCommitConflictError(
                    f"approved department parent is missing: {proposal.branch_external_key}"
                )
        unit = units_by_external.get(proposal.external_key)
        if unit is None:
            normalized = normalize_unit_name(proposal.department_name)
            unit = _one_or_none(
                [
                    item
                    for item in units
                    if item.parent_id == (parent.id if parent else None)
                    and item.normalized_name == normalized
                    and item.unit_type == "department"
                ],
                conflict=f"ambiguous department {proposal.department_name}",
            )
        if unit is None:
            unit_id = uuid4()
            scope = parent.slug if parent else "legacy-root"
            unit = Department(
                id=unit_id,
                tenant_id=tenant_id,
                name=proposal.department_name,
                slug=f"{_slug_part(scope)}--{_slug_part(proposal.department_name)}--{str(unit_id)[:8]}",
                unit_type="department",
                normalized_name=normalize_unit_name(proposal.department_name),
                external_key=proposal.external_key,
                parent_id=parent.id if parent else None,
                is_active=True,
                source_metadata={"origin": "adaptive_import", "session_id": str(record.id)},
                legacy_root=legacy_root,
                description="",
            )
            db.add(unit)
            units.append(unit)
            counts["departments_created"] += 1
        else:
            changed = (
                unit.name != proposal.department_name
                or unit.parent_id != (parent.id if parent else None)
                or unit.external_key != proposal.external_key
            )
            unit.name = proposal.department_name
            unit.normalized_name = normalize_unit_name(proposal.department_name)
            unit.unit_type = "department"
            unit.parent_id = parent.id if parent else None
            unit.external_key = proposal.external_key
            unit.legacy_root = legacy_root
            unit.is_active = True
            if changed:
                counts["departments_updated"] += 1
            else:
                counts["unchanged"] += 1
        units_by_external[proposal.external_key] = unit
        resolved_units[proposal.external_key] = unit
        await db.flush()

    # Position eagerly joins its optional department.  PostgreSQL rejects a
    # blanket FOR UPDATE across the nullable side of that outer join, so lock
    # only the position rows that this commit reconciles.
    positions_result = await db.execute(
        select(Position).where(Position.tenant_id == tenant_id).with_for_update(of=Position)
    )
    positions = list(positions_result.scalars().all())
    positions_by_external = {position.external_key: position for position in positions if position.external_key}
    resolved_positions: dict[str, Position] = {}
    for proposal in domain.proposal.positions:
        if not _active_action(proposal.action):
            counts["skipped"] += 1
            continue
        unit_key = (
            proposal.organization_unit_external_key
            or proposal.department_external_key
            or proposal.branch_external_key
        )
        unit = resolved_units.get(unit_key) or units_by_external.get(unit_key)
        if unit is None and unit_key:
            raise ImportCommitConflictError(f"approved position unit is missing: {unit_key}")
        position = positions_by_external.get(proposal.external_key)
        if position is None:
            normalized = normalize_unit_name(proposal.position_name)
            position = _one_or_none(
                [
                    item
                    for item in positions
                    if item.department_id == (unit.id if unit is not None else None)
                    and item.normalized_name == normalized
                ],
                conflict=f"ambiguous position {proposal.position_name}",
            )
        if position is None:
            position = Position(
                id=uuid4(),
                tenant_id=tenant_id,
                name=proposal.position_name,
                normalized_name=normalize_unit_name(proposal.position_name),
                external_key=proposal.external_key,
                source_metadata={"origin": "adaptive_import", "session_id": str(record.id)},
                is_active=True,
                department=unit.name if unit is not None else "",
                department_id=unit.id if unit is not None else None,
                level="",
                responsibilities="",
                requirements="",
                employee_count=0,
            )
            db.add(position)
            positions.append(position)
            counts["positions_created"] += 1
        else:
            changed = (
                position.name != proposal.position_name
                or position.department_id != (unit.id if unit is not None else None)
                or position.external_key != proposal.external_key
            )
            position.name = proposal.position_name
            position.normalized_name = normalize_unit_name(proposal.position_name)
            position.external_key = proposal.external_key
            position.department = unit.name if unit is not None else ""
            position.department_id = unit.id if unit is not None else None
            position.is_active = True
            if changed:
                counts["positions_updated"] += 1
            else:
                counts["unchanged"] += 1
        positions_by_external[proposal.external_key] = position
        resolved_positions[proposal.external_key] = position
        await db.flush()

    personnel_numbers = [
        proposal.personnel_number for proposal in domain.proposal.staff if _active_action(proposal.action)
    ]
    users_result = await db.execute(
        select(User)
        .where(
            User.tenant_id == tenant_id,
            User.personnel_number.in_(personnel_numbers) if personnel_numbers else User.id.is_(None),
        )
        .with_for_update()
    )
    users_by_personnel = {
        normalize_unit_name(user.personnel_number): user
        for user in users_result.scalars().all()
        if user.personnel_number
    }
    for proposal in domain.proposal.staff:
        if not _active_action(proposal.action):
            counts["skipped"] += 1
            continue
        position = resolved_positions.get(proposal.position_external_key) or positions_by_external.get(
            proposal.position_external_key
        )
        if position is None:
            raise ImportCommitConflictError(f"approved staff position is missing: {proposal.position_external_key}")
        organization_unit_key = (
            proposal.organization_unit_external_key
            or proposal.department_external_key
            or (
                proposal.branch_external_key
                if proposal.branch_external_key != LEGACY_ROOT_EXTERNAL_KEY
                else None
            )
        )
        organization_unit = (
            resolved_units.get(organization_unit_key) or units_by_external.get(organization_unit_key)
            if organization_unit_key
            else None
        )
        if organization_unit_key and organization_unit is None:
            raise ImportCommitConflictError(
                f"approved staff organization unit is missing: {organization_unit_key}"
            )
        user = users_by_personnel.get(normalize_unit_name(proposal.personnel_number))
        if user is None and proposal.email:
            email_result = await db.execute(
                select(User).where(
                    User.tenant_id == tenant_id,
                    func.lower(func.btrim(User.email)) == proposal.email.strip().casefold(),
                )
            )
            user = email_result.scalar_one_or_none()
        if user is None:
            user = User(
                id=uuid4(),
                tenant_id=tenant_id,
                personnel_number=proposal.personnel_number,
                email=proposal.email,
                phone=proposal.phone,
                first_name=proposal.first_name,
                last_name=proposal.last_name,
                role="student",
                is_active=True,
                position_id=position.id,
                organization_unit_id=organization_unit.id if organization_unit is not None else None,
                password_hash=None,
                status="active",
            )
            db.add(user)
            users_by_personnel[normalize_unit_name(proposal.personnel_number)] = user
            counts["staff_created"] += 1
            affected_user_ids.add(user.id)
        else:
            changed = (
                user.first_name != proposal.first_name
                or user.last_name != proposal.last_name
                or user.position_id != position.id
                or (
                    organization_unit is not None
                    and user.organization_unit_id != organization_unit.id
                )
                or (proposal.email is not None and user.email != proposal.email)
                or (proposal.phone is not None and user.phone != proposal.phone)
            )
            user.first_name = proposal.first_name
            user.last_name = proposal.last_name
            user.position_id = position.id
            if organization_unit is not None:
                user.organization_unit_id = organization_unit.id
            user.is_active = True
            if proposal.email is not None:
                user.email = proposal.email
            if proposal.phone is not None:
                user.phone = proposal.phone
            if changed:
                counts["staff_updated"] += 1
                affected_user_ids.add(user.id)
            else:
                counts["unchanged"] += 1
        await db.flush()

    committed = apply_transition(
        record_to_domain(record),
        ImportSessionState.COMMITTED,
        now=timestamp,
    )
    record.state = committed.state.value
    record.committed_at = timestamp
    record.result_summary = {
        **counts,
        "rules_recompute_required": counts["staff_created"] + counts["staff_updated"],
        "rules_recompute_state": "pending" if affected_user_ids else "not_required",
        "affected_user_ids": [str(user_id) for user_id in sorted(affected_user_ids, key=str)],
        "deleted": 0,
    }
    db.add(
        StaffImportSessionEvent(
            tenant_id=tenant_id,
            session_id=record.id,
            actor_id=actor_id,
            from_state=ImportSessionState.COMMITTING.value,
            to_state=ImportSessionState.COMMITTED.value,
            event_type="commit_completed",
            event_metadata={"revision": revision, "summary": record.result_summary},
        )
    )
    await db.flush()
    return record


async def run_committed_rule_recompute(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    session_id: UUID,
    actor_id: UUID,
) -> StaffImportSession:
    """Materialize training rules after the structure transaction committed.

    This retryable second phase never rolls back the already committed staff
    import. Re-running it is safe because the assignment kernel is idempotent.
    """

    record = await get_import_session(
        db,
        tenant_id=tenant_id,
        session_id=session_id,
        for_update=True,
    )
    if record.state != ImportSessionState.COMMITTED.value:
        raise ImportCommitConflictError("rules can run only after import commit")
    summary = dict(record.result_summary or {})
    if summary.get("rules_recompute_state") in {"success", "not_required"}:
        return record
    user_ids = [UUID(value) for value in summary.get("affected_user_ids", [])]
    if not user_ids:
        summary["rules_recompute_state"] = "not_required"
        record.result_summary = summary
        await db.flush()
        return record
    outcome = await apply_rules_for_users(db, user_ids)
    summary.update(
        {
            "rules_recompute_state": "success",
            "rules_added": outcome.added,
            "rules_removed": outcome.removed,
            "rules_updated": outcome.updated,
        }
    )
    record.result_summary = summary
    db.add(
        StaffImportSessionEvent(
            tenant_id=tenant_id,
            session_id=record.id,
            actor_id=actor_id,
            from_state=record.state,
            to_state=record.state,
            event_type="rules_recomputed",
            event_metadata={
                "users": len(user_ids),
                "added": outcome.added,
                "removed": outcome.removed,
                "updated": outcome.updated,
            },
        )
    )
    await db.flush()
    return record


async def mark_rule_recompute_failed(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    session_id: UUID,
    actor_id: UUID,
    error_code: str,
) -> StaffImportSession:
    record = await get_import_session(
        db,
        tenant_id=tenant_id,
        session_id=session_id,
        for_update=True,
    )
    summary = dict(record.result_summary or {})
    summary["rules_recompute_state"] = "failed"
    summary["rules_recompute_error"] = error_code
    record.result_summary = summary
    db.add(
        StaffImportSessionEvent(
            tenant_id=tenant_id,
            session_id=record.id,
            actor_id=actor_id,
            from_state=record.state,
            to_state=record.state,
            event_type="rules_recompute_failed",
            event_metadata={"error_code": error_code},
        )
    )
    await db.flush()
    return record
