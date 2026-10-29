"""Exact source custody for bounded learner-response projections.

This module performs no truth, key, grammar, or assessment admission.  It only
proves that a response budget and an optional given/assessed split are bound to
one exact, uniquely owned source component.  Unsafe splits retain the complete
component as the assessed answer instead of guessing a semantic partition.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Literal

DEFAULT_OPTION_MAX_CHARS = 240
ABSOLUTE_OPTION_MAX_CHARS = 320

_MAX_SOURCES = 256
_MAX_SOURCE_TEXT_CHARS = 65_536
_MAX_SPANS = 32
_MAX_EXPANSIONS = 4
_MAX_EXPANSION_CHARS = 16
_MAX_ID_CHARS = 100
_POLICY = "source-response-projection-v1"

Disposition = Literal["given", "assessed"]
SpanRole = Literal[
    "actor",
    "action",
    "condition",
    "timing",
    "exception",
    "scope",
    "object",
    "qualifier",
    "operator",
    "other",
]
ExpansionKind = Literal["prohibition_negation", "function_token"]

_DISPOSITIONS = frozenset({"given", "assessed"})
_ROLES = frozenset({
    "actor",
    "action",
    "condition",
    "timing",
    "exception",
    "scope",
    "object",
    "qualifier",
    "operator",
    "other",
})
_PROHIBITION_OWNERS = frozenset({
    "запрещается",
    "запрещено",
    "не допускается",
    "не разрешается",
})
_FUNCTION_TOKENS = frozenset({"в", "для", "и", "или", "либо", "на", "по", "при"})
_PROTECTED_ALTERNATIVE = re.compile(r"(?<!\w)(?:или|либо)(?!\w)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class OwnedSource:
    source_id: str
    text: str


@dataclass(frozen=True, slots=True)
class OwnedResponseSpan:
    source_id: str
    start: int
    end: int
    text: str
    disposition: Disposition
    role: SpanRole
    assessment_required: bool = False


@dataclass(frozen=True, slots=True)
class LiteralExpansion:
    source_id: str
    start: int
    end: int
    text: str
    kind: ExpansionKind
    rendered_literal: str


@dataclass(frozen=True, slots=True)
class SourceResponseProjectionInput:
    target_id: str
    sources: tuple[OwnedSource, ...]
    component: str
    spans: tuple[OwnedResponseSpan, ...]
    candidate_text: str
    literal_expansions: tuple[LiteralExpansion, ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectionLedgerEntry:
    source_id: str
    start: int
    end: int
    text: str
    text_sha256: str
    disposition: Disposition
    role: str
    assessment_required: bool


@dataclass(frozen=True, slots=True)
class LiteralExpansionReceipt:
    source_id: str
    start: int
    end: int
    text: str
    text_sha256: str
    kind: ExpansionKind
    rendered_literal: str


@dataclass(frozen=True, slots=True)
class SourceResponseProjection:
    version: str
    target_id: str
    source_id: str
    source_start: int
    source_end: int
    source_sha256: str
    target_sha256: str
    component_sha256: str
    candidate_sha256: str
    input_sha256: str
    canonical_source_answer: str
    option_max_chars: int
    premise_projection: bool
    ledger: tuple[ProjectionLedgerEntry, ...]
    literal_expansions: tuple[LiteralExpansionReceipt, ...]
    semantic_credit: Literal[False]
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class SourceResponseBudgetProof:
    """Exact inputs retained for downstream length-only recomputation."""

    request: SourceResponseProjectionInput
    receipt: SourceResponseProjection


def verified_response_option_limit(proof: SourceResponseBudgetProof | None, *, answer: str) -> int:
    """A valid receipt changes only a length bound, never truth or admission."""
    if (not isinstance(proof, SourceResponseBudgetProof)
            or not isinstance(proof.request, SourceResponseProjectionInput)
            or proof.request.candidate_text != answer
            or not verify_source_response_projection(proof.request, proof.receipt)):
        return DEFAULT_OPTION_MAX_CHARS
    return proof.receipt.option_max_chars


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return _sha256(payload)


def _valid_text(value: object, *, maximum: int | None = None) -> bool:
    return isinstance(value, str) and bool(value) and (maximum is None or len(value) <= maximum)


def _component_owner(
    sources: tuple[OwnedSource, ...], component: str,
) -> tuple[OwnedSource, int, int] | None:
    if not isinstance(sources, tuple) or not 1 <= len(sources) <= _MAX_SOURCES:
        return None
    seen_ids: set[str] = set()
    matches: list[tuple[OwnedSource, int, int]] = []
    for source in sources:
        if (
            not isinstance(source, OwnedSource)
            or not _valid_text(source.source_id, maximum=_MAX_ID_CHARS)
            or not _valid_text(source.text, maximum=_MAX_SOURCE_TEXT_CHARS)
            or source.source_id in seen_ids
        ):
            return None
        seen_ids.add(source.source_id)
        cursor = 0
        while (start := source.text.find(component, cursor)) >= 0:
            end = start + len(component)
            if _cuts_word(source.text, start) or _cuts_word(source.text, end):
                cursor = start + 1
                continue
            matches.append((source, start, end))
            if len(matches) > 1:
                return None
            cursor = start + 1
    return matches[0] if len(matches) == 1 else None


def _wordish(character: str) -> bool:
    category = unicodedata.category(character)
    return character == "_" or category[:1] in {"L", "M", "N"}


def _cuts_word(source_text: str, boundary: int) -> bool:
    return (
        0 < boundary < len(source_text)
        and _wordish(source_text[boundary - 1])
        and _wordish(source_text[boundary])
    )


def _fallback_ledger(
    source: OwnedSource, start: int, end: int, component: str,
) -> tuple[ProjectionLedgerEntry, ...]:
    return (
        ProjectionLedgerEntry(
            source_id=source.source_id,
            start=start,
            end=end,
            text=component,
            text_sha256=_sha256(component),
            disposition="assessed",
            role="whole_component",
            assessment_required=True,
        ),
    )


def _projected_ledger(
    request: SourceResponseProjectionInput,
    source: OwnedSource,
    component_start: int,
    component_end: int,
) -> tuple[tuple[ProjectionLedgerEntry, ...], str, bool] | None:
    spans = request.spans
    if not isinstance(spans, tuple) or not 1 <= len(spans) <= _MAX_SPANS:
        return None
    ordered: list[OwnedResponseSpan] = []
    for span in spans:
        if (
            not isinstance(span, OwnedResponseSpan)
            or span.source_id != source.source_id
            or isinstance(span.start, bool)
            or isinstance(span.end, bool)
            or not isinstance(span.start, int)
            or not isinstance(span.end, int)
            or not component_start <= span.start < span.end <= component_end
            or source.text[span.start:span.end] != span.text
            or span.disposition not in _DISPOSITIONS
            or span.role not in _ROLES
            or not isinstance(span.assessment_required, bool)
        ):
            return None
        ordered.append(span)
    ordered.sort(key=lambda row: (row.start, row.end))
    if ordered[0].start != component_start or ordered[-1].end != component_end:
        return None
    for left, right in zip(ordered, ordered[1:], strict=False):
        if left.end != right.start or _cuts_word(source.text, left.end):
            return None
    if _cuts_word(source.text, ordered[0].start):
        return None
    if _cuts_word(source.text, ordered[-1].end):
        return None
    if any(row.assessment_required and row.disposition != "assessed" for row in ordered):
        return None

    assessed = [row for row in ordered if row.disposition == "assessed"]
    given = [row for row in ordered if row.disposition == "given"]
    if len(assessed) != 1 or not given or assessed[0].text != assessed[0].text.strip():
        return None
    for alternative in _PROTECTED_ALTERNATIVE.finditer(request.component):
        absolute_start = component_start + alternative.start()
        absolute_end = component_start + alternative.end()
        if not (assessed[0].start <= absolute_start and absolute_end <= assessed[0].end):
            return None

    ledger = tuple(
        ProjectionLedgerEntry(
            source_id=row.source_id,
            start=row.start,
            end=row.end,
            text=row.text,
            text_sha256=_sha256(row.text),
            disposition=row.disposition,
            role=row.role,
            assessment_required=row.assessment_required,
        )
        for row in ordered
    )
    return ledger, assessed[0].text, True


def _literal_expansion_receipts(
    expansions: tuple[LiteralExpansion, ...], source: OwnedSource,
) -> tuple[LiteralExpansionReceipt, ...] | None:
    if not isinstance(expansions, tuple) or len(expansions) > _MAX_EXPANSIONS:
        return None
    receipts: list[LiteralExpansionReceipt] = []
    occupied: list[tuple[int, int]] = []
    rendered_chars = 0
    for expansion in expansions:
        if (
            not isinstance(expansion, LiteralExpansion)
            or expansion.source_id != source.source_id
            or isinstance(expansion.start, bool)
            or isinstance(expansion.end, bool)
            or not isinstance(expansion.start, int)
            or not isinstance(expansion.end, int)
            or not 0 <= expansion.start < expansion.end <= len(source.text)
            or source.text[expansion.start:expansion.end] != expansion.text
            or not expansion.rendered_literal
            or _cuts_word(source.text, expansion.start)
            or _cuts_word(source.text, expansion.end)
        ):
            return None
        owner = expansion.text.strip().casefold()
        if expansion.kind == "prohibition_negation":
            if owner not in _PROHIBITION_OWNERS or expansion.rendered_literal != "не ":
                return None
        elif expansion.kind == "function_token":
            if owner not in _FUNCTION_TOKENS or expansion.rendered_literal != owner + " ":
                return None
        else:
            return None
        if any(expansion.start < end and start < expansion.end for start, end in occupied):
            return None
        occupied.append((expansion.start, expansion.end))
        rendered_chars += len(expansion.rendered_literal)
        if rendered_chars > _MAX_EXPANSION_CHARS:
            return None
        receipts.append(
            LiteralExpansionReceipt(
                source_id=expansion.source_id,
                start=expansion.start,
                end=expansion.end,
                text=expansion.text,
                text_sha256=_sha256(expansion.text),
                kind=expansion.kind,
                rendered_literal=expansion.rendered_literal,
            )
        )
    return tuple(receipts)


def _input_payload(request: SourceResponseProjectionInput) -> dict[str, object]:
    return {
        "target_id": request.target_id,
        "sources": [asdict(source) for source in request.sources],
        "component": request.component,
        "spans": [asdict(span) for span in request.spans],
        "candidate_text": request.candidate_text,
        "literal_expansions": [asdict(row) for row in request.literal_expansions],
    }


def build_source_response_projection(
    request: SourceResponseProjectionInput,
) -> SourceResponseProjection | None:
    """Build a zero-credit receipt for one exact source-owned response surface."""
    if (
        not isinstance(request, SourceResponseProjectionInput)
        or not _valid_text(request.target_id, maximum=_MAX_ID_CHARS)
        or not _valid_text(request.component, maximum=ABSOLUTE_OPTION_MAX_CHARS)
        or not _valid_text(request.candidate_text, maximum=ABSOLUTE_OPTION_MAX_CHARS)
        or not isinstance(request.spans, tuple)
        or len(request.spans) > _MAX_SPANS
        or any(not isinstance(row, OwnedResponseSpan) for row in request.spans)
        or not isinstance(request.literal_expansions, tuple)
        or any(not isinstance(row, LiteralExpansion) for row in request.literal_expansions)
    ):
        return None
    owner = _component_owner(request.sources, request.component)
    if owner is None:
        return None
    source, component_start, component_end = owner
    expansion_receipts = _literal_expansion_receipts(request.literal_expansions, source)
    if expansion_receipts is None:
        return None

    projection = _projected_ledger(request, source, component_start, component_end)
    if projection is None:
        ledger = _fallback_ledger(source, component_start, component_end, request.component)
        canonical_answer = request.component
        premise_projection = False
    else:
        ledger, canonical_answer, premise_projection = projection

    option_max_chars = max(
        DEFAULT_OPTION_MAX_CHARS,
        len(canonical_answer) + sum(len(row.rendered_literal) for row in expansion_receipts),
    )
    if option_max_chars > ABSOLUTE_OPTION_MAX_CHARS or len(request.candidate_text) > option_max_chars:
        return None

    input_sha256 = _canonical_sha256(_input_payload(request))
    receipt_payload: dict[str, object] = {
        "version": _POLICY,
        "target_id": request.target_id,
        "source_id": source.source_id,
        "source_start": component_start,
        "source_end": component_end,
        "source_sha256": _sha256(source.text),
        "target_sha256": _sha256(request.target_id),
        "component_sha256": _sha256(request.component),
        "candidate_sha256": _sha256(request.candidate_text),
        "input_sha256": input_sha256,
        "canonical_source_answer": canonical_answer,
        "option_max_chars": option_max_chars,
        "premise_projection": premise_projection,
        "ledger": [asdict(row) for row in ledger],
        "literal_expansions": [asdict(row) for row in expansion_receipts],
        "semantic_credit": False,
    }
    return SourceResponseProjection(
        version=_POLICY,
        target_id=request.target_id,
        source_id=source.source_id,
        source_start=component_start,
        source_end=component_end,
        source_sha256=_sha256(source.text),
        target_sha256=_sha256(request.target_id),
        component_sha256=_sha256(request.component),
        candidate_sha256=_sha256(request.candidate_text),
        input_sha256=input_sha256,
        canonical_source_answer=canonical_answer,
        option_max_chars=option_max_chars,
        premise_projection=premise_projection,
        ledger=ledger,
        literal_expansions=expansion_receipts,
        semantic_credit=False,
        receipt_sha256=_canonical_sha256(receipt_payload),
    )


def verify_source_response_projection(
    request: SourceResponseProjectionInput,
    receipt: SourceResponseProjection,
) -> bool:
    """Recompute a receipt from current exact inputs; stale custody never survives."""
    if not isinstance(receipt, SourceResponseProjection) or receipt.semantic_credit is not False:
        return False
    return build_source_response_projection(request) == receipt
