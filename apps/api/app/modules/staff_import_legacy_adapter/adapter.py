"""Pure adapter from the old flat staff import to canonical proposals.

The historical format had one free-text ``department`` column and no branch
column.  Labels that explicitly look like ``Филиал ...`` become branches with
direct positions.  Other labels become departments under the explicit
``LEGACY_ROOT_EXTERNAL_KEY`` compatibility root.  No database row is implied
by this sentinel; the commit adapter must preserve existing root-department
compatibility rather than inventing a visible branch.

This module accepts the same attribute shape as ``staff_import_service.ParsedRow``
but intentionally does not import that service.  That keeps the compatibility
seam pure and allows parser/API replacement without a circular dependency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.staff_import_matching import normalize_import_key
from app.modules.staff_import_sessions import (
    BranchProposal,
    CanonicalDepartmentProposal,
    CanonicalPositionProposal,
    CanonicalStaffProposal,
    EvidenceItem,
    ImportMode,
    ImportSessionConflict,
    ImportSessionProposal,
    MatchAction,
    ProposalConfidence,
    SourceCellRef,
)

LEGACY_ROOT_EXTERNAL_KEY = "legacy:root"
_BRANCH_EXTERNAL_PREFIX = "legacy:branch:"
_DEPARTMENT_EXTERNAL_PREFIX = "legacy:root-department:"
_NESTED_DEPARTMENT_EXTERNAL_PREFIX = "legacy:department:"
_POSITION_EXTERNAL_PREFIX = "legacy:position:"
_STAFF_EXTERNAL_PREFIX = "legacy:staff:"
_BRANCH_LABEL_RE = re.compile(r"^(?:филиал|branch)(?:\s+|$)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class LegacyStaffRow:
    """Minimal row protocol used by the adapter and focused tests."""

    row_number: int
    personnel_number: str
    first_name: str
    last_name: str
    department: str
    position: str
    email: str | None = None
    phone: str | None = None
    branch: str = ""


class LegacyRowLike(Protocol):
    row_number: int
    personnel_number: str
    first_name: str
    last_name: str
    department: str
    position: str
    email: str | None
    phone: str | None
    branch: str


@dataclass(frozen=True, slots=True)
class LegacyColumnMap:
    """Default spreadsheet columns of the historical six-column export."""

    personnel_number: str = "A"
    full_name: str = "B"
    position: str = "C"
    department: str = "D"
    email: str = "E"
    phone: str = "F"
    branch: str = "G"


def _slug(value: str) -> str:
    normalized = normalize_import_key(value)
    safe = "".join(char if char.isalnum() else "-" for char in normalized)
    safe = re.sub(r"-+", "-", safe).strip("-")
    return safe or "unnamed"


def _text(value: object | None) -> str:
    return str(value or "").strip()


def _branch_label(value: str) -> bool:
    return bool(_BRANCH_LABEL_RE.match(_text(value)))


def _ref(sheet: str, row: LegacyRowLike, column: str, value: object | None) -> SourceCellRef:
    # Coordinates provide traceability without duplicating staff PII in the
    # long-lived proposal and append-only event history.
    del value
    return SourceCellRef(sheet=sheet, row=row.row_number, column=column)


def _row_refs(sheet: str, row: LegacyRowLike, columns: LegacyColumnMap) -> tuple[SourceCellRef, ...]:
    refs = [
        _ref(sheet, row, columns.personnel_number, row.personnel_number),
        _ref(sheet, row, columns.full_name, f"{row.first_name} {row.last_name}"),
    ]
    if _text(row.email):
        refs.append(_ref(sheet, row, columns.email, row.email))
    if _text(row.phone):
        refs.append(_ref(sheet, row, columns.phone, row.phone))
    if _text(getattr(row, "branch", "")):
        refs.append(_ref(sheet, row, columns.branch, row.branch))
    return tuple(refs)


def _evidence(
    code: str,
    claim: str,
    *,
    confidence: ProposalConfidence = ProposalConfidence.HIGH,
    reason: str = "",
) -> EvidenceItem:
    return EvidenceItem(evidence_code=code, claim=claim, confidence=confidence, reason=reason)


def _conflict(
    *,
    code: str,
    scope: str,
    message: str,
    refs: list[SourceCellRef],
    proposal_ids: list[str] | None = None,
) -> ImportSessionConflict:
    return ImportSessionConflict(
        conflict_code=code,
        scope=scope,
        message=message,
        blocking=True,
        source_refs=refs,
        proposal_ids=proposal_ids or [],
    )


def _branch_key(label: str) -> str:
    return f"{_BRANCH_EXTERNAL_PREFIX}{_slug(label)}"


def _department_key(label: str) -> str:
    return f"{_DEPARTMENT_EXTERNAL_PREFIX}{_slug(label)}"


def _nested_department_key(branch_key: str, label: str) -> str:
    return f"{_NESTED_DEPARTMENT_EXTERNAL_PREFIX}{_slug(branch_key)}:{_slug(label)}"


def _position_key(parent_key: str, label: str) -> str:
    return f"{_POSITION_EXTERNAL_PREFIX}{_slug(parent_key)}:{_slug(label)}"


def _staff_key(personnel_number: str) -> str:
    return f"{_STAFF_EXTERNAL_PREFIX}{_slug(personnel_number)}"


def adapt_legacy_rows(
    *,
    tenant_id: UUID,
    source_file_name: str,
    source_file_sha256: str,
    rows: list[LegacyRowLike] | tuple[LegacyRowLike, ...],
    sheet_name: str = "Лист1",
    columns: LegacyColumnMap | None = None,
    generated_at: datetime | None = None,
    mode: ImportMode = ImportMode.ADD_OR_UPDATE,
) -> ImportSessionProposal:
    """Convert old flat rows into an additive canonical proposal.

    The adapter has no existing-database input, therefore all emitted records
    start with ``CREATE``.  The matching seam subsequently changes a proposal
    to ``UPDATE``/``UNCHANGED`` using its stable external keys.  Repeated
    adaptation is therefore idempotent at the identity-key level, while
    ``ADD_OR_UPDATE`` guarantees that a partial old file cannot delete rows.
    """

    column_map = columns or LegacyColumnMap()
    requested_mode = ImportMode(mode)
    branch_by_key: dict[str, BranchProposal] = {}
    department_by_key: dict[str, CanonicalDepartmentProposal] = {}
    position_by_key: dict[str, CanonicalPositionProposal] = {}
    staff_by_personnel: dict[str, CanonicalStaffProposal] = {}
    branch_refs: dict[str, list[SourceCellRef]] = {}
    department_refs: dict[str, list[SourceCellRef]] = {}
    position_refs: dict[str, list[SourceCellRef]] = {}
    conflicts: list[ImportSessionConflict] = []
    seen_personnel: dict[str, LegacyRowLike] = {}
    source_rows = tuple(rows)

    for row in source_rows:
        branch_name = _text(getattr(row, "branch", ""))
        department_name = _text(row.department)
        position_name = _text(row.position)
        personnel_number = _text(row.personnel_number)
        refs = list(_row_refs(sheet_name, row, column_map))
        if not department_name and not branch_name:
            conflicts.append(
                _conflict(
                    code="missing_department",
                    scope="legacy_row",
                    message="Legacy row has no department or branch label.",
                    refs=refs,
                )
            )
            continue
        if not position_name:
            conflicts.append(
                _conflict(
                    code="missing_position",
                    scope="legacy_row",
                    message="Legacy row has no position label.",
                    refs=refs,
                )
            )
            continue
        if not personnel_number:
            conflicts.append(
                _conflict(
                    code="missing_personnel_number",
                    scope="legacy_row",
                    message="Legacy row has no personnel number.",
                    refs=refs,
                )
            )
            continue

        if branch_name:
            branch_key = _branch_key(branch_name)
            branch_refs.setdefault(branch_key, []).append(_ref(sheet_name, row, column_map.branch, branch_name))
            if branch_key not in branch_by_key:
                branch_by_key[branch_key] = BranchProposal(
                    branch_id=branch_key,
                    branch_name=branch_name,
                    external_key=branch_key,
                    action=MatchAction.CREATE,
                    confidence=ProposalConfidence.HIGH,
                    source_refs=[],
                    evidence=[
                        _evidence(
                            "explicit_branch_column",
                            "Branch is taken from the dedicated branch column.",
                        )
                    ],
                )
            if department_name:
                department_key = _nested_department_key(branch_key, department_name)
                department_refs.setdefault(department_key, []).append(
                    _ref(sheet_name, row, column_map.department, department_name)
                )
                if department_key not in department_by_key:
                    department_by_key[department_key] = CanonicalDepartmentProposal(
                        department_id=department_key,
                        department_name=department_name,
                        branch_external_key=branch_key,
                        external_key=department_key,
                        action=MatchAction.CREATE,
                        confidence=ProposalConfidence.HIGH,
                        source_refs=[],
                        evidence=[
                            _evidence(
                                "explicit_branch_department",
                                "Department is nested under the dedicated branch column.",
                            )
                        ],
                    )
            else:
                department_key = None
        elif _branch_label(department_name):
            parent_key = _branch_key(department_name)
            branch_refs.setdefault(parent_key, []).append(_ref(sheet_name, row, column_map.department, department_name))
            if parent_key not in branch_by_key:
                branch_by_key[parent_key] = BranchProposal(
                    branch_id=parent_key,
                    branch_name=department_name,
                    external_key=parent_key,
                    action=MatchAction.CREATE,
                    confidence=ProposalConfidence.HIGH,
                    source_refs=[],
                    evidence=[
                        _evidence(
                            "legacy_branch_label",
                            "Flat department value is explicitly labeled as a branch.",
                        )
                    ],
                )
            department_key: str | None = None
            branch_key = parent_key
        else:
            department_key = _department_key(department_name)
            branch_key = LEGACY_ROOT_EXTERNAL_KEY
            department_refs.setdefault(department_key, []).append(
                _ref(sheet_name, row, column_map.department, department_name)
            )
            if department_key not in department_by_key:
                department_by_key[department_key] = CanonicalDepartmentProposal(
                    department_id=department_key,
                    department_name=department_name,
                    branch_external_key=LEGACY_ROOT_EXTERNAL_KEY,
                    external_key=department_key,
                    action=MatchAction.CREATE,
                    confidence=ProposalConfidence.MEDIUM,
                    source_refs=[],
                    evidence=[
                        _evidence(
                            "legacy_root_department",
                            "The old file has no branch column; the department is kept under the explicit compatibility root.",
                            confidence=ProposalConfidence.MEDIUM,
                            reason="Methodologist review is required before applying a new hierarchy mapping.",
                        )
                    ],
                )

        position_key = _position_key(department_key or branch_key, position_name)
        position_refs.setdefault(position_key, []).append(_ref(sheet_name, row, column_map.position, position_name))
        if position_key not in position_by_key:
            position_by_key[position_key] = CanonicalPositionProposal(
                position_id=position_key,
                position_name=position_name,
                branch_external_key=branch_key,
                department_external_key=department_key,
                external_key=position_key,
                action=MatchAction.CREATE,
                confidence=ProposalConfidence.HIGH,
                source_refs=[],
                evidence=[
                    _evidence(
                        "legacy_position_parent",
                        "Position is linked to the legacy branch label or compatibility-root department.",
                    )
                ],
            )

        personnel_key = normalize_import_key(personnel_number)
        if personnel_key in seen_personnel:
            first_row = seen_personnel[personnel_key]
            conflicts.append(
                _conflict(
                    code="duplicate_personnel_number",
                    scope="staff",
                    message="Multiple legacy rows share one personnel number.",
                    refs=[
                        _ref(sheet_name, first_row, column_map.personnel_number, first_row.personnel_number),
                        _ref(sheet_name, row, column_map.personnel_number, row.personnel_number),
                    ],
                    proposal_ids=[_staff_key(personnel_number)],
                )
            )
            continue
        seen_personnel[personnel_key] = row
        staff_by_personnel[personnel_key] = CanonicalStaffProposal(
            personnel_number=personnel_number,
            first_name=_text(row.first_name) or "Не указано",
            last_name=_text(row.last_name) or "Не указано",
            position_external_key=position_key,
            branch_external_key=branch_key,
            department_external_key=department_key,
            email=_text(row.email).lower() or None,
            phone=_text(row.phone) or None,
            external_key=_staff_key(personnel_number),
            action=MatchAction.CREATE,
            confidence=ProposalConfidence.HIGH,
            source_refs=refs,
            evidence=[
                _evidence(
                    "legacy_personnel_number",
                    "Staff identity is taken from the legacy personnel number.",
                )
            ],
        )

    for key, proposal in branch_by_key.items():
        branch_by_key[key] = proposal.model_copy(update={"source_refs": branch_refs[key]})
    for key, proposal in department_by_key.items():
        department_by_key[key] = proposal.model_copy(update={"source_refs": department_refs[key]})
    for key, proposal in position_by_key.items():
        position_by_key[key] = proposal.model_copy(update={"source_refs": position_refs[key]})

    top_evidence = [
        _evidence(
            "legacy_flat_adapter",
            "Rows were converted from the historical flat staff format without database writes.",
        )
    ]
    if not branch_by_key and department_by_key:
        top_evidence.append(
            _evidence(
                "legacy_branch_absent",
                "No branch column or explicit branch label was found; root-department compatibility was used.",
                confidence=ProposalConfidence.MEDIUM,
            )
        )

    return ImportSessionProposal(
        mode=requested_mode,
        source_file_name=source_file_name,
        source_file_sha256=source_file_sha256,
        extracted_by="legacy-flat-adapter-v1",
        branches=sorted(branch_by_key.values(), key=lambda item: item.external_key),
        departments=sorted(department_by_key.values(), key=lambda item: item.external_key),
        positions=sorted(position_by_key.values(), key=lambda item: item.external_key),
        staff=sorted(staff_by_personnel.values(), key=lambda item: item.external_key),
        conflicts=conflicts,
        evidence=top_evidence,
        **({"generated_at": generated_at} if generated_at is not None else {}),
    )
