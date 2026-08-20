"""Deterministic, side-effect-free inspection of already-loaded staff sheets.

This module deliberately stops before parsing a file or proposing a database
mutation.  Its input is a small adapter value (sheet name, row values and
merged-range metadata), so callers can use it with XLS, XLSX, CSV or a test
fixture without making the analysis module know about a file format.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

_LABEL_RE = re.compile(r"[^\w]+", flags=re.UNICODE)


@dataclass(frozen=True)
class LoadedStaffSheet:
    """Adapter input for one already-loaded worksheet."""

    name: str
    rows: Sequence[Sequence[Any]]
    merged_ranges: Sequence[str] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "rows", tuple(tuple(row) for row in self.rows))
        object.__setattr__(self, "merged_ranges", tuple(sorted(str(value) for value in self.merged_ranges)))


@dataclass(frozen=True)
class Evidence:
    code: str
    message: str
    confidence: str
    source_rows: tuple[int, ...] = ()


@dataclass(frozen=True)
class HeaderCandidate:
    row_number: int
    raw_labels: tuple[str, ...]
    recognized_fields: tuple[str, ...]
    score: float
    confidence: str


# HeaderMatch is retained as a descriptive public alias for callers that use
# the analysis vocabulary rather than the concrete DTO name.
HeaderMatch = HeaderCandidate


@dataclass(frozen=True)
class RepeatedHeaderCandidate:
    row_number: int
    matches_row_number: int
    raw_labels: tuple[str, ...]
    confidence: str


@dataclass(frozen=True)
class EmployeeSheetEvidence:
    score: float
    confidence: str
    matched_fields: tuple[str, ...]
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class StaffWorkbookSheetInspection:
    name: str
    row_count: int
    column_count: int
    merged_ranges: tuple[str, ...]
    header_candidates: tuple[HeaderCandidate, ...]
    repeated_header_candidates: tuple[RepeatedHeaderCandidate, ...]
    empty_or_decorative_rows: tuple[int, ...]
    employee_sheet_evidence: EmployeeSheetEvidence


@dataclass(frozen=True)
class StaffWorkbookAnalysis:
    sheets: tuple[StaffWorkbookSheetInspection, ...]
    likely_employee_sheets: tuple[str, ...]


# The aliases are intentionally conservative.  A tenant's arbitrary header
# label remains in raw_labels; only a known label is classified semantically.
_FIELD_ALIASES: dict[str, frozenset[str]] = {
    "employee_identity": frozenset(
        {
            "фио",
            "фио сотрудника",
            "сотрудник",
            "имя",
            "фамилия",
            "имя фамилия",
            "полное имя",
            "full name",
            "employee",
            "employee name",
            "employee id",
            "personnel number",
            "personnel no",
            "табельный",
            "табельный номер",
            "иин",
            "iin",
            "аты жөні",
            "қызметкер",
            "қызметкер аты жөні",
            "аты жөнi",
        }
    ),
    "position": frozenset({"должность", "position", "job title", "роль", "лауазымы", "лауазымы қызметкердің"}),
    "department": frozenset({"отдел", "подразделение", "department", "unit", "бөлім", "бөлімше"}),
    "branch": frozenset({"филиал", "branch", "филиал атауы", "филиал名称"}),
    "email": frozenset({"email", "e mail", "почта", "электронная почта", "электронды пошта", "e mail address"}),
    "phone": frozenset({"телефон", "phone", "mobile", "мобильный", "телефон нөмірі", "ұялы телефон"}),
}


def _normalize_label(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    return " ".join(_LABEL_RE.sub(" ", text).split())


def _labels(row: Sequence[Any], width: int) -> tuple[str, ...]:
    return tuple("" if value is None else str(value).strip() for value in (*row, *([None] * width)))[:width]


def _field_for_label(value: Any) -> str | None:
    normalized = _normalize_label(value)
    if not normalized:
        return None
    for field, aliases in _FIELD_ALIASES.items():
        if normalized in aliases:
            return field
    return None


def _row_width(rows: Sequence[Sequence[Any]]) -> int:
    return max((len(row) for row in rows), default=0)


def _candidate_for_row(row_number: int, row: Sequence[Any], width: int) -> HeaderCandidate | None:
    raw_labels = _labels(row, width)
    non_empty = tuple(value for value in raw_labels if value)
    if len(non_empty) < 2:
        return None
    fields = tuple(dict.fromkeys(field for field in (_field_for_label(value) for value in raw_labels) if field))
    # Two independent semantic labels are enough to show a useful candidate;
    # one label alone is too easy to confuse with a document title.
    if len(fields) < 2:
        return None
    core_fields = {field for field in fields if field not in {"email", "phone"}}
    score = min(1.0, len(core_fields) * 0.22 + len(set(fields) - core_fields) * 0.08 + 0.16)
    confidence = "high" if len(fields) >= 3 else "medium"
    return HeaderCandidate(
        row_number=row_number,
        raw_labels=raw_labels,
        recognized_fields=tuple(sorted(fields)),
        score=round(score, 2),
        confidence=confidence,
    )


def _header_signature(row: Sequence[Any], width: int) -> tuple[str, ...]:
    return tuple(_normalize_label(value) for value in _labels(row, width))


def _repeated_headers(
    rows: Sequence[Sequence[Any]], width: int, candidates: Sequence[HeaderCandidate]
) -> tuple[RepeatedHeaderCandidate, ...]:
    result: list[RepeatedHeaderCandidate] = []
    for candidate in candidates:
        signature = _header_signature(rows[candidate.row_number - 1], width)
        for index in range(candidate.row_number, len(rows)):
            if _header_signature(rows[index], width) != signature:
                continue
            result.append(
                RepeatedHeaderCandidate(
                    row_number=index + 1,
                    matches_row_number=candidate.row_number,
                    raw_labels=_labels(rows[index], width),
                    confidence="high" if candidate.confidence == "high" else "medium",
                )
            )
    return tuple(sorted(result, key=lambda item: (item.row_number, item.matches_row_number)))


def _empty_or_decorative_rows(
    rows: Sequence[Sequence[Any]], width: int, candidates: Sequence[HeaderCandidate]
) -> tuple[int, ...]:
    candidate_rows = {candidate.row_number for candidate in candidates}
    result: list[int] = []
    for row_number, row in enumerate(rows, start=1):
        values = _labels(row, width)
        count = sum(bool(value) for value in values)
        if count == 0 or row_number in candidate_rows:
            if count == 0:
                result.append(row_number)
            continue
        # With no viable header, every short row is explanatory/decorative
        # metadata.  With a viable header, only one-cell separators qualify.
        if not candidates and count <= 2:
            result.append(row_number)
        elif candidates and count == 1:
            result.append(row_number)
    return tuple(result)


def _employee_evidence(candidates: Sequence[HeaderCandidate]) -> EmployeeSheetEvidence:
    if not candidates:
        return EmployeeSheetEvidence(
            score=0.0,
            confidence="low",
            matched_fields=(),
            evidence=(
                Evidence("no_employee_header", "No row contains two recognized staff-structure labels.", "high"),
            ),
        )
    best = candidates[0]
    fields = set(best.recognized_fields)
    core_order = ("employee_identity", "position", "branch", "department")
    matched = tuple(field for field in core_order if field in fields)
    score = 0.0
    evidence: list[Evidence] = []
    if "employee_identity" in fields:
        score += 0.45
        evidence.append(
            Evidence("employee_identity_header", "A staff identity label was found.", "high", (best.row_number,))
        )
    if "position" in fields:
        score += 0.35
        evidence.append(Evidence("position_header", "A position label was found.", "high", (best.row_number,)))
    if fields.intersection({"branch", "department"}):
        score += 0.1
        evidence.append(
            Evidence("structure_header", "A branch or department label was found.", "medium", (best.row_number,))
        )
    if fields.intersection({"email", "phone"}):
        score += 0.1
        evidence.append(Evidence("contact_header", "A contact label was found.", "medium", (best.row_number,)))
    score = round(min(score, 1.0), 2)
    confidence = "high" if score >= 0.8 else "medium" if score >= 0.5 else "low"
    return EmployeeSheetEvidence(score, confidence, matched, tuple(evidence))


def _inspect_sheet(sheet: LoadedStaffSheet) -> StaffWorkbookSheetInspection:
    rows = sheet.rows
    width = _row_width(rows)
    candidates = tuple(
        sorted(
            (
                candidate
                for number, row in enumerate(rows, start=1)
                if (candidate := _candidate_for_row(number, row, width))
            ),
            key=lambda item: (-item.score, item.row_number),
        )
    )
    return StaffWorkbookSheetInspection(
        name=sheet.name,
        row_count=len(rows),
        column_count=width,
        merged_ranges=sheet.merged_ranges,
        header_candidates=candidates,
        repeated_header_candidates=_repeated_headers(rows, width, candidates),
        empty_or_decorative_rows=_empty_or_decorative_rows(rows, width, candidates),
        employee_sheet_evidence=_employee_evidence(candidates),
    )


def analyze_staff_workbook(sheets: Iterable[LoadedStaffSheet]) -> StaffWorkbookAnalysis:
    """Return deterministic metadata and employee-sheet evidence only.

    No input row is written, parsed into canonical staff, logged, persisted or
    sent to an AI model.  The caller remains responsible for an explicit
    mapping/review/commit workflow after this analysis.
    """

    inspections = tuple(_inspect_sheet(sheet) for sheet in sheets)
    likely = tuple(
        inspection.name
        for inspection in inspections
        if inspection.employee_sheet_evidence.confidence in {"high", "medium"}
    )
    return StaffWorkbookAnalysis(sheets=inspections, likely_employee_sheets=likely)


def compute_workbook_signature(
    analysis: StaffWorkbookAnalysis,
    *,
    selected_sheet: str | None = None,
    raw_columns: Sequence[str] | None = None,
) -> str:
    """Hash the workbook shape and selected header, never employee cell values.

    ``raw_columns`` comes from the parser's chosen header row.  It is essential
    for tenant-specific templates whose labels are not in our built-in alias
    catalogue: two equally wide workbooks must not share a profile merely
    because their sheet names match.
    """

    structural = [
        {
            "name": _normalize_label(sheet.name),
            "columns": sheet.column_count,
            "headers": [
                {
                    "row": candidate.row_number,
                    "labels": [_normalize_label(label) for label in candidate.raw_labels],
                    "fields": list(candidate.recognized_fields),
                }
                for candidate in sheet.header_candidates
            ],
        }
        for sheet in analysis.sheets
    ]
    structural.append(
        {
            "selected_sheet": _normalize_label(selected_sheet or ""),
            "selected_header": [_normalize_label(str(label)) for label in (raw_columns or ())],
        }
    )
    encoded = json.dumps(structural, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()
