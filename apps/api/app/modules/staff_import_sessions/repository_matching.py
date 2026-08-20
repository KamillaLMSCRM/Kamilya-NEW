"""Tenant-scoped ORM adapter for the pure staff import matcher."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department
from app.models.users import User
from app.modules.organization_units.domain import OrganizationUnitType
from app.modules.positions.models import Position
from app.modules.staff_import_legacy_adapter import LEGACY_ROOT_EXTERNAL_KEY
from app.modules.staff_import_matching import (
    ExistingOrganizationUnit,
    ExistingPosition,
    ExistingStaff,
    ImportEntityType,
    IncomingOrganizationUnit,
    IncomingPosition,
    IncomingStaff,
    build_import_diff,
    normalize_import_key,
)

from .schemas import ImportSessionConflict, ImportSessionProposal


def _unit_candidate_key(
    *,
    name: str,
    unit_type: OrganizationUnitType,
    proposal: ImportSessionProposal,
) -> str | None:
    candidates = proposal.branches if unit_type is OrganizationUnitType.BRANCH else proposal.departments
    matched = [
        item.external_key
        for item in candidates
        if normalize_import_key(item.branch_name if unit_type is OrganizationUnitType.BRANCH else item.department_name)
        == normalize_import_key(name)
    ]
    return matched[0] if len(matched) == 1 else None


async def reconcile_proposal_with_database(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    proposal: ImportSessionProposal,
) -> ImportSessionProposal:
    unit_rows = list(
        (
            await db.execute(
                select(Department).where(
                    Department.tenant_id == tenant_id,
                    Department.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    units_by_id = {unit.id: unit for unit in unit_rows}
    existing_unit_keys: dict[UUID, str] = {}
    unit_types: dict[UUID, OrganizationUnitType] = {}
    for unit in unit_rows:
        unit_type = OrganizationUnitType(unit.unit_type)
        if unit.legacy_root and any(
            normalize_import_key(item.branch_name) == normalize_import_key(unit.name) for item in proposal.branches
        ):
            # This is still only a preview classification. The commit keeps
            # the same row ID and changes its type only after approval.
            unit_type = OrganizationUnitType.BRANCH
        candidate_key = unit.external_key or _unit_candidate_key(
            name=unit.name,
            unit_type=unit_type,
            proposal=proposal,
        )
        if candidate_key:
            existing_unit_keys[unit.id] = candidate_key
        unit_types[unit.id] = unit_type

    existing_units: list[ExistingOrganizationUnit] = []
    for unit in unit_rows:
        unit_type = unit_types[unit.id]
        parent = units_by_id.get(unit.parent_id)
        existing_units.append(
            ExistingOrganizationUnit(
                tenant_id=unit.tenant_id,
                record_id=str(unit.id),
                name=unit.name,
                unit_type=unit_type,
                external_key=unit.external_key,
                parent_external_key=(existing_unit_keys.get(parent.id) if parent else None),
                parent_name=(parent.name if parent else None),
                parent_type=(unit_types.get(parent.id) if parent else None),
                metadata=unit.source_metadata or {},
            )
        )

    incoming_units = [
        IncomingOrganizationUnit(
            tenant_id=tenant_id,
            name=item.branch_name,
            unit_type=OrganizationUnitType.BRANCH,
            external_key=item.external_key,
            source_refs=tuple(item.source_refs),
        )
        for item in proposal.branches
    ]
    incoming_units.extend(
        IncomingOrganizationUnit(
            tenant_id=tenant_id,
            name=item.department_name,
            unit_type=OrganizationUnitType.DEPARTMENT,
            external_key=item.external_key,
            parent_external_key=(
                None if item.branch_external_key == LEGACY_ROOT_EXTERNAL_KEY else item.branch_external_key
            ),
            parent_name=None,
            parent_type=(None if item.branch_external_key == LEGACY_ROOT_EXTERNAL_KEY else OrganizationUnitType.BRANCH),
            source_refs=tuple(item.source_refs),
        )
        for item in proposal.departments
    )

    position_rows = list((await db.execute(select(Position).where(Position.tenant_id == tenant_id))).scalars().all())
    incoming_position_by_identity = {
        (
            item.department_external_key or item.branch_external_key,
            normalize_import_key(item.position_name),
        ): item.external_key
        for item in proposal.positions
    }
    existing_position_keys: dict[UUID, str] = {}
    existing_positions: list[ExistingPosition] = []
    for position in position_rows:
        unit_key = existing_unit_keys.get(position.department_id, "")
        candidate_key = position.external_key or incoming_position_by_identity.get(
            (unit_key, normalize_import_key(position.name))
        )
        if candidate_key:
            existing_position_keys[position.id] = candidate_key
        existing_positions.append(
            ExistingPosition(
                tenant_id=position.tenant_id,
                record_id=str(position.id),
                name=position.name,
                org_unit_external_key=unit_key,
                external_key=position.external_key,
                metadata=position.source_metadata or {},
            )
        )
    incoming_positions = [
        IncomingPosition(
            tenant_id=tenant_id,
            name=item.position_name,
            org_unit_external_key=item.department_external_key or item.branch_external_key,
            external_key=item.external_key,
            source_refs=tuple(item.source_refs),
        )
        for item in proposal.positions
    ]

    staff_rows = list((await db.execute(select(User).where(User.tenant_id == tenant_id))).scalars().all())
    existing_staff = [
        ExistingStaff(
            tenant_id=user.tenant_id,
            record_id=str(user.id),
            first_name=user.first_name,
            last_name=user.last_name,
            personnel_number=user.personnel_number,
            email=user.email,
            position_external_key=existing_position_keys.get(user.position_id),
            org_unit_external_key=(
                existing_unit_keys.get(
                    next(
                        (position.department_id for position in position_rows if position.id == user.position_id),
                        None,
                    )
                )
            ),
            phone=user.phone,
        )
        for user in staff_rows
    ]
    incoming_staff = [
        IncomingStaff(
            tenant_id=tenant_id,
            first_name=item.first_name,
            last_name=item.last_name,
            personnel_number=item.personnel_number,
            email=item.email,
            position_external_key=item.position_external_key,
            org_unit_external_key=item.department_external_key or item.branch_external_key,
            external_key=item.external_key,
            phone=item.phone,
            source_refs=tuple(item.source_refs),
        )
        for item in proposal.staff
    ]
    diff = build_import_diff(
        tenant_id=tenant_id,
        existing_units=existing_units,
        incoming_units=incoming_units,
        existing_positions=existing_positions,
        incoming_positions=incoming_positions,
        existing_staff=existing_staff,
        incoming_staff=incoming_staff,
    )
    action_by_key = {
        (entry.entity_type.value, normalize_import_key(entry.incoming_key)): entry for entry in diff.entries
    }

    def apply_action(item, entity_type: ImportEntityType, incoming_key: str | None = None):
        key = incoming_key if incoming_key is not None else item.external_key
        entry = action_by_key.get((entity_type.value, normalize_import_key(key)))
        if entry is None:
            return item
        return item.model_copy(
            update={
                "action": entry.action,
                "evidence": [*item.evidence, *entry.evidence],
            }
        )

    conflicts = [
        ImportSessionConflict(
            conflict_code=entry.conflict_code or "matching_conflict",
            scope=entry.entity_type.value,
            message=entry.message or "Неоднозначное сопоставление.",
            blocking=entry.blocking,
            proposal_ids=[entry.incoming_key],
            source_refs=list(entry.source_refs),
        )
        for entry in diff.conflicts
    ]
    return proposal.model_copy(
        update={
            "branches": [apply_action(item, ImportEntityType.BRANCH) for item in proposal.branches],
            "departments": [apply_action(item, ImportEntityType.DEPARTMENT) for item in proposal.departments],
            "positions": [apply_action(item, ImportEntityType.POSITION) for item in proposal.positions],
            "staff": [apply_action(item, ImportEntityType.STAFF, item.personnel_number) for item in proposal.staff],
            "conflicts": [*proposal.conflicts, *conflicts],
        }
    )
