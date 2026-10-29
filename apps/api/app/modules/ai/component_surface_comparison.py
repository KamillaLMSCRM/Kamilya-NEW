"""Raw-bound whole-component surface comparison with zero semantic credit.

The source component, source context, learner container, and offsets remain the
authoritative bytes.  This module may compile only a closed formatting or
dictionary-grammar receipt; it never chooses an answer, target, key, or truth.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal, cast

from app.modules.ai.assessment_facets import BRANCH_EFFECTS, FACET_ROLES
from app.modules.ai.assessment_preservation import (
    MAX_SOURCE_CONTEXT_CHARS,
    MAX_TEXT_CHARS,
    SourceGrammarRealizationReceipt,
    _word_info,
    canonical_option_typography,
    source_grammar_realization_comparison_view,
    source_grammar_realization_receipts,
    unsupported_option_spacing,
)
from app.modules.ai.lesson_surface_grammar import (
    LessonSurfaceGrammarOperation,
    prose_grammar_comparison_view,
)
from app.modules.ai.source_layout import SOURCE_HORIZONTAL_SPACE

WHOLE_COMPONENT_COMPARISON_POLICY = "whole-component-surface-comparison-v1"
_BINDING_KEYS = frozenset(
    {
        "facet_id",
        "source_id",
        "quote",
        "role",
        "branch_effect",
        "quote_start",
        "quote_end",
    }
)
_FORMAT_RECEIPT_FAMILIES = frozenset(
    {
        "initial_cyrillic_capitalization",
        "source_horizontal_typography",
    }
)
_PROSE_OPERATION_CODES = frozenset({"animate_hyphen_apposition_agreement"})
_LEXICAL_HYPHENS = frozenset({"-", "‐", "‑"})
_NUMERIC_ATTACHMENTS = frozenset({"+", "−", "±", "≤", "≥", "<", ">", "="})
_CYRILLIC_WORD = re.compile(r"[А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]{2,}(?![\w-])")
_NUMERIC_TOKEN = re.compile(
    rf"[+\-−]?(?:\d{{1,3}}(?:[{re.escape(SOURCE_HORIZONTAL_SPACE)}]\d{{3}})+|\d+)(?:[.,]\d+)?"
)


@dataclass(frozen=True, slots=True)
class ComponentSurfaceFormatOperation:
    """One exact comparison-only formatting change on an immutable side."""

    side: Literal["source", "candidate"]
    family: Literal["horizontal_space", "initial_cyrillic_case"]
    start: int
    end: int
    before_sha256: str
    after_sha256: str


@dataclass(frozen=True, slots=True)
class WholeComponentComparisonReceipt:
    """Closed custody for one complete source component and learner quote."""

    policy: str
    family: Literal["exact", "format", "prose_grammar"]
    source_id: str
    source_context_sha256: str
    source_start: int
    source_end: int
    component_sha256: str
    candidate_container_sha256: str
    candidate_start: int
    candidate_end: int
    candidate_quote_sha256: str
    comparison_sha256: str
    governing_bindings_sha256: str
    source_grammar_receipts: tuple[SourceGrammarRealizationReceipt, ...]
    format_operations: tuple[ComponentSurfaceFormatOperation, ...]
    prose_operations: tuple[LessonSurfaceGrammarOperation, ...]
    binding_sha256: str
    not_semantic_approval: bool = True


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _lexical_character(value: str) -> bool:
    return value.isalnum() or value == "_" or value in _LEXICAL_HYPHENS


def _unique_exact_start(container: str, value: str) -> int | None:
    start = container.find(value)
    if start < 0 or container.find(value, start + 1) >= 0:
        return None
    return start


def lexical_span_is_complete(text: str, start: int, end: int) -> bool:
    """Return whether an exact span does not cut a lexical or signed token.

    Punctuation outside this closed set remains a delimiter.  In particular,
    line punctuation is not normalized and no semantic tokenization is inferred.
    """

    if not isinstance(text, str) or type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
        return False
    if start and _lexical_character(text[start - 1]) and _lexical_character(text[start]):
        return False
    if end < len(text) and _lexical_character(text[end - 1]) and _lexical_character(text[end]):
        return False
    if text[start].isdigit() and start and text[start - 1] in _NUMERIC_ATTACHMENTS:
        return False
    if text[end - 1].isdigit() and end < len(text) and text[end] in _NUMERIC_ATTACHMENTS:
        return False
    for numeric in _NUMERIC_TOKEN.finditer(text):
        if start < numeric.end() and numeric.start() < end and not (
            start <= numeric.start() and numeric.end() <= end
        ):
            return False
    return True


def _validated_bindings(
    value: Sequence[dict[str, object]],
    *,
    source_context: str,
    source_id: str,
) -> tuple[tuple[dict[str, object], ...], str] | None:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return None
    rows: list[dict[str, object]] = []
    identities: set[tuple[object, ...]] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != _BINDING_KEYS:
            return None
        facet_id = raw.get("facet_id")
        owner = raw.get("source_id")
        quote = raw.get("quote")
        role = raw.get("role")
        effect = raw.get("branch_effect")
        start = raw.get("quote_start")
        end = raw.get("quote_end")
        if (
            not all(
                isinstance(item, str) and item
                for item in (
                    facet_id,
                    owner,
                    quote,
                    role,
                    effect,
                )
            )
            or owner != source_id
            or role not in FACET_ROLES
            or effect not in BRANCH_EFFECTS
            or type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= len(source_context)
            or source_context[start:end] != quote
            or _unique_exact_start(source_context, quote) != start
            or not lexical_span_is_complete(source_context, start, end)
        ):
            return None
        identity = tuple(raw[key] for key in sorted(_BINDING_KEYS))
        if identity in identities:
            return None
        identities.add(identity)
        rows.append(dict(raw))
    rows.sort(
        key=lambda row: (
            str(row["facet_id"]),
            cast(int, row["quote_start"]),
            str(row["quote"]),
        )
    )
    frozen = tuple(rows)
    return frozen, _digest(frozen)


def _ordinary_initial_cyrillic_word(value: str) -> bool:
    match = _CYRILLIC_WORD.match(value)
    if match is None:
        return False
    word = match.group()
    if word.isupper():
        return False
    try:
        info = _word_info(word.casefold())
    except (ImportError, OSError, RuntimeError, ValueError):
        return False
    return bool(info.known and info.parts_of_speech)


def _format_view(
    source: str,
    candidate: str,
) -> tuple[str, tuple[ComponentSurfaceFormatOperation, ...]] | None:
    if unsupported_option_spacing(source) or unsupported_option_spacing(candidate):
        return None
    source_display = canonical_option_typography(source)
    candidate_display = canonical_option_typography(candidate)
    operations: list[ComponentSurfaceFormatOperation] = []
    if source_display != source:
        operations.append(
            ComponentSurfaceFormatOperation(
                "source",
                "horizontal_space",
                0,
                len(source),
                _text_sha256(source),
                _text_sha256(source_display),
            )
        )
    if candidate_display != candidate:
        operations.append(
            ComponentSurfaceFormatOperation(
                "candidate",
                "horizontal_space",
                0,
                len(candidate),
                _text_sha256(candidate),
                _text_sha256(candidate_display),
            )
        )
    if source_display == candidate_display:
        return source_display, tuple(operations)
    if (
        len(source_display) != len(candidate_display)
        or source_display[1:] != candidate_display[1:]
        or source_display[0].casefold() != candidate_display[0].casefold()
        or source_display[0] == candidate_display[0]
        or not _ordinary_initial_cyrillic_word(source_display)
        or not _ordinary_initial_cyrillic_word(candidate_display)
    ):
        return None
    # Lower both first letters solely for a stable comparison hash.  The raw
    # source and learner bytes remain in the receipt through their own hashes.
    source_comparison = source_display[0].lower() + source_display[1:]
    candidate_comparison = candidate_display[0].lower() + candidate_display[1:]
    if source_comparison != candidate_comparison:
        return None
    if source_display[0] != source_comparison[0]:
        operations.append(
            ComponentSurfaceFormatOperation(
                "source",
                "initial_cyrillic_case",
                0,
                1,
                _text_sha256(source_display[0]),
                _text_sha256(source_comparison[0]),
            )
        )
    if candidate_display[0] != candidate_comparison[0]:
        operations.append(
            ComponentSurfaceFormatOperation(
                "candidate",
                "initial_cyrillic_case",
                0,
                1,
                _text_sha256(candidate_display[0]),
                _text_sha256(candidate_comparison[0]),
            )
        )
    return source_comparison, tuple(operations)


def _comparison(
    component: str,
    candidate_quote: str,
    *,
    source_context: str,
    source_id: str,
    bindings: tuple[dict[str, object], ...],
) -> (
    tuple[
        Literal["exact", "format", "prose_grammar"],
        str,
        tuple[SourceGrammarRealizationReceipt, ...],
        tuple[ComponentSurfaceFormatOperation, ...],
        tuple[LessonSurfaceGrammarOperation, ...],
    ]
    | None
):
    if component == candidate_quote:
        return "exact", component, (), (), ()

    receipts = source_grammar_realization_receipts(
        component,
        candidate_quote,
        source_context=source_context,
        source_id=source_id,
        verified_governing_bindings=bindings,
    )
    for receipt in receipts:
        if receipt.family not in _FORMAT_RECEIPT_FAMILIES:
            continue
        view = source_grammar_realization_comparison_view(
            receipt,
            component,
            candidate_quote,
            source_context=source_context,
            source_id=source_id,
            verified_governing_bindings=bindings,
        )
        if view is not None and view.comparison_component == candidate_quote:
            return "format", candidate_quote, (receipt,), (), ()

    formatted = _format_view(component, candidate_quote)
    if formatted is not None:
        comparison, operations = formatted
        if operations:
            return "format", comparison, (), operations, ()

    try:
        prose = prose_grammar_comparison_view(component)
    except (ImportError, OSError, RuntimeError, ValueError):
        return None
    if (
        not prose.operations
        or any(operation.code not in _PROSE_OPERATION_CODES for operation in prose.operations)
        or prose.raw_sha256 != _text_sha256(component)
    ):
        return None
    formatted = _format_view(prose.text, candidate_quote)
    if formatted is None:
        return None
    comparison, operations = formatted
    return "prose_grammar", comparison, (), operations, prose.operations


def bind_whole_component_comparison(
    component: str,
    candidate_quote: str,
    *,
    source_context: str,
    source_id: str,
    verified_governing_bindings: Sequence[dict[str, object]],
    candidate_container: str,
    candidate_start: int,
    candidate_end: int,
) -> WholeComponentComparisonReceipt | None:
    """Bind one complete raw component to one complete raw learner quote."""

    if (
        not all(
            isinstance(value, str) and value
            for value in (
                component,
                candidate_quote,
                source_context,
                source_id,
                candidate_container,
            )
        )
        or component != component.strip()
        or candidate_quote != candidate_quote.strip()
        or source_id != source_id.strip()
        or len(component) > MAX_TEXT_CHARS
        or len(candidate_quote) > MAX_TEXT_CHARS
        or len(source_context) > MAX_SOURCE_CONTEXT_CHARS
        or len(candidate_container) > MAX_SOURCE_CONTEXT_CHARS
        or type(candidate_start) is not int
        or type(candidate_end) is not int
        or not 0 <= candidate_start < candidate_end <= len(candidate_container)
        or candidate_container[candidate_start:candidate_end] != candidate_quote
        or _unique_exact_start(candidate_container, candidate_quote) != candidate_start
        or not lexical_span_is_complete(candidate_container, candidate_start, candidate_end)
    ):
        return None
    source_start = _unique_exact_start(source_context, component)
    if source_start is None:
        return None
    source_end = source_start + len(component)
    if not lexical_span_is_complete(source_context, source_start, source_end):
        return None
    validated = _validated_bindings(
        verified_governing_bindings,
        source_context=source_context,
        source_id=source_id,
    )
    if validated is None:
        return None
    bindings, bindings_sha256 = validated
    comparison = _comparison(
        component,
        candidate_quote,
        source_context=source_context,
        source_id=source_id,
        bindings=bindings,
    )
    if comparison is None:
        return None
    family, comparison_text, source_receipts, format_operations, prose_operations = comparison
    source_context_sha256 = _text_sha256(source_context)
    component_sha256 = _text_sha256(component)
    candidate_container_sha256 = _text_sha256(candidate_container)
    candidate_quote_sha256 = _text_sha256(candidate_quote)
    comparison_sha256 = _text_sha256(comparison_text)
    body = {
        "policy": WHOLE_COMPONENT_COMPARISON_POLICY,
        "family": family,
        "source_id": source_id,
        "source_context_sha256": source_context_sha256,
        "source_start": source_start,
        "source_end": source_end,
        "component_sha256": component_sha256,
        "candidate_container_sha256": candidate_container_sha256,
        "candidate_start": candidate_start,
        "candidate_end": candidate_end,
        "candidate_quote_sha256": candidate_quote_sha256,
        "comparison_sha256": comparison_sha256,
        "governing_bindings_sha256": bindings_sha256,
        "source_grammar_receipts": [asdict(row) for row in source_receipts],
        "format_operations": [asdict(row) for row in format_operations],
        "prose_operations": [asdict(row) for row in prose_operations],
        "not_semantic_approval": True,
    }
    return WholeComponentComparisonReceipt(
        policy=WHOLE_COMPONENT_COMPARISON_POLICY,
        family=family,
        source_id=source_id,
        source_context_sha256=source_context_sha256,
        source_start=source_start,
        source_end=source_end,
        component_sha256=component_sha256,
        candidate_container_sha256=candidate_container_sha256,
        candidate_start=candidate_start,
        candidate_end=candidate_end,
        candidate_quote_sha256=candidate_quote_sha256,
        comparison_sha256=comparison_sha256,
        governing_bindings_sha256=bindings_sha256,
        source_grammar_receipts=source_receipts,
        format_operations=format_operations,
        prose_operations=prose_operations,
        binding_sha256=_digest(body),
    )


def whole_component_comparison_receipt_valid(
    receipt: WholeComponentComparisonReceipt,
    component: str,
    candidate_quote: str,
    *,
    source_context: str,
    source_id: str,
    verified_governing_bindings: Sequence[dict[str, object]],
    candidate_container: str,
    candidate_start: int,
    candidate_end: int,
) -> bool:
    """Recompute the complete receipt; stale evidence receives no partial use."""

    if not isinstance(receipt, WholeComponentComparisonReceipt):
        return False
    rebound = bind_whole_component_comparison(
        component,
        candidate_quote,
        source_context=source_context,
        source_id=source_id,
        verified_governing_bindings=verified_governing_bindings,
        candidate_container=candidate_container,
        candidate_start=candidate_start,
        candidate_end=candidate_end,
    )
    return rebound is not None and rebound == receipt


__all__ = [
    "ComponentSurfaceFormatOperation",
    "WHOLE_COMPONENT_COMPARISON_POLICY",
    "WholeComponentComparisonReceipt",
    "bind_whole_component_comparison",
    "lexical_span_is_complete",
    "whole_component_comparison_receipt_valid",
]
