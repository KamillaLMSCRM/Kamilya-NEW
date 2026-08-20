"""Deterministic, mutation-free matching for adaptive staff imports.

The module deliberately accepts snapshots rather than ORM objects.  An API or
repository adapter can construct these snapshots under its tenant context and
then hand the resulting diff to the review/commit workflow.

Identity rules are intentionally conservative:

* branches and departments: external key first, then
  ``(parent, type, normalized name)``;
* positions: ``(organization unit, normalized name)``;
* staff: personnel number first, then a unique email;
* staff names are display fields only and are never an identity key.

The result is additive: the diff contains incoming records only.  Missing
existing records are never represented as deletes or archive operations.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.modules.organization_units.domain import OrganizationUnitType
from app.modules.staff_import_sessions.schemas import (
    EvidenceItem,
    MatchAction,
    ProposalConfidence,
    SourceCellRef,
)

# Re-export the session contract's action enum so adapters do not need a
# conversion layer between review proposals and this pure diff seam.
ImportDiffAction = MatchAction


class ImportEntityType(StrEnum):
    """Snapshot kind represented by a diff entry."""

    BRANCH = "branch"
    DEPARTMENT = "department"
    POSITION = "position"
    STAFF = "staff"


@dataclass(frozen=True, slots=True)
class IncomingOrganizationUnit:
    """One normalized source branch or department candidate."""

    tenant_id: UUID
    name: str
    unit_type: OrganizationUnitType
    external_key: str | None = None
    parent_external_key: str | None = None
    parent_name: str | None = None
    parent_type: OrganizationUnitType | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    source_refs: tuple[SourceCellRef, ...] = ()


@dataclass(frozen=True, slots=True)
class ExistingOrganizationUnit:
    """Tenant-owned branch or department read from the current database."""

    tenant_id: UUID
    record_id: str
    name: str
    unit_type: OrganizationUnitType
    external_key: str | None = None
    parent_external_key: str | None = None
    parent_name: str | None = None
    parent_type: OrganizationUnitType | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IncomingPosition:
    """Position source row.  ``org_unit_external_key`` may be a branch key."""

    tenant_id: UUID
    name: str
    org_unit_external_key: str
    external_key: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    source_refs: tuple[SourceCellRef, ...] = ()


@dataclass(frozen=True, slots=True)
class ExistingPosition:
    """Position read from the current database."""

    tenant_id: UUID
    record_id: str
    name: str
    org_unit_external_key: str
    external_key: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IncomingStaff:
    """Staff source row with identity and assignment fields."""

    tenant_id: UUID
    first_name: str
    last_name: str
    personnel_number: str | None = None
    email: str | None = None
    position_external_key: str | None = None
    org_unit_external_key: str | None = None
    external_key: str | None = None
    phone: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    source_refs: tuple[SourceCellRef, ...] = ()


@dataclass(frozen=True, slots=True)
class ExistingStaff:
    """Staff identity snapshot read from the current database."""

    tenant_id: UUID
    record_id: str
    first_name: str
    last_name: str
    personnel_number: str | None = None
    email: str | None = None
    position_external_key: str | None = None
    org_unit_external_key: str | None = None
    phone: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ImportDiffEntry:
    """Reviewable diff entry with source traceability and conflict details."""

    entity_type: ImportEntityType
    action: ImportDiffAction
    incoming_key: str
    existing_id: str | None
    source_refs: tuple[SourceCellRef, ...] = ()
    evidence: tuple[EvidenceItem, ...] = ()
    changed_fields: tuple[str, ...] = ()
    blocking: bool = False
    conflict_code: str | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class ImportDiffResult:
    """Additive import diff.  No entry represents deletion or archival."""

    entries: tuple[ImportDiffEntry, ...] = ()

    @property
    def conflicts(self) -> tuple[ImportDiffEntry, ...]:
        return tuple(entry for entry in self.entries if entry.action is ImportDiffAction.CONFLICT)

    @property
    def has_blocking_conflicts(self) -> bool:
        return any(entry.blocking for entry in self.entries)

    def by_action(self, action: ImportDiffAction) -> tuple[ImportDiffEntry, ...]:
        return tuple(entry for entry in self.entries if entry.action is action)


_SPACE_RE = re.compile(r"\s+")


def normalize_import_key(value: object | None) -> str:
    """Normalize a human or external key without altering the displayed value."""

    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", str(value)).strip()
    return _SPACE_RE.sub(" ", normalized).casefold()


def _nonempty(value: object | None) -> str | None:
    normalized = normalize_import_key(value)
    return normalized or None


def _source_refs(value: object) -> tuple[SourceCellRef, ...]:
    refs = getattr(value, "source_refs", ())
    return tuple(refs)


def _evidence(code: str, claim: str, *, confidence: str = "high", reason: str = "") -> EvidenceItem:
    return EvidenceItem(
        evidence_code=code,
        claim=claim,
        confidence=ProposalConfidence(confidence),
        reason=reason,
    )


def _index_by(values: Iterable[Any], key_fn) -> dict[str, list[Any]]:
    indexed: dict[str, list[Any]] = defaultdict(list)
    for value in values:
        key = key_fn(value)
        if key:
            indexed[key].append(value)
    return indexed


def _parent_key(value: IncomingOrganizationUnit | ExistingOrganizationUnit) -> str:
    # The normalized fallback is intentionally human-parent based.  External
    # keys are attempted first by ``_organization_entry``; using them here
    # would make a source-key rotation look like a new department.
    return _nonempty(value.parent_name) or _nonempty(value.parent_external_key) or ""


def _unit_norm_key(value: IncomingOrganizationUnit | ExistingOrganizationUnit) -> tuple[str, str, str, str]:
    parent_type = value.parent_type.value if value.parent_type is not None else ""
    return (
        _parent_key(value),
        parent_type,
        value.unit_type.value,
        normalize_import_key(value.name),
    )


def _parent_same(
    incoming: IncomingOrganizationUnit,
    existing: ExistingOrganizationUnit,
) -> bool:
    incoming_parent = _parent_key(incoming)
    existing_parent = _parent_key(existing)
    if incoming_parent or existing_parent:
        return incoming_parent == existing_parent
    return True


def _mapping_changes(incoming: Mapping[str, Any], existing: Mapping[str, Any]) -> tuple[str, ...]:
    # Missing optional metadata in an additive workbook is not a deletion.
    keys = sorted(incoming)
    return tuple(key for key in keys if incoming.get(key) != existing.get(key))


def _organization_entry(
    incoming: IncomingOrganizationUnit,
    existing: Sequence[ExistingOrganizationUnit],
    tenant_id: UUID,
) -> ImportDiffEntry:
    entity_type = ImportEntityType(incoming.unit_type.value)
    incoming_key = _nonempty(incoming.external_key) or _unit_norm_key(incoming)[-1]
    refs = _source_refs(incoming)
    if incoming.tenant_id != tenant_id:
        return _conflict(
            entity_type, incoming_key, refs, "cross_tenant_input", "Incoming record belongs to another tenant."
        )

    same_key = (
        [item for item in existing if _nonempty(item.external_key) == _nonempty(incoming.external_key)]
        if _nonempty(incoming.external_key)
        else []
    )
    if len(same_key) > 1:
        return _conflict(
            entity_type,
            incoming_key,
            refs,
            "duplicate_external_key",
            "External key identifies multiple existing records.",
        )
    if same_key:
        match = same_key[0]
        if match.tenant_id != tenant_id:
            return _conflict(
                entity_type,
                incoming_key,
                refs,
                "cross_tenant_match",
                "External key resolves outside the import tenant.",
            )
        if match.unit_type is not incoming.unit_type:
            return _conflict(
                entity_type,
                incoming_key,
                refs,
                "external_key_type_mismatch",
                "External key changes organization-unit type.",
            )
        return _matched_organization_entry(incoming, match, entity_type, incoming_key, refs, "external_key")

    norm_matches = [
        item for item in existing if item.tenant_id == tenant_id and _unit_norm_key(item) == _unit_norm_key(incoming)
    ]
    if len(norm_matches) > 1:
        return _conflict(
            entity_type,
            incoming_key,
            refs,
            "ambiguous_normalized_match",
            "Normalized parent/type/name match is ambiguous.",
        )
    if norm_matches:
        match = norm_matches[0]
        changes = _mapping_changes(incoming.metadata, match.metadata)
        if _nonempty(incoming.external_key) != _nonempty(match.external_key):
            changes = (*changes, "external_key")
        return ImportDiffEntry(
            entity_type=entity_type,
            action=ImportDiffAction.UPDATE if changes else ImportDiffAction.UNCHANGED,
            incoming_key=incoming_key,
            existing_id=match.record_id,
            source_refs=refs,
            evidence=(
                _evidence("normalized_identity", "Matched by normalized parent, type, and name.", confidence="medium"),
            ),
            changed_fields=tuple(sorted(set(changes))),
        )
    return ImportDiffEntry(
        entity_type=entity_type,
        action=ImportDiffAction.CREATE,
        incoming_key=incoming_key,
        existing_id=None,
        source_refs=refs,
        evidence=(
            _evidence("no_existing_identity", "No existing branch or department matched the approved identity rules."),
        ),
    )


def _matched_organization_entry(
    incoming: IncomingOrganizationUnit,
    match: ExistingOrganizationUnit,
    entity_type: ImportEntityType,
    incoming_key: str,
    refs: tuple[SourceCellRef, ...],
    matched_by: str,
) -> ImportDiffEntry:
    parent_changed = not _parent_same(incoming, match)
    name_changed = normalize_import_key(incoming.name) != normalize_import_key(match.name)
    metadata_changes = _mapping_changes(incoming.metadata, match.metadata)
    changed_fields = list(metadata_changes)
    if parent_changed:
        changed_fields.append("parent")
    if name_changed:
        changed_fields.append("name")
    if parent_changed:
        action = ImportDiffAction.MOVE
    elif name_changed:
        action = ImportDiffAction.RENAME
    elif changed_fields:
        action = ImportDiffAction.UPDATE
    else:
        action = ImportDiffAction.UNCHANGED
    return ImportDiffEntry(
        entity_type=entity_type,
        action=action,
        incoming_key=incoming_key,
        existing_id=match.record_id,
        source_refs=refs,
        evidence=(_evidence(f"matched_{matched_by}", f"Matched existing {entity_type.value} by {matched_by}."),),
        changed_fields=tuple(dict.fromkeys(changed_fields)),
    )


def _conflict(
    entity_type: ImportEntityType,
    incoming_key: str,
    refs: tuple[SourceCellRef, ...],
    code: str,
    message: str,
) -> ImportDiffEntry:
    return ImportDiffEntry(
        entity_type=entity_type,
        action=ImportDiffAction.CONFLICT,
        incoming_key=incoming_key,
        existing_id=None,
        source_refs=refs,
        evidence=(_evidence(code, message, confidence="low", reason="Review required before approval."),),
        blocking=True,
        conflict_code=code,
        message=message,
    )


def _position_entry(
    incoming: IncomingPosition,
    existing: Sequence[ExistingPosition],
    tenant_id: UUID,
) -> ImportDiffEntry:
    incoming_key = (
        _nonempty(incoming.external_key)
        or f"{normalize_import_key(incoming.org_unit_external_key)}:{normalize_import_key(incoming.name)}"
    )
    refs = _source_refs(incoming)
    if incoming.tenant_id != tenant_id:
        return _conflict(
            ImportEntityType.POSITION,
            incoming_key,
            refs,
            "cross_tenant_input",
            "Incoming record belongs to another tenant.",
        )
    org_key = normalize_import_key(incoming.org_unit_external_key)
    if not org_key:
        return _conflict(
            ImportEntityType.POSITION,
            incoming_key,
            refs,
            "missing_org_unit",
            "Position must reference a branch or department.",
        )
    external_key = _nonempty(incoming.external_key)
    if external_key:
        key_matches = [item for item in existing if _nonempty(item.external_key) == external_key]
        if len(key_matches) > 1:
            return _conflict(
                ImportEntityType.POSITION,
                incoming_key,
                refs,
                "duplicate_position_external_key",
                "Position external key identifies multiple records.",
            )
        if key_matches:
            match = key_matches[0]
            if match.tenant_id != tenant_id:
                return _conflict(
                    ImportEntityType.POSITION,
                    incoming_key,
                    refs,
                    "cross_tenant_match",
                    "Position external key resolves outside the import tenant.",
                )
            org_changed = normalize_import_key(match.org_unit_external_key) != org_key
            name_changed = normalize_import_key(match.name) != normalize_import_key(incoming.name)
            changes = list(_mapping_changes(incoming.metadata, match.metadata))
            if org_changed:
                changes.append("org_unit")
            if name_changed:
                changes.append("name")
            if org_changed:
                action = ImportDiffAction.MOVE
            elif name_changed:
                action = ImportDiffAction.RENAME
            elif changes:
                action = ImportDiffAction.UPDATE
            else:
                action = ImportDiffAction.UNCHANGED
            return ImportDiffEntry(
                entity_type=ImportEntityType.POSITION,
                action=action,
                incoming_key=incoming_key,
                existing_id=match.record_id,
                source_refs=refs,
                evidence=(
                    _evidence(
                        "matched_external_key",
                        "Matched existing position by external key.",
                    ),
                ),
                changed_fields=tuple(changes),
            )
    matches = [
        item
        for item in existing
        if item.tenant_id == tenant_id
        and normalize_import_key(item.org_unit_external_key) == org_key
        and normalize_import_key(item.name) == normalize_import_key(incoming.name)
    ]
    if len(matches) > 1:
        return _conflict(
            ImportEntityType.POSITION,
            incoming_key,
            refs,
            "ambiguous_position_identity",
            "Organization unit and position name identify multiple records.",
        )
    if not matches:
        return ImportDiffEntry(
            entity_type=ImportEntityType.POSITION,
            action=ImportDiffAction.CREATE,
            incoming_key=incoming_key,
            existing_id=None,
            source_refs=refs,
            evidence=(
                _evidence("no_existing_identity", "No position matched by organization unit and normalized name."),
            ),
        )
    match = matches[0]
    changes = _mapping_changes(incoming.metadata, match.metadata)
    return ImportDiffEntry(
        entity_type=ImportEntityType.POSITION,
        action=ImportDiffAction.UPDATE if changes else ImportDiffAction.UNCHANGED,
        incoming_key=incoming_key,
        existing_id=match.record_id,
        source_refs=refs,
        evidence=(
            _evidence("position_composite_identity", "Matched by organization unit and normalized position name."),
        ),
        changed_fields=changes,
    )


def _staff_entry(
    incoming: IncomingStaff,
    existing: Sequence[ExistingStaff],
    tenant_id: UUID,
) -> ImportDiffEntry:
    incoming_key = (
        _nonempty(incoming.external_key) or _nonempty(incoming.personnel_number) or _nonempty(incoming.email) or "staff"
    )
    refs = _source_refs(incoming)
    if incoming.tenant_id != tenant_id:
        return _conflict(
            ImportEntityType.STAFF,
            incoming_key,
            refs,
            "cross_tenant_input",
            "Incoming record belongs to another tenant.",
        )
    personnel_key = _nonempty(incoming.personnel_number)
    email_key = _nonempty(incoming.email)
    pn_matches = (
        [item for item in existing if item.tenant_id == tenant_id and _nonempty(item.personnel_number) == personnel_key]
        if personnel_key
        else []
    )
    email_matches = (
        [item for item in existing if item.tenant_id == tenant_id and _nonempty(item.email) == email_key]
        if email_key
        else []
    )
    if len(pn_matches) > 1:
        return _conflict(
            ImportEntityType.STAFF,
            incoming_key,
            refs,
            "ambiguous_personnel_number",
            "Personnel number identifies multiple staff records.",
        )
    if len(email_matches) > 1:
        return _conflict(
            ImportEntityType.STAFF, incoming_key, refs, "ambiguous_email", "Email identifies multiple staff records."
        )
    if pn_matches and email_matches and pn_matches[0].record_id != email_matches[0].record_id:
        return _conflict(
            ImportEntityType.STAFF,
            incoming_key,
            refs,
            "identity_key_disagreement",
            "Personnel number and email resolve to different staff records.",
        )
    if personnel_key and not pn_matches and email_matches:
        matched_personnel = _nonempty(email_matches[0].personnel_number)
        if matched_personnel and matched_personnel != personnel_key:
            return _conflict(
                ImportEntityType.STAFF,
                incoming_key,
                refs,
                "personnel_number_email_conflict",
                "Email belongs to a staff record with another personnel number.",
            )
    matches = pn_matches or email_matches
    if not matches:
        if not personnel_key and not email_key:
            return _conflict(
                ImportEntityType.STAFF,
                incoming_key,
                refs,
                "missing_staff_identity",
                "Staff cannot be matched or created without personnel number or email.",
            )
        return ImportDiffEntry(
            entity_type=ImportEntityType.STAFF,
            action=ImportDiffAction.CREATE,
            incoming_key=incoming_key,
            existing_id=None,
            source_refs=refs,
            evidence=(
                _evidence("new_staff_identity", "No existing staff matched by personnel number or unique email."),
            ),
        )
    match = matches[0]
    changed_fields: list[str] = []
    for field_name in ("first_name", "last_name"):
        incoming_value = _nonempty(getattr(incoming, field_name))
        existing_value = _nonempty(getattr(match, field_name))
        if incoming_value != existing_value:
            changed_fields.append(field_name)
    for field_name in (
        "personnel_number",
        "email",
        "phone",
        "position_external_key",
        "org_unit_external_key",
    ):
        incoming_value = _nonempty(getattr(incoming, field_name))
        if not incoming_value:
            continue
        existing_value = _nonempty(getattr(match, field_name))
        if incoming_value != existing_value:
            changed_fields.append(field_name)
    changed_fields.extend(_mapping_changes(incoming.metadata, match.metadata))
    if "position_external_key" in changed_fields or "org_unit_external_key" in changed_fields:
        action = ImportDiffAction.MOVE
    elif "first_name" in changed_fields or "last_name" in changed_fields:
        action = ImportDiffAction.RENAME
    elif changed_fields:
        action = ImportDiffAction.UPDATE
    else:
        action = ImportDiffAction.UNCHANGED
    evidence_code = "personnel_number" if pn_matches else "unique_email"
    return ImportDiffEntry(
        entity_type=ImportEntityType.STAFF,
        action=action,
        incoming_key=incoming_key,
        existing_id=match.record_id,
        source_refs=refs,
        evidence=(_evidence(f"matched_{evidence_code}", f"Matched staff by {evidence_code}."),),
        changed_fields=tuple(changed_fields),
    )


def _validate_duplicates(values: Sequence[Any], key_fn) -> set[str]:
    """Return source-object identities that belong to duplicate groups."""

    result: set[str] = set()
    groups = _index_by(values, key_fn)
    for _key, group in groups.items():
        if len(group) > 1:
            result.update(str(id(item)) for item in group)
    return result


def _validate_staff_duplicates(values: Sequence[IncomingStaff]) -> set[str]:
    """Mark rows duplicated by either personnel number or email."""

    duplicate_ids: set[str] = set()
    for key_fn in (
        lambda item: _nonempty(item.personnel_number),
        lambda item: _nonempty(item.email),
    ):
        duplicate_ids.update(_validate_duplicates(values, key_fn))
    return duplicate_ids


def build_import_diff(
    *,
    tenant_id: UUID,
    existing_units: Sequence[ExistingOrganizationUnit] = (),
    incoming_units: Sequence[IncomingOrganizationUnit] = (),
    existing_positions: Sequence[ExistingPosition] = (),
    incoming_positions: Sequence[IncomingPosition] = (),
    existing_staff: Sequence[ExistingStaff] = (),
    incoming_staff: Sequence[IncomingStaff] = (),
) -> ImportDiffResult:
    """Build an additive, deterministic diff without mutating any input.

    The caller owns tenant-scoped reads and later persistence.  This function
    does not perform database lookups, deletes, archives, or commits.
    """

    entries: list[ImportDiffEntry] = []
    duplicate_unit_keys = _validate_duplicates(
        incoming_units,
        lambda item: _nonempty(item.external_key) or "|".join(_unit_norm_key(item)),
    )
    for incoming in incoming_units:
        if str(id(incoming)) in duplicate_unit_keys:
            entries.append(
                _conflict(
                    ImportEntityType(incoming.unit_type.value),
                    _nonempty(incoming.external_key) or _unit_norm_key(incoming)[-1],
                    _source_refs(incoming),
                    "duplicate_source_identity",
                    "Multiple incoming rows share the same identity key.",
                )
            )
        else:
            entries.append(_organization_entry(incoming, existing_units, tenant_id))

    duplicate_position_keys = _validate_duplicates(
        incoming_positions,
        lambda item: f"{normalize_import_key(item.org_unit_external_key)}|{normalize_import_key(item.name)}",
    )
    for incoming in incoming_positions:
        if str(id(incoming)) in duplicate_position_keys:
            entries.append(
                _conflict(
                    ImportEntityType.POSITION,
                    _nonempty(incoming.external_key)
                    or f"{normalize_import_key(incoming.org_unit_external_key)}:{normalize_import_key(incoming.name)}",
                    _source_refs(incoming),
                    "duplicate_source_identity",
                    "Multiple incoming rows share the same position identity key.",
                )
            )
        else:
            entries.append(_position_entry(incoming, existing_positions, tenant_id))

    duplicate_staff_keys = _validate_staff_duplicates(incoming_staff)
    for incoming in incoming_staff:
        if str(id(incoming)) in duplicate_staff_keys:
            entries.append(
                _conflict(
                    ImportEntityType.STAFF,
                    _nonempty(incoming.personnel_number) or _nonempty(incoming.email) or "staff",
                    _source_refs(incoming),
                    "duplicate_source_identity",
                    "Multiple incoming rows share the same staff identity key.",
                )
            )
        else:
            entries.append(_staff_entry(incoming, existing_staff, tenant_id))
    return ImportDiffResult(entries=tuple(entries))
