"""Atomic application of one approved staff import proposal."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
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
                and normalize_unit_name(cast(str, unit.name)) == normalized_name
                and getattr(unit.unit_type, "value", unit.unit_type) == proposal.unit_type.value
            ]
            if len(candidates) > 1:
                raise ImportCommitConflictError(f"ambiguous organization unit {proposal.name}")
            existing = candidates[0] if candidates else None
        plan.append(GenericUnitCommitPlanItem(proposal=proposal, existing=existing))
        if existing is not None:
            resolved_existing_by_key[key] = existing

    active_items = [item for item in plan if _active_action(item.proposal.action)]
    incoming_head_offices = [item for item in active_items if item.proposal.is_head_office]
    existing_head_office_ids = {
        unit.id
        for unit in existing_units
        if getattr(unit, "is_head_office", False) and getattr(unit, "is_active", True)
    }
    matched_head_office_ids = {item.existing.id for item in incoming_head_offices if item.existing is not None}
    if existing_head_office_ids - matched_head_office_ids and incoming_head_offices:
        raise ImportCommitConflictError("tenant already has an active head office")

    # Validate the final graph, not only the incoming fragment.  An imported
    # node may be attached to an existing depth-eight parent or an existing
    # descendant; both must fail before the session changes state or writes.
    identity_by_key: dict[str, object] = {key: unit.id for key, unit in existing_by_external.items()}
    identity_by_item: dict[int, object] = {}
    for item in active_items:
        key = normalize_import_key(item.proposal.external_key)
        identity = item.existing.id if item.existing is not None else ("incoming", key)
        identity_by_key[key] = identity
        identity_by_item[id(item)] = identity

    parent_by_identity: dict[object, object | None] = {unit.id: unit.parent_id for unit in existing_units}
    for item in active_items:
        parent_key = normalize_import_key(item.proposal.parent_external_key)
        parent_identity = identity_by_key.get(parent_key) if parent_key else None
        if parent_key and parent_identity is None:
            raise ImportCommitConflictError(
                f"approved organization unit parent is missing: {item.proposal.parent_external_key}"
            )
        parent_by_identity[identity_by_item[id(item)]] = parent_identity

    depths: dict[object, int] = {}
    visiting: set[object] = set()

    def final_depth(identity: object) -> int:
        if identity in depths:
            return depths[identity]
        if identity in visiting:
            raise ImportCommitConflictError("organization unit parent cycle detected")
        visiting.add(identity)
        parent_identity = parent_by_identity.get(identity)
        depth = 0 if parent_identity is None else final_depth(parent_identity) + 1
        visiting.remove(identity)
        if depth > 8:
            raise ImportCommitConflictError("organization unit hierarchy exceeds maximum depth of 8")
        depths[identity] = depth
        return depth

    for item in active_items:
        final_depth(identity_by_item[id(item)])
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
    units_by_external = {
        normalize_import_key(unit.external_key): unit for unit in units if normalize_import_key(unit.external_key)
    }
    resolved_units: dict[str, Department] = {}

    if generic_plan is not None:
        for plan_item in generic_plan:
            unit_proposal = plan_item.proposal
            parent_key = normalize_import_key(unit_proposal.parent_external_key)
            parent = resolved_units.get(parent_key) or units_by_external.get(parent_key)
            if parent_key and parent is None:
                raise ImportCommitConflictError(
                    "approved organization unit parent is missing: " f"{unit_proposal.parent_external_key}"
                )
            unit = plan_item.existing
            if unit is None:
                unit_id = uuid4()
                scope = cast(str, parent.slug) if parent is not None else "root"
                unit = Department(
                    id=unit_id,
                    tenant_id=tenant_id,
                    name=unit_proposal.name,
                    slug=(f"{_slug_part(scope)}--{_slug_part(unit_proposal.name)}--" f"{str(unit_id)[:8]}"),
                    unit_type=unit_proposal.unit_type.value,
                    normalized_name=normalize_unit_name(unit_proposal.name),
                    external_key=unit_proposal.external_key,
                    parent_id=parent.id if parent is not None else None,
                    is_active=True,
                    source_metadata={"origin": "adaptive_import", "session_id": str(record.id)},
                    legacy_root=_is_legacy_compatibility_root(unit_proposal.external_key),
                    is_head_office=unit_proposal.is_head_office,
                    description="",
                )
                db.add(unit)
                units.append(unit)
                counts["organization_units_created"] = counts.get("organization_units_created", 0) + 1
                count_key = f"{unit_proposal.unit_type.value}s_created"
                if count_key in counts:
                    counts[count_key] += 1
            else:
                changed = (
                    unit.name != unit_proposal.name
                    or unit.parent_id != (parent.id if parent is not None else None)
                    or unit.unit_type != unit_proposal.unit_type.value
                    or unit.external_key != unit_proposal.external_key
                    or unit.is_head_office != unit_proposal.is_head_office
                    or unit.legacy_root != _is_legacy_compatibility_root(unit_proposal.external_key)
                )
                writable_unit = cast(Any, unit)
                writable_unit.name = unit_proposal.name
                writable_unit.normalized_name = normalize_unit_name(unit_proposal.name)
                writable_unit.unit_type = unit_proposal.unit_type.value
                writable_unit.parent_id = parent.id if parent is not None else None
                writable_unit.external_key = unit_proposal.external_key
                writable_unit.is_active = True
                writable_unit.is_head_office = unit_proposal.is_head_office
                writable_unit.legacy_root = _is_legacy_compatibility_root(unit_proposal.external_key)
                if changed:
                    counts["organization_units_updated"] = counts.get("organization_units_updated", 0) + 1
                    count_key = f"{unit_proposal.unit_type.value}s_updated"
                    if count_key in counts:
                        counts[count_key] += 1
                else:
                    counts["unchanged"] += 1
            proposal_key = normalize_import_key(unit_proposal.external_key)
            units_by_external[proposal_key] = unit
            resolved_units[proposal_key] = unit
            await db.flush()

    for branch_proposal in () if generic_plan is not None else domain.proposal.branches:
        if not _active_action(branch_proposal.action):
            counts["skipped"] += 1
            continue
        proposal = branch_proposal
        proposal_key = normalize_import_key(proposal.external_key)
        unit = units_by_external.get(proposal_key)
        if unit is None:
            normalized = normalize_unit_name(branch_proposal.branch_name)
            unit = _one_or_none(
                [u for u in units if u.parent_id is None and u.normalized_name == normalized],
                conflict=f"ambiguous branch {branch_proposal.branch_name}",
            )
        if unit is None:
            unit_id = uuid4()
            unit = Department(
                id=unit_id,
                tenant_id=tenant_id,
                name=branch_proposal.branch_name,
                slug=f"branch--{_slug_part(branch_proposal.branch_name)}--{str(unit_id)[:8]}",
                unit_type="branch",
                normalized_name=normalize_unit_name(branch_proposal.branch_name),
                external_key=branch_proposal.external_key,
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
                unit.name != branch_proposal.branch_name
                or unit.unit_type != "branch"
                or unit.external_key != branch_proposal.external_key
                or unit.parent_id is not None
                or unit.legacy_root
            )
            unit.name = branch_proposal.branch_name
            unit.normalized_name = normalize_unit_name(branch_proposal.branch_name)
            unit.unit_type = "branch"
            unit.parent_id = None
            unit.external_key = branch_proposal.external_key
            unit.legacy_root = False
            unit.is_active = True
            if changed:
                counts["branches_updated"] += 1
            else:
                counts["unchanged"] += 1
        units_by_external[proposal_key] = unit
        resolved_units[proposal_key] = unit
        await db.flush()

    for department_proposal in () if generic_plan is not None else domain.proposal.departments:
        if not _active_action(department_proposal.action):
            counts["skipped"] += 1
            continue
        parent = None
        legacy_root = department_proposal.branch_external_key == LEGACY_ROOT_EXTERNAL_KEY
        if not legacy_root:
            parent_key = normalize_import_key(department_proposal.branch_external_key)
            parent = resolved_units.get(parent_key) or units_by_external.get(parent_key)
            if parent is None or parent.unit_type != "branch":
                raise ImportCommitConflictError(
                    "approved department parent is missing: " f"{department_proposal.branch_external_key}"
                )
        proposal_key = normalize_import_key(department_proposal.external_key)
        unit = units_by_external.get(proposal_key)
        if unit is None:
            normalized = normalize_unit_name(department_proposal.department_name)
            unit = _one_or_none(
                [
                    item
                    for item in units
                    if item.parent_id == (parent.id if parent else None)
                    and item.normalized_name == normalized
                    and item.unit_type == "department"
                ],
                conflict=f"ambiguous department {department_proposal.department_name}",
            )
        if unit is None:
            unit_id = uuid4()
            scope = cast(str, parent.slug) if parent else "legacy-root"
            unit = Department(
                id=unit_id,
                tenant_id=tenant_id,
                name=department_proposal.department_name,
                slug=(
                    f"{_slug_part(scope)}--" f"{_slug_part(department_proposal.department_name)}--{str(unit_id)[:8]}"
                ),
                unit_type="department",
                normalized_name=normalize_unit_name(department_proposal.department_name),
                external_key=department_proposal.external_key,
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
                unit.name != department_proposal.department_name
                or unit.parent_id != (parent.id if parent else None)
                or unit.external_key != department_proposal.external_key
            )
            unit.name = department_proposal.department_name
            unit.normalized_name = normalize_unit_name(department_proposal.department_name)
            unit.unit_type = "department"
            unit.parent_id = parent.id if parent else None
            unit.external_key = department_proposal.external_key
            unit.legacy_root = legacy_root
            unit.is_active = True
            if changed:
                counts["departments_updated"] += 1
            else:
                counts["unchanged"] += 1
        units_by_external[proposal_key] = unit
        resolved_units[proposal_key] = unit
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
    for position_proposal in domain.proposal.positions:
        if not _active_action(position_proposal.action):
            counts["skipped"] += 1
            continue
        unit_key = (
            position_proposal.organization_unit_external_key
            or position_proposal.department_external_key
            or position_proposal.branch_external_key
        )
        normalized_unit_key = normalize_import_key(unit_key)
        unit = resolved_units.get(normalized_unit_key) or units_by_external.get(normalized_unit_key)
        if unit is None and unit_key:
            raise ImportCommitConflictError(f"approved position unit is missing: {unit_key}")
        position = positions_by_external.get(position_proposal.external_key)
        if position is None:
            normalized = normalize_unit_name(position_proposal.position_name)
            position = _one_or_none(
                [
                    item
                    for item in positions
                    if item.department_id == (unit.id if unit is not None else None)
                    and item.normalized_name == normalized
                ],
                conflict=f"ambiguous position {position_proposal.position_name}",
            )
        if position is None:
            position = Position(
                id=uuid4(),
                tenant_id=tenant_id,
                name=position_proposal.position_name,
                normalized_name=normalize_unit_name(position_proposal.position_name),
                external_key=position_proposal.external_key,
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
                position.name != position_proposal.position_name
                or position.department_id != (unit.id if unit is not None else None)
                or position.external_key != position_proposal.external_key
            )
            position.name = position_proposal.position_name
            position.normalized_name = normalize_unit_name(position_proposal.position_name)
            position.external_key = position_proposal.external_key
            position.department = unit.name if unit is not None else ""
            position.department_id = unit.id if unit is not None else None
            position.is_active = True
            if changed:
                counts["positions_updated"] += 1
            else:
                counts["unchanged"] += 1
        positions_by_external[position_proposal.external_key] = position
        resolved_positions[position_proposal.external_key] = position
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
    for staff_proposal in domain.proposal.staff:
        if not _active_action(staff_proposal.action):
            counts["skipped"] += 1
            continue
        position = resolved_positions.get(staff_proposal.position_external_key) or positions_by_external.get(
            staff_proposal.position_external_key
        )
        if position is None:
            raise ImportCommitConflictError(
                "approved staff position is missing: " f"{staff_proposal.position_external_key}"
            )
        organization_unit_key = (
            staff_proposal.organization_unit_external_key
            or staff_proposal.department_external_key
            or (
                staff_proposal.branch_external_key
                if staff_proposal.branch_external_key != LEGACY_ROOT_EXTERNAL_KEY
                else None
            )
        )
        normalized_organization_unit_key = normalize_import_key(organization_unit_key)
        organization_unit = (
            resolved_units.get(normalized_organization_unit_key)
            or units_by_external.get(normalized_organization_unit_key)
            if organization_unit_key
            else None
        )
        if organization_unit_key and organization_unit is None:
            raise ImportCommitConflictError(f"approved staff organization unit is missing: {organization_unit_key}")
        user = users_by_personnel.get(normalize_unit_name(staff_proposal.personnel_number))
        if user is None and staff_proposal.email:
            email_result = await db.execute(
                select(User).where(
                    User.tenant_id == tenant_id,
                    func.lower(func.btrim(User.email)) == staff_proposal.email.strip().casefold(),
                )
            )
            user = email_result.scalar_one_or_none()
        if user is None:
            user = User(
                id=uuid4(),
                tenant_id=tenant_id,
                personnel_number=staff_proposal.personnel_number,
                email=staff_proposal.email,
                phone=staff_proposal.phone,
                first_name=staff_proposal.first_name,
                last_name=staff_proposal.last_name,
                role="student",
                is_active=True,
                position_id=position.id,
                organization_unit_id=organization_unit.id if organization_unit is not None else None,
                password_hash=None,
                status="active",
            )
            db.add(user)
            users_by_personnel[normalize_unit_name(staff_proposal.personnel_number)] = user
            counts["staff_created"] += 1
            affected_user_ids.add(user.id)
        else:
            desired_organization_unit_id = organization_unit.id if organization_unit is not None else None
            staff_changed = (
                user.first_name != staff_proposal.first_name
                or user.last_name != staff_proposal.last_name
                or user.position_id != position.id
                or user.organization_unit_id != desired_organization_unit_id
                or (staff_proposal.email is not None and user.email != staff_proposal.email)
                or (staff_proposal.phone is not None and user.phone != staff_proposal.phone)
            )
            writable_user = cast(Any, user)
            writable_user.first_name = staff_proposal.first_name
            writable_user.last_name = staff_proposal.last_name
            writable_user.position_id = position.id
            writable_user.organization_unit_id = desired_organization_unit_id
            writable_user.is_active = True
            if staff_proposal.email is not None:
                writable_user.email = staff_proposal.email
            if staff_proposal.phone is not None:
                writable_user.phone = staff_proposal.phone
            if staff_changed:
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
