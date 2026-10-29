"""Immutable, raw-bound custody for reviewed source working editions.

This module compiles proposed editorial replacements, binds an independent
review to that exact proposal, and emits a complete raw-to-working span map.
It never changes the original source and never grants source, semantic, or
assessment approval.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from typing import Literal, cast

from app.modules.ai.source_layout import SOURCE_HORIZONTAL_SPACE

_MAX_SOURCE_CHARS = 262_144
_MAX_PATCHES = 256
_MAX_PATCH_TEXT_CHARS = 2_000
_MAX_REASON_CHARS = 300
_MAX_CONTEXT_QUOTE_CHARS = 2_000
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_WORD_RE = re.compile(r"[^\W\d_]+(?:[-\u2010\u2011][^\W\d_]+)*", re.UNICODE)
_NUMERIC_RE = re.compile(
    rf"[+\-−]?(?:\d{{1,3}}(?:[{re.escape(SOURCE_HORIZONTAL_SPACE)}]\d{{3}})+|\d+)"
    r"(?:[.,]\d+)?"
)
_NUMERIC_OPERATOR_RE = re.compile(r"(?:>=|<=|!=|≥|≤|≠|>|<|=|[+\-−])(?=\s*\d)")
_UNIT_RE = re.compile(rf"[{re.escape(SOURCE_HORIZONTAL_SPACE)}]*(?P<unit>[%‰°²³₸$€₽]|[^\W\d_]+(?:[-\u2010\u2011][^\W\d_]+)*)", re.UNICODE)
_CATEGORIES = frozenset({"grammar", "typo", "layout", "numbering"})
_RELATIONS = frozenset({"preserved", "changed", "unknown"})
_NEGATION_MODAL_IDENTITIES = {
    "не": "не",
    "ни": "ни",
    "без": "без",
    "кроме": "кроме",
    "только": "только",
    "нет": "нет",
    "нельзя": "нельзя",
    "невозможно": "невозможно",
    "должен": "должен",
    "должна": "должен",
    "должно": "должен",
    "должны": "должен",
    "обязан": "обязан",
    "обязана": "обязан",
    "обязано": "обязан",
    "обязаны": "обязан",
    "необходимо": "необходимо",
    "нужно": "нужно",
    "следует": "следует",
    "требуется": "требуется",
    "может": "мочь",
    "могут": "мочь",
    "вправе": "вправе",
    "разрешено": "разрешено",
    "разрешается": "разрешено",
    "запрещено": "запрещено",
    "запрещается": "запрещено",
    "допускается": "допускается",
    "обязательно": "обязательно",
}
_COORDINATION_WORDS = frozenset({"и", "или", "либо", "and", "or", "және", "немесе"})
_REVIEW_AXES = (
    "digits_preserved",
    "numeric_values_preserved",
    "units_preserved",
    "operators_preserved",
    "negation_modality_preserved",
    "coordination_logic_preserved",
    "actors_preserved",
    "content_complete",
    "no_inferred_list_logic",
)
_PATCH_KEYS = frozenset(
    {
        "alias",
        "start",
        "end",
        "before",
        "after",
        "category",
        "reason",
        "supporting_original_context_quotes",
    }
)
_UNRESOLVED_KEYS = frozenset(
    {"alias", "start", "end", "excerpt", "category", "reason"}
)
_REVIEW_ROW_KEYS = frozenset({"patch_alias", "relation", "reason", *_REVIEW_AXES})


@dataclass(frozen=True, slots=True)
class SourceEditorialPatch:
    alias: str
    start: int
    end: int
    before: str
    after: str
    category: Literal["grammar", "typo", "layout", "numbering"]
    reason: str
    supporting_original_context_quotes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceEditorialUnresolved:
    alias: str
    start: int
    end: int
    excerpt: str
    category: Literal["grammar", "typo", "layout", "numbering"]
    reason: str


@dataclass(frozen=True, slots=True)
class SourceEditorialProposal:
    source_id: str
    chunk_id: str
    raw_sha256: str
    patches: tuple[SourceEditorialPatch, ...]
    unresolved: tuple[SourceEditorialUnresolved, ...]
    proposal_sha256: str
    policy: str = "source-editorial-proposal-v1"


@dataclass(frozen=True, slots=True)
class SourceEditorialReviewEvidence:
    patch_alias: str
    relation: Literal["preserved", "changed", "unknown"]
    reason: str
    preservation_axes: tuple[tuple[str, bool], ...]


@dataclass(frozen=True, slots=True)
class SourceEditorialGap:
    alias: str
    start: int
    end: int
    category: str
    code: str
    reason: str


@dataclass(frozen=True, slots=True)
class SourceEditorialSpan:
    raw_start: int
    raw_end: int
    working_start: int
    working_end: int
    origin: Literal["original", "editorial_replacement"]
    patch_alias: str | None


@dataclass(frozen=True, slots=True)
class SourceWorkingEdition:
    source_id: str
    chunk_id: str
    raw_sha256: str
    proposal_sha256: str
    review_sha256: str
    working_text: str
    working_sha256: str
    applied_patch_aliases: tuple[str, ...]
    gaps: tuple[SourceEditorialGap, ...]
    span_map: tuple[SourceEditorialSpan, ...]
    review_rows: tuple[SourceEditorialReviewEvidence, ...]
    receipt_sha256: str
    policy: str = "source-working-edition-v1"
    not_source_or_semantic_approval: bool = True


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _text_digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _bounded_identifier(value: object, code: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 200
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise ValueError(code)
    return value


def _bounded_reason(value: object, code: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or not value.strip()
        or len(value) > _MAX_REASON_CHARS
    ):
        raise ValueError(code)
    return value


def _alias(value: object) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise ValueError("source_editorial_invalid_alias")
    return value


def _source_text(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_SOURCE_CHARS:
        raise ValueError("source_editorial_invalid_source")
    return value


def _numeric_signature(value: str) -> tuple[str, ...]:
    horizontal = frozenset(SOURCE_HORIZONTAL_SPACE)
    return tuple(
        "".join(character for character in match.group(0) if character not in horizontal)
        for match in _NUMERIC_RE.finditer(value)
    )


def _unit_signature(value: str) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    numeric = _numeric_signature(value)
    for index, match in enumerate(_NUMERIC_RE.finditer(value)):
        unit = _UNIT_RE.match(value, match.end())
        if unit is not None:
            rows.append((numeric[index], unit.group("unit").casefold()))
    return tuple(rows)


def _protected_inventory(value: str) -> tuple[object, ...]:
    words = tuple(match.group(0).casefold() for match in _WORD_RE.finditer(value))
    operators = tuple(
        {"≥": ">=", "≤": "<=", "≠": "!=", "−": "-"}.get(
            match.group(0), match.group(0)
        )
        for match in _NUMERIC_OPERATOR_RE.finditer(value)
    )
    return (
        tuple(character for character in value if character.isdigit()),
        _numeric_signature(value),
        _unit_signature(value),
        operators,
        tuple(word for word in words if word in _COORDINATION_WORDS),
    )


def _negation_modal_signature(value: str, counterpart: str) -> tuple[str, ...]:
    tokens = re.findall(r"[^\W\d_]+", value.casefold(), re.UNICODE)
    counterpart_tokens = re.findall(
        r"[^\W\d_]+", counterpart.casefold(), re.UNICODE
    )
    try:
        from app.modules.ai.evidence_engine.provider_engine import (
            _orthographic_negation_view,
        )

        tokens = _orthographic_negation_view(tokens, counterpart_tokens)
    except (ImportError, OSError, RuntimeError, ValueError):
        # A missing dictionary proof is an abstention: raw tokens remain and
        # the ordinary polarity inventory fails closed.
        pass
    return tuple(
        _NEGATION_MODAL_IDENTITIES[word]
        for word in tokens
        if word in _NEGATION_MODAL_IDENTITIES
    )


def _protected_inventories_match(source: str, candidate: str) -> bool:
    return (
        _protected_inventory(source) == _protected_inventory(candidate)
        and _negation_modal_signature(source, candidate)
        == _negation_modal_signature(candidate, source)
    )


def _patch_candidate(source: str, patch: SourceEditorialPatch) -> str:
    return source[: patch.start] + patch.after + source[patch.end :]


def _validate_patch_guard(source: str, patch: SourceEditorialPatch) -> None:
    candidate = _patch_candidate(source, patch)
    if not _protected_inventories_match(source, candidate):
        raise ValueError("source_editorial_protected_inventory_changed")
    if patch.category in {"layout", "numbering"}:
        before_words = tuple(match.group(0) for match in _WORD_RE.finditer(patch.before))
        after_words = tuple(match.group(0) for match in _WORD_RE.finditer(patch.after))
        if before_words != after_words:
            raise ValueError("source_editorial_content_shape_changed")


def _parse_patch(source: str, row: object) -> SourceEditorialPatch:
    if not isinstance(row, Mapping) or set(row) != _PATCH_KEYS:
        raise ValueError("source_editorial_invalid_patch")
    alias = _alias(row.get("alias"))
    start = row.get("start")
    end = row.get("end")
    if (
        type(start) is not int
        or type(end) is not int
        or start < 0
        or end <= start
        or end > len(source)
    ):
        raise ValueError("source_editorial_invalid_patch_bounds")
    before = row.get("before")
    after = row.get("after")
    if (
        not isinstance(before, str)
        or not isinstance(after, str)
        or not before
        or not after
        or before == after
        or max(len(before), len(after)) > _MAX_PATCH_TEXT_CHARS
    ):
        raise ValueError("source_editorial_invalid_patch_text")
    if source[start:end] != before:
        raise ValueError("source_editorial_patch_before_mismatch")
    category = row.get("category")
    if not isinstance(category, str) or category not in _CATEGORIES:
        raise ValueError("source_editorial_invalid_patch_category")
    reason = _bounded_reason(row.get("reason"), "source_editorial_invalid_patch_reason")
    raw_quotes = row.get("supporting_original_context_quotes")
    if (
        not isinstance(raw_quotes, Sequence)
        or isinstance(raw_quotes, str | bytes)
        or not 1 <= len(raw_quotes) <= 4
    ):
        raise ValueError("source_editorial_invalid_context_quote")
    quotes: list[str] = []
    seen_quotes: set[str] = set()
    encloses_patch = False
    for quote in raw_quotes:
        if (
            not isinstance(quote, str)
            or not quote
            or len(quote) > _MAX_CONTEXT_QUOTE_CHARS
            or source.count(quote) != 1
            or quote in seen_quotes
        ):
            raise ValueError("source_editorial_invalid_context_quote")
        seen_quotes.add(quote)
        quote_start = source.index(quote)
        encloses_patch = encloses_patch or (
            quote_start <= start and quote_start + len(quote) >= end
        )
        quotes.append(quote)
    if not encloses_patch:
        raise ValueError("source_editorial_invalid_context_quote")
    patch = SourceEditorialPatch(
        alias=alias,
        start=start,
        end=end,
        before=before,
        after=after,
        category=cast(Literal["grammar", "typo", "layout", "numbering"], category),
        reason=reason,
        supporting_original_context_quotes=tuple(quotes),
    )
    _validate_patch_guard(source, patch)
    return patch


def _parse_unresolved(source: str, row: object) -> SourceEditorialUnresolved:
    if not isinstance(row, Mapping) or set(row) != _UNRESOLVED_KEYS:
        raise ValueError("source_editorial_invalid_unresolved")
    alias = _alias(row.get("alias"))
    start = row.get("start")
    end = row.get("end")
    excerpt = row.get("excerpt")
    if (
        type(start) is not int
        or type(end) is not int
        or start < 0
        or end <= start
        or end > len(source)
        or not isinstance(excerpt, str)
        or not excerpt
        or source[start:end] != excerpt
    ):
        raise ValueError("source_editorial_invalid_unresolved_span")
    category = row.get("category")
    if not isinstance(category, str) or category not in _CATEGORIES:
        raise ValueError("source_editorial_invalid_unresolved_category")
    return SourceEditorialUnresolved(
        alias=alias,
        start=start,
        end=end,
        excerpt=excerpt,
        category=cast(Literal["grammar", "typo", "layout", "numbering"], category),
        reason=_bounded_reason(
            row.get("reason"), "source_editorial_invalid_unresolved_reason"
        ),
    )


def _proposal_payload(
    source_id: str,
    chunk_id: str,
    raw_sha256: str,
    patches: tuple[SourceEditorialPatch, ...],
    unresolved: tuple[SourceEditorialUnresolved, ...],
    policy: str,
) -> dict[str, object]:
    return {
        "source_id": source_id,
        "chunk_id": chunk_id,
        "raw_sha256": raw_sha256,
        "patches": [asdict(patch) for patch in patches],
        "unresolved": [asdict(gap) for gap in unresolved],
        "policy": policy,
    }


def compile_source_editorial_proposal(
    source_text: str,
    *,
    source_id: str,
    chunk_id: str,
    patches: Sequence[Mapping[str, object]],
    unresolved: Sequence[Mapping[str, object]] = (),
) -> SourceEditorialProposal:
    """Validate and hash proposed exact replacements against immutable source."""
    source = _source_text(source_text)
    checked_source_id = _bounded_identifier(source_id, "source_editorial_invalid_source_id")
    checked_chunk_id = _bounded_identifier(chunk_id, "source_editorial_invalid_chunk_id")
    if (
        not isinstance(patches, Sequence)
        or isinstance(patches, str | bytes)
        or len(patches) > _MAX_PATCHES
        or not isinstance(unresolved, Sequence)
        or isinstance(unresolved, str | bytes)
        or len(unresolved) > _MAX_PATCHES
    ):
        raise ValueError("source_editorial_invalid_inventory")
    parsed_patches = tuple(
        sorted(
            (_parse_patch(source, row) for row in patches),
            key=lambda row: (row.start, row.end, row.alias),
        )
    )
    parsed_unresolved = tuple(
        sorted(
            (_parse_unresolved(source, row) for row in unresolved),
            key=lambda row: (row.start, row.end, row.alias),
        )
    )
    aliases = [row.alias for row in parsed_patches]
    aliases.extend(row.alias for row in parsed_unresolved)
    if len(aliases) != len(set(aliases)):
        raise ValueError("source_editorial_duplicate_alias")
    for previous, current in zip(parsed_patches, parsed_patches[1:], strict=False):
        if current.start < previous.end:
            raise ValueError("source_editorial_overlapping_patches")
    candidate = source
    for patch in reversed(parsed_patches):
        candidate = candidate[: patch.start] + patch.after + candidate[patch.end :]
    if not _protected_inventories_match(source, candidate):
        raise ValueError("source_editorial_protected_inventory_changed")
    policy = "source-editorial-proposal-v1"
    raw_sha256 = _text_digest(source)
    payload = _proposal_payload(
        checked_source_id,
        checked_chunk_id,
        raw_sha256,
        parsed_patches,
        parsed_unresolved,
        policy,
    )
    return SourceEditorialProposal(
        source_id=checked_source_id,
        chunk_id=checked_chunk_id,
        raw_sha256=raw_sha256,
        patches=parsed_patches,
        unresolved=parsed_unresolved,
        proposal_sha256=_digest(payload),
        policy=policy,
    )


def _recompile_proposal(source: str, proposal: SourceEditorialProposal) -> SourceEditorialProposal:
    if not isinstance(proposal, SourceEditorialProposal):
        raise ValueError("source_editorial_invalid_proposal")
    try:
        rebuilt = compile_source_editorial_proposal(
            source,
            source_id=proposal.source_id,
            chunk_id=proposal.chunk_id,
            patches=[asdict(patch) for patch in proposal.patches],
            unresolved=[asdict(gap) for gap in proposal.unresolved],
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("source_editorial_invalid_proposal") from exc
    if rebuilt != proposal:
        raise ValueError("source_editorial_invalid_proposal")
    return rebuilt


def _parse_review(
    proposal: SourceEditorialProposal,
    review_wire: object,
) -> tuple[tuple[SourceEditorialReviewEvidence, ...], str]:
    if not isinstance(review_wire, Mapping) or set(review_wire) != {"proposal_sha256", "rows"}:
        raise ValueError("source_editorial_invalid_review_shape")
    if review_wire.get("proposal_sha256") != proposal.proposal_sha256:
        raise ValueError("source_editorial_invalid_review_binding")
    raw_rows = review_wire.get("rows")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, str | bytes):
        raise ValueError("source_editorial_invalid_review_inventory")
    by_alias: dict[str, SourceEditorialReviewEvidence] = {}
    for raw_row in raw_rows:
        if not isinstance(raw_row, Mapping) or set(raw_row) != _REVIEW_ROW_KEYS:
            raise ValueError("source_editorial_invalid_review_row")
        alias = raw_row.get("patch_alias")
        relation = raw_row.get("relation")
        if (
            not isinstance(alias, str)
            or alias in by_alias
            or not isinstance(relation, str)
            or relation not in _RELATIONS
        ):
            raise ValueError("source_editorial_invalid_review_row")
        axes: list[tuple[str, bool]] = []
        for axis in _REVIEW_AXES:
            value = raw_row.get(axis)
            if type(value) is not bool:
                raise ValueError("source_editorial_invalid_review_row")
            axes.append((axis, value))
        by_alias[alias] = SourceEditorialReviewEvidence(
            patch_alias=alias,
            relation=cast(Literal["preserved", "changed", "unknown"], relation),
            reason=_bounded_reason(
                raw_row.get("reason"), "source_editorial_invalid_review_row"
            ),
            preservation_axes=tuple(axes),
        )
    expected = tuple(patch.alias for patch in proposal.patches)
    if set(by_alias) != set(expected) or len(by_alias) != len(expected):
        raise ValueError("source_editorial_invalid_review_inventory")
    rows = tuple(by_alias[alias] for alias in expected)
    review_sha256 = _digest(
        {
            "proposal_sha256": proposal.proposal_sha256,
            "rows": [asdict(row) for row in rows],
        }
    )
    return rows, review_sha256


def _span_map(
    source: str,
    working: str,
    patches: tuple[SourceEditorialPatch, ...],
) -> tuple[SourceEditorialSpan, ...]:
    spans: list[SourceEditorialSpan] = []
    raw_cursor = 0
    working_cursor = 0
    for patch in patches:
        if raw_cursor < patch.start:
            length = patch.start - raw_cursor
            spans.append(
                SourceEditorialSpan(
                    raw_start=raw_cursor,
                    raw_end=patch.start,
                    working_start=working_cursor,
                    working_end=working_cursor + length,
                    origin="original",
                    patch_alias=None,
                )
            )
            working_cursor += length
        spans.append(
            SourceEditorialSpan(
                raw_start=patch.start,
                raw_end=patch.end,
                working_start=working_cursor,
                working_end=working_cursor + len(patch.after),
                origin="editorial_replacement",
                patch_alias=patch.alias,
            )
        )
        raw_cursor = patch.end
        working_cursor += len(patch.after)
    if raw_cursor < len(source):
        length = len(source) - raw_cursor
        spans.append(
            SourceEditorialSpan(
                raw_start=raw_cursor,
                raw_end=len(source),
                working_start=working_cursor,
                working_end=working_cursor + length,
                origin="original",
                patch_alias=None,
            )
        )
    if not spans or spans[-1].working_end != len(working):
        raise ValueError("source_editorial_invalid_span_map")
    return tuple(spans)


def _edition_payload(edition: SourceWorkingEdition) -> dict[str, object]:
    payload = asdict(edition)
    payload.pop("receipt_sha256")
    return payload


def apply_source_editorial_review(
    source_text: str,
    proposal: SourceEditorialProposal,
    review_wire: Mapping[str, object],
) -> SourceWorkingEdition:
    """Apply only independently preserved patches and retain every other gap."""
    source = _source_text(source_text)
    if _text_digest(source) != getattr(proposal, "raw_sha256", None):
        raise ValueError("source_editorial_source_mismatch")
    checked = _recompile_proposal(source, proposal)
    review_rows, review_sha256 = _parse_review(checked, review_wire)
    row_by_alias = {row.patch_alias: row for row in review_rows}
    applied: list[SourceEditorialPatch] = []
    gaps: list[SourceEditorialGap] = []
    for patch in checked.patches:
        review = row_by_alias[patch.alias]
        axes_proved = all(value is True for _, value in review.preservation_axes)
        if review.relation == "preserved" and axes_proved:
            applied.append(patch)
            continue
        code = (
            f"source_editorial_review_{review.relation}"
            if review.relation != "preserved"
            else "source_editorial_review_preservation_unproved"
        )
        gaps.append(
            SourceEditorialGap(
                alias=patch.alias,
                start=patch.start,
                end=patch.end,
                category=patch.category,
                code=code,
                reason=review.reason,
            )
        )
    gaps.extend(
        SourceEditorialGap(
            alias=gap.alias,
            start=gap.start,
            end=gap.end,
            category=gap.category,
            code="source_editorial_unresolved_original",
            reason=gap.reason,
        )
        for gap in checked.unresolved
    )
    working = source
    for patch in reversed(applied):
        working = working[: patch.start] + patch.after + working[patch.end :]
    if not _protected_inventories_match(source, working):
        raise ValueError("source_editorial_protected_inventory_changed")
    edition = SourceWorkingEdition(
        source_id=checked.source_id,
        chunk_id=checked.chunk_id,
        raw_sha256=checked.raw_sha256,
        proposal_sha256=checked.proposal_sha256,
        review_sha256=review_sha256,
        working_text=working,
        working_sha256=_text_digest(working),
        applied_patch_aliases=tuple(patch.alias for patch in applied),
        gaps=tuple(sorted(gaps, key=lambda gap: (gap.start, gap.end, gap.alias))),
        span_map=_span_map(source, working, tuple(applied)),
        review_rows=review_rows,
        receipt_sha256="",
    )
    return replace(edition, receipt_sha256=_digest(_edition_payload(edition)))


def source_working_edition_valid(
    edition: SourceWorkingEdition,
    *,
    source_text: str,
    proposal: SourceEditorialProposal,
    review_wire: Mapping[str, object],
) -> bool:
    """Rederive the complete receipt from immutable inputs; never infer trust."""
    if not isinstance(edition, SourceWorkingEdition):
        return False
    try:
        rebuilt = apply_source_editorial_review(source_text, proposal, review_wire)
    except (TypeError, ValueError):
        return False
    return rebuilt == edition
