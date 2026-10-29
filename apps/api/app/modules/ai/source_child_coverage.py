"""Literal child accounting for caller-selected source list references.

This module does not decide whether a source list is normative and does not
create assessment targets.  Once a caller has selected a source reference for
assessment, it prevents one parent-level obligation from being mistaken for
complete coverage of the reference's explicit list children.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Literal

from app.modules.ai.assessment_obligations import MATERIAL_DIMENSIONS, MaterialObligation
from app.modules.ai.evidence_engine.models import SourceFact
from app.modules.ai.source_layout import (
    SOURCE_HORIZONTAL_SPACE,
    SourceMarker,
    parse_source_marker,
    split_marker_paragraphs,
)

_MAX_SOURCE_CHARS = 100_000
_MAX_CHILDREN = 192
_MAX_REASON_CHARS = 500
_PROTECTED_OPERATOR_RE = re.compile(r">=|<=|!=|[><=≥≤≠+\-−%‰°²³/]")
_LATIN_MARKER_ORDER = "abcdefghijklmnopqrstuvwxyz"
_RUSSIAN_MARKER_ORDER = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
_KAZAKH_MARKER_ORDER = "аәбвгғдеёжзийкқлмнңоөпрстуұүфхһцчшщъыіьэюя"
_KAZAKH_SPECIFIC_MARKERS = frozenset(_KAZAKH_MARKER_ORDER) - frozenset(
    _RUSSIAN_MARKER_ORDER
)

ChildDispositionState = Literal["excluded", "unresolved"]


@dataclass(frozen=True, slots=True)
class LiteralSourceChild:
    """One exact marked child under a literal colon-ended source owner."""

    child_id: str
    source_ref: str
    fact_id: str
    source_locator: str
    source_sha256: str
    owner_start: int
    owner_end: int
    owner_quote: str
    marker_start: int
    marker_end: int
    marker: str
    quote_start: int
    quote_end: int
    quote: str


@dataclass(frozen=True, slots=True)
class SourceChildDisposition:
    """Exact server-owned negative accounting; never semantic approval."""

    child_id: str
    source_ref: str
    fact_id: str
    source_sha256: str
    quote_start: int
    quote_end: int
    quote: str
    state: ChildDispositionState
    reason: str
    semantic_approval: bool = False


@dataclass(frozen=True, slots=True)
class SourceChildScopeMarkerBridge:
    """Exact layout custody only; the caller separately proves target ownership."""

    source_ref: str
    source_sha256: str
    child_id: str
    binding_span: tuple[int, int]
    marker_span: tuple[int, int]
    marker_family: str
    action_span: tuple[int, int]
    semantic_approval: bool = False


@dataclass(frozen=True, slots=True)
class SourceChildCoverageGap:
    child_id: str
    source_ref: str
    fact_id: str
    source_locator: str
    source_sha256: str
    quote_start: int
    quote_end: int
    quote: str
    code: str
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceChildCoverageLedger:
    """Deterministic accounting result for one selected source reference."""

    source_ref: str
    fact_id: str
    source_sha256: str
    applicable: bool
    children: tuple[LiteralSourceChild, ...]
    covered_child_ids: tuple[str, ...]
    excluded_child_ids: tuple[str, ...]
    unresolved_child_ids: tuple[str, ...]
    gaps: tuple[SourceChildCoverageGap, ...]
    layout_unknowns: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.gaps and not self.layout_unknowns


@dataclass(frozen=True, slots=True)
class _Piece:
    start: int
    end: int
    text: str
    marker: SourceMarker | None
    content_end: int

    @property
    def body_start(self) -> int:
        if self.marker is None:
            return self.start
        return self.start + self.marker.content_start

    @property
    def body(self) -> str:
        return self.text[self.body_start - self.start : self.content_end - self.start]


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _source_digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _pieces(source_text: str) -> tuple[_Piece, ...]:
    offset = 0
    result: list[_Piece] = []
    for text in split_marker_paragraphs(source_text):
        if not text:
            continue
        first_line = text.splitlines(keepends=True)[0].rstrip("\r\n")
        marker = parse_source_marker(first_line)
        content_end = offset + len(text.rstrip("\r\n"))
        result.append(_Piece(offset, offset + len(text), text, marker, content_end))
        offset += len(text)
    if offset != len(source_text):
        raise ValueError("source_child_coverage_nonconserving_layout")
    return tuple(result)


def _same_child_family(left: SourceMarker, right: SourceMarker) -> bool:
    return left.family == right.family


def _numeric_sequence_unknown(markers: Sequence[SourceMarker]) -> bool:
    paths = [marker.numeric_path for marker in markers]
    if not paths or any(not path for path in paths):
        return False
    prefix = paths[0][:-1]
    if any(path[:-1] != prefix for path in paths):
        return True
    return [path[-1] for path in paths] != list(
        range(paths[0][-1], paths[0][-1] + len(paths))
    )


def _consecutive_letters(letters: Sequence[str], alphabet: str) -> bool:
    try:
        positions = [alphabet.index(letter) for letter in letters]
    except ValueError:
        return False
    return positions == list(range(positions[0], positions[0] + len(positions)))


def _letter_sequence_unknown(markers: Sequence[SourceMarker]) -> str | None:
    letters = [marker.letter.casefold() for marker in markers]
    rendered = ",".join(letters)
    if not letters or any(not letter for letter in letters):
        return "unknown_explicit_child_marker_alphabet:" + rendered
    if all(letter in _LATIN_MARKER_ORDER for letter in letters):
        if _consecutive_letters(letters, _LATIN_MARKER_ORDER):
            return None
        return "nonconsecutive_explicit_child_markers:" + rendered

    cyrillic_markers = frozenset(_RUSSIAN_MARKER_ORDER + _KAZAKH_MARKER_ORDER)
    if not all(letter in cyrillic_markers for letter in letters):
        return "mixed_explicit_child_marker_alphabets:" + rendered
    if any(letter in _KAZAKH_SPECIFIC_MARKERS for letter in letters):
        if _consecutive_letters(letters, _KAZAKH_MARKER_ORDER):
            return None
        return "nonconsecutive_explicit_child_markers:" + rendered

    russian_consecutive = _consecutive_letters(letters, _RUSSIAN_MARKER_ORDER)
    kazakh_consecutive = _consecutive_letters(letters, _KAZAKH_MARKER_ORDER)
    if russian_consecutive and kazakh_consecutive:
        return None
    if russian_consecutive != kazakh_consecutive:
        return "ambiguous_cyrillic_child_markers:" + rendered
    return "nonconsecutive_explicit_child_markers:" + rendered


def _literal_children(
    source_ref: str,
    fact: SourceFact,
) -> tuple[tuple[LiteralSourceChild, ...], tuple[str, ...]]:
    source_sha256 = _source_digest(fact.value)
    pieces = _pieces(fact.value)
    children: list[LiteralSourceChild] = []
    unknowns: list[str] = []
    occupied: set[int] = set()
    for owner_index, owner in enumerate(pieces[:-2]):
        owner_body = owner.body.strip()
        if not owner_body.endswith(":"):
            continue
        first = pieces[owner_index + 1]
        if first.marker is None:
            continue
        siblings = [first]
        for candidate in pieces[owner_index + 2 :]:
            if candidate.marker is None or not _same_child_family(first.marker, candidate.marker):
                break
            siblings.append(candidate)
        if len(siblings) < 2:
            continue
        if any(piece.start in occupied for piece in siblings):
            unknowns.append("overlapping_explicit_list_owners")
            continue
        markers = [piece.marker for piece in siblings if piece.marker is not None]
        if first.marker.family == "numeric" and _numeric_sequence_unknown(markers):
            unknowns.append(
                "nonconsecutive_explicit_child_markers:"
                + ",".join(".".join(map(str, marker.numeric_path)) for marker in markers)
            )
        elif first.marker.family == "letter":
            letter_unknown = _letter_sequence_unknown(markers)
            if letter_unknown is not None:
                unknowns.append(letter_unknown)
        for piece in siblings:
            marker = piece.marker
            if marker is None:
                raise AssertionError("source child marker disappeared")
            quote_start = piece.body_start
            quote_end = piece.content_end
            quote = fact.value[quote_start:quote_end]
            if not quote:
                unknowns.append(f"empty_explicit_child:{piece.start}")
                continue
            identity = [source_ref, fact.fact_id, source_sha256, quote_start, quote_end, quote]
            children.append(
                LiteralSourceChild(
                    child_id="source-child-" + _digest(identity)[:24],
                    source_ref=source_ref,
                    fact_id=fact.fact_id,
                    source_locator=fact.source_locator,
                    source_sha256=source_sha256,
                    owner_start=owner.body_start,
                    owner_end=owner.content_end,
                    owner_quote=fact.value[owner.body_start : owner.content_end],
                    marker_start=piece.start + marker.raw_start,
                    marker_end=piece.start + marker.content_start,
                    marker=marker.raw_marker,
                    quote_start=quote_start,
                    quote_end=quote_end,
                    quote=quote,
                )
            )
            occupied.add(piece.start)
    # Inventory explicit parenthesized enumerations without deciding whether any
    # fragment is independently normative or manufacturing assessment targets.
    for match in re.finditer(r"\(\s*включая\s+([^()]{1,400})\)", fact.value, re.IGNORECASE):
        body_start, body_end = match.span(1)
        body = fact.value[body_start:body_end]
        separators = list(re.finditer(r"(?<!\d),(?!\d)|(?<=\D),(?=\d)|(?<=\d),(?=\D)", body))
        if not separators:
            continue
        if any(match.start() < child.quote_end and match.end() > child.quote_start for child in children):
            unknowns.append("inline_list_nested_in_marked_child")
            continue
        starts = [0, *(separator.end() for separator in separators)]
        ends = [*(separator.start() for separator in separators), len(body)]
        for start, end in zip(starts, ends, strict=True):
            fragment = body[start:end]
            left = len(fragment) - len(fragment.lstrip())
            right = len(fragment.rstrip())
            if end == len(body):
                suffix = re.search(r"\s+(?:и\s+т\.\s*п\.|и\s+т\.\s*д\.)\s*$", fragment, re.IGNORECASE)
                if suffix:
                    right = len(fragment[:suffix.start()].rstrip())
            quote_start, quote_end = body_start + start + left, body_start + start + right
            quote = fact.value[quote_start:quote_end]
            if not quote:
                unknowns.append("empty_inline_list_child")
                continue
            identity = [source_ref, fact.fact_id, source_sha256, quote_start, quote_end, quote]
            children.append(LiteralSourceChild(
                child_id="source-child-" + _digest(identity)[:24],
                source_ref=source_ref, fact_id=fact.fact_id, source_locator=fact.source_locator,
                source_sha256=source_sha256, owner_start=match.start(), owner_end=match.end(),
                owner_quote=match.group(), marker_start=quote_start, marker_end=quote_start,
                marker="", quote_start=quote_start, quote_end=quote_end, quote=quote,
            ))
    if len(children) > _MAX_CHILDREN:
        raise ValueError("source_child_coverage_child_limit")
    return tuple(children), tuple(dict.fromkeys(unknowns))


def bind_source_child_disposition(
    child: LiteralSourceChild,
    *,
    state: ChildDispositionState,
    reason: str,
) -> SourceChildDisposition:
    """Bind one exact source-owned exclusion or unresolved decision to a child."""

    if state not in {"excluded", "unresolved"}:
        raise ValueError("source_child_disposition_state")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > _MAX_REASON_CHARS:
        raise ValueError("source_child_disposition_reason")
    return SourceChildDisposition(
        child_id=child.child_id,
        source_ref=child.source_ref,
        fact_id=child.fact_id,
        source_sha256=child.source_sha256,
        quote_start=child.quote_start,
        quote_end=child.quote_end,
        quote=child.quote,
        state=state,
        reason=reason.strip(),
    )


def _disposition_matches(child: LiteralSourceChild, row: SourceChildDisposition) -> bool:
    return (
        row.semantic_approval is False
        and row.child_id == child.child_id
        and row.source_ref == child.source_ref
        and row.fact_id == child.fact_id
        and row.source_sha256 == child.source_sha256
        and row.quote_start == child.quote_start
        and row.quote_end == child.quote_end
        and row.quote == child.quote
        and row.state in {"excluded", "unresolved"}
        and bool(row.reason.strip())
        and len(row.reason) <= _MAX_REASON_CHARS
    )


def _child_body_interval(
    child: LiteralSourceChild,
    obligation: MaterialObligation,
    *,
    source_text: str,
) -> tuple[int, int] | None:
    """Return only the obligation interval owned by the literal child body."""

    start = obligation.quote_start
    end = obligation.quote_end
    if (
        isinstance(start, bool)
        or not isinstance(start, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
    ):
        return None
    if child.quote_start <= start < end <= child.quote_end:
        return start, end
    exact_marker_prefix = (
        start == child.marker_start
        and child.marker_start < child.marker_end == child.quote_start
        and child.quote_start < end <= child.quote_end
        and source_text[child.marker_start : child.marker_end] == child.marker
    )
    if exact_marker_prefix:
        return child.quote_start, end
    return None


def _obligation_issue(
    child: LiteralSourceChild,
    obligation: MaterialObligation,
    *,
    source_text: str,
    admitted_target_ids: set[str],
    qualified_target_ids: set[str],
) -> str | None:
    if obligation.source_ref != child.source_ref:
        return "foreign_source_ref"
    if obligation.source_id != child.fact_id:
        return "foreign_source_id"
    start = obligation.quote_start
    end = obligation.quote_end
    if _child_body_interval(child, obligation, source_text=source_text) is None:
        return "source_child_offset_mismatch"
    assert isinstance(start, int) and not isinstance(start, bool)
    assert isinstance(end, int) and not isinstance(end, bool)
    if source_text[start:end] != obligation.quote:
        return "source_child_quote_mismatch"
    if obligation.dimension not in MATERIAL_DIMENSIONS:
        return "source_child_dimension_invalid"
    if obligation.evidence_level not in {"operational_decision", "source_recognition"}:
        return "source_child_evidence_level_invalid"
    if not obligation.target_ids:
        return "source_child_unlinked"
    targets = set(obligation.target_ids)
    if not targets <= admitted_target_ids:
        return "source_child_unadmitted_target"
    if not targets <= qualified_target_ids:
        return "source_child_unqualified_target"
    return None


def _obligation_claims_child(
    child: LiteralSourceChild,
    obligation: MaterialObligation,
) -> bool:
    """Recognize a literal child claim without attaching sibling rows to it."""

    start = obligation.quote_start
    end = obligation.quote_end
    exact_subspan = (
        not isinstance(start, bool)
        and isinstance(start, int)
        and not isinstance(end, bool)
        and isinstance(end, int)
        and child.quote_start <= start < end <= child.quote_end
        and child.quote[start - child.quote_start : end - child.quote_start]
        == obligation.quote
    )
    if exact_subspan:
        return True
    exact_literal = (
        obligation.quote == child.quote
        and start == child.quote_start
        and end == child.quote_end
    )
    if exact_literal:
        return True
    if obligation.source_ref != child.source_ref:
        return False
    if (
        not isinstance(start, bool)
        and isinstance(start, int)
        and not isinstance(end, bool)
        and isinstance(end, int)
    ):
        return (
            start < child.quote_end
            and end > child.quote_start
        )
    if obligation.source_id != child.fact_id:
        return False
    return bool(obligation.quote) and (
        obligation.quote in child.quote or child.quote in obligation.quote
    )


def _overlaps_multiple_children(
    obligation: MaterialObligation,
    children: Sequence[LiteralSourceChild],
) -> bool:
    start = obligation.quote_start
    end = obligation.quote_end
    if (
        isinstance(start, bool)
        or not isinstance(start, int)
        or isinstance(end, bool)
        or not isinstance(end, int)
        or start >= end
    ):
        return False
    return sum(start < child.quote_end and end > child.quote_start for child in children) > 1


def _required_child_positions(child: LiteralSourceChild) -> set[int]:
    required = {
        child.quote_start + index
        for index, character in enumerate(child.quote)
        if character.isalpha() or character.isdigit()
    }
    for match in _PROTECTED_OPERATOR_RE.finditer(child.quote):
        required.update(
            range(child.quote_start + match.start(), child.quote_start + match.end())
        )
    return required


def inspect_source_child_scope_marker_bridge(
    *, source_ref: str, fact: SourceFact, binding_start: int, binding_end: int,
    action_start: int, action_end: int,
) -> SourceChildScopeMarkerBridge | None:
    """Prove one terminal child span immediately precedes a marked list governor.

    No words, markers or ownership are repaired. This cannot approve an action,
    a binding, a target or coverage; it only locates an already-owned scope span.
    """
    text = fact.value
    offsets = (binding_start, binding_end, action_start, action_end)
    if (not isinstance(text, str) or len(text) > _MAX_SOURCE_CHARS
            or fact.confidence != 1 or fact.uncertainty
            or any(not isinstance(value, int) or isinstance(value, bool) for value in offsets)
            or not 0 <= binding_start < binding_end <= action_start < action_end <= len(text)):
        return None
    binding, action = text[binding_start:binding_end], text[action_start:action_end]
    if (not action.endswith(":") or text.find(binding) != binding_start
            or text.find(binding, binding_start + 1) >= 0 or text.find(action) != action_start
            or text.find(action, action_start + 1) >= 0):
        return None
    try:
        children, unknowns = _literal_children(source_ref, fact)
    except ValueError as exc:
        if str(exc) == "source_child_coverage_child_limit":
            return None
        raise
    if unknowns:
        return None
    owners = [child for child in children
              if child.quote_start <= binding_start < binding_end <= child.quote_end]
    if len(owners) != 1:
        return None
    child = owners[0]
    if any(position >= binding_end for position in _required_child_positions(child)):
        return None
    pieces = _pieces(text)
    actions = [(index, piece) for index, piece in enumerate(pieces)
               if piece.body_start == action_start and piece.content_end == action_end]
    if len(actions) != 1:
        return None
    index, piece = actions[0]
    marker = piece.marker
    if (not index or marker is None or marker.family != "numeric"
            or len(marker.numeric_path) != 1 or marker.decoration
            or pieces[index - 1].content_end != child.quote_end
            or child.quote_end > piece.start
            or any(character not in SOURCE_HORIZONTAL_SPACE + "\r\n"
                   for character in text[binding_end:piece.start])
            or not any(row.owner_start == action_start and row.owner_end == action_end for row in children)):
        return None
    return SourceChildScopeMarkerBridge(source_ref, _source_digest(text), child.child_id,
        (binding_start, binding_end), (piece.start + marker.raw_start, action_start), marker.family,
        (action_start, action_end))


def _uncovered_substantive_ranges(
    child: LiteralSourceChild,
    obligations: Sequence[MaterialObligation],
    *,
    source_text: str,
) -> tuple[tuple[int, int], ...]:
    covered: set[int] = set()
    for obligation in obligations:
        interval = _child_body_interval(child, obligation, source_text=source_text)
        assert interval is not None
        covered.update(range(*interval))
    missing = sorted(_required_child_positions(child) - covered)
    if not missing:
        return ()
    ranges: list[tuple[int, int]] = []
    start = previous = missing[0]
    for position in missing[1:]:
        if position != previous + 1:
            ranges.append((start, previous + 1))
            start = position
        previous = position
    ranges.append((start, previous + 1))
    return tuple(ranges)


def inspect_source_child_coverage(
    *,
    source_ref: str,
    fact: SourceFact,
    obligations: Sequence[MaterialObligation],
    admitted_target_ids: Collection[str],
    qualified_target_ids: Collection[str],
    dispositions: Sequence[SourceChildDisposition] = (),
) -> SourceChildCoverageLedger:
    """Audit exact child accounting for one caller-selected source reference.

    Exact in-child subspans may collectively cover the child's substantive
    characters.  At least one subspan must be an operational decision whose
    linked targets are admitted and qualification-safe.  Recognition rows may
    supplement that lexical accounting but cannot fulfill a child alone.  A
    multi-leaf parent quote earns no child credit.  This proves no semantic
    equivalence or admission, and several children may link to one target.
    """

    if not isinstance(source_ref, str) or not source_ref:
        raise ValueError("source_child_coverage_source_ref")
    if not isinstance(fact.value, str) or len(fact.value) > _MAX_SOURCE_CHARS:
        raise ValueError("source_child_coverage_source_limit")
    admitted = set(admitted_target_ids)
    qualified = set(qualified_target_ids)
    if not all(isinstance(value, str) and value for value in admitted | qualified):
        raise ValueError("source_child_coverage_target_id")
    children, layout_unknowns = _literal_children(source_ref, fact)
    if not children:
        return SourceChildCoverageLedger(
            source_ref,
            fact.fact_id,
            _source_digest(fact.value),
            False,
            (),
            (),
            (),
            (),
            (),
            layout_unknowns,
        )

    disposition_by_child: dict[str, SourceChildDisposition] = {}
    invalid_dispositions: dict[str, list[str]] = {}
    known_ids = {child.child_id for child in children}
    for disposition_row in dispositions:
        if disposition_row.child_id not in known_ids:
            invalid_dispositions.setdefault(disposition_row.child_id, []).append(
                "foreign_child_disposition"
            )
            continue
        child = next(
            child for child in children if child.child_id == disposition_row.child_id
        )
        if not _disposition_matches(child, disposition_row):
            invalid_dispositions.setdefault(disposition_row.child_id, []).append(
                "invalid_child_disposition"
            )
            continue
        if disposition_row.child_id in disposition_by_child:
            invalid_dispositions.setdefault(disposition_row.child_id, []).append(
                "duplicate_child_disposition"
            )
            continue
        disposition_by_child[disposition_row.child_id] = disposition_row

    covered: list[str] = []
    excluded: list[str] = []
    unresolved: list[str] = []
    gaps: list[SourceChildCoverageGap] = []
    for child in children:
        disposition = disposition_by_child.get(child.child_id)
        matching_rows = [
            obligation_row
            for obligation_row in obligations
            if _obligation_claims_child(child, obligation_row)
            and not _overlaps_multiple_children(obligation_row, children)
        ]
        valid_rows: list[MaterialObligation] = []
        issues: list[str] = list(invalid_dispositions.get(child.child_id, ()))
        for obligation_row in matching_rows:
            issue = _obligation_issue(
                child,
                obligation_row,
                source_text=fact.value,
                admitted_target_ids=admitted,
                qualified_target_ids=qualified,
            )
            if issue is None:
                valid_rows.append(obligation_row)
            else:
                issues.append(f"{obligation_row.obligation_id}:{issue}")
        if disposition is not None and valid_rows:
            issues.append("source_child_positive_negative_conflict")
        if issues:
            gaps.append(
                SourceChildCoverageGap(
                    child_id=child.child_id,
                    source_ref=child.source_ref,
                    fact_id=child.fact_id,
                    source_locator=child.source_locator,
                    source_sha256=child.source_sha256,
                    quote_start=child.quote_start,
                    quote_end=child.quote_end,
                    quote=child.quote,
                    code="invalid_source_child_accounting",
                    evidence_ids=tuple(dict.fromkeys(issues)),
                )
            )
            continue
        if disposition is not None:
            if disposition.state == "excluded":
                excluded.append(child.child_id)
            else:
                unresolved.append(child.child_id)
                gaps.append(
                    SourceChildCoverageGap(
                        child_id=child.child_id,
                        source_ref=child.source_ref,
                        fact_id=child.fact_id,
                        source_locator=child.source_locator,
                        source_sha256=child.source_sha256,
                        quote_start=child.quote_start,
                        quote_end=child.quote_end,
                        quote=child.quote,
                        code="unresolved_source_child",
                        evidence_ids=(disposition.reason,),
                    )
                )
            continue
        operational_rows = [
            row for row in valid_rows if row.evidence_level == "operational_decision"
        ]
        uncovered = _uncovered_substantive_ranges(
            child,
            valid_rows,
            source_text=fact.value,
        )
        if valid_rows and operational_rows and not uncovered:
            covered.append(child.child_id)
            continue
        if valid_rows:
            evidence_ids: list[str] = []
            if not operational_rows:
                evidence_ids.append("source_child_operational_evidence_missing")
            evidence_ids.extend(
                f"source_child_uncovered_substantive:{start}:{end}"
                for start, end in uncovered
            )
            gaps.append(
                SourceChildCoverageGap(
                    child_id=child.child_id,
                    source_ref=child.source_ref,
                    fact_id=child.fact_id,
                    source_locator=child.source_locator,
                    source_sha256=child.source_sha256,
                    quote_start=child.quote_start,
                    quote_end=child.quote_end,
                    quote=child.quote,
                    code="incomplete_source_child_accounting",
                    evidence_ids=tuple(evidence_ids),
                )
            )
            continue
        gaps.append(
            SourceChildCoverageGap(
                child_id=child.child_id,
                source_ref=child.source_ref,
                fact_id=child.fact_id,
                source_locator=child.source_locator,
                source_sha256=child.source_sha256,
                quote_start=child.quote_start,
                quote_end=child.quote_end,
                quote=child.quote,
                code="unaccounted_source_child",
            )
        )

    for child_id, issues in invalid_dispositions.items():
        if child_id in known_ids:
            continue
        gaps.append(
            SourceChildCoverageGap(
                child_id=child_id,
                source_ref=source_ref,
                fact_id=fact.fact_id,
                source_locator=fact.source_locator,
                source_sha256=_source_digest(fact.value),
                quote_start=0,
                quote_end=0,
                quote="",
                code="invalid_source_child_accounting",
                evidence_ids=tuple(dict.fromkeys(issues)),
            )
        )
    return SourceChildCoverageLedger(
        source_ref=source_ref,
        fact_id=fact.fact_id,
        source_sha256=_source_digest(fact.value),
        applicable=True,
        children=children,
        covered_child_ids=tuple(covered),
        excluded_child_ids=tuple(excluded),
        unresolved_child_ids=tuple(unresolved),
        gaps=tuple(gaps),
        layout_unknowns=layout_unknowns,
    )
