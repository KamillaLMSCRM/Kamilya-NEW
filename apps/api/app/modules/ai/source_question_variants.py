"""Bounded source-literal option variants for neutral assessment questions."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.modules.ai.assessment_preservation import source_edit_noun_signature

MAX_BASE_CHARS = 240
MAX_VARIANTS = 3
MAX_EDIT_TOKENS = 4
MAX_REPLACEMENT_CHARS = 160
_LINE_BREAKS = frozenset("\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029")
_NON_WHITESPACE = re.compile(r"\S+")


@dataclass(frozen=True)
class _Token:
    start: int
    end: int


def _tokens(value: str) -> list[_Token]:
    return [_Token(match.start(), match.end()) for match in _NON_WHITESPACE.finditer(value)]


def _single_line(value: str) -> bool:
    return not any(character in _LINE_BREAKS for character in value)


def _canonical(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


def materialize_source_variants(
    base: str,
    variants: Sequence[Mapping[str, Any]],
    *,
    preserve_nouns: bool = True,
) -> tuple[str, ...]:
    """Return the exact base followed by bounded source-slice replacements."""
    if (
        not isinstance(base, str)
        or not base
        or base != base.strip()
        or len(base) > MAX_BASE_CHARS
        or not _single_line(base)
    ):
        raise ValueError("invalid_source_variant_base")
    if type(preserve_nouns) is not bool:
        raise ValueError("invalid_preserve_nouns")
    if (
        isinstance(variants, str | bytes)
        or not isinstance(variants, Sequence)
        or not 1 <= len(variants) <= MAX_VARIANTS
    ):
        raise ValueError("invalid_source_variants_bounds")

    source_tokens = _tokens(base)
    if not source_tokens:
        raise ValueError("invalid_source_variant_base")
    materialized = [base]
    canonical = {_canonical(base)}
    for variant_index, variant in enumerate(variants):
        if not isinstance(variant, Mapping) or set(variant) != {"token_span", "replacement"}:
            raise ValueError(f"invalid_source_variant_shape:variant={variant_index}")
        token_span = variant["token_span"]
        if not isinstance(token_span, list) or len(token_span) != 2:
            raise ValueError(f"invalid_source_variant_span:variant={variant_index}")
        first, last = token_span
        if any(type(index) is not int for index in (first, last)):
            raise ValueError(f"invalid_source_variant_span:variant={variant_index}")
        if (
            not 1 <= first <= last <= len(source_tokens)
            or last - first + 1 > MAX_EDIT_TOKENS
        ):
            raise ValueError(f"invalid_source_variant_span:variant={variant_index}")

        replacement = variant["replacement"]
        if (
            not isinstance(replacement, str)
            or not replacement
            or replacement != replacement.strip()
            or len(replacement) > MAX_REPLACEMENT_CHARS
            or not _single_line(replacement)
        ):
            raise ValueError(f"invalid_source_variant_replacement:variant={variant_index}")
        replacement_tokens = _tokens(replacement)
        if not 1 <= len(replacement_tokens) <= MAX_EDIT_TOKENS:
            raise ValueError(f"invalid_source_variant_replacement:variant={variant_index}")

        start = source_tokens[first - 1].start
        end = source_tokens[last - 1].end
        if preserve_nouns:
            source_signature = source_edit_noun_signature(base[start:end])
            replacement_signature = source_edit_noun_signature(replacement)
            if source_signature is None or replacement_signature is None:
                raise ValueError(f"unsupported_source_edit_grammar:variant={variant_index}")
            if source_signature != replacement_signature:
                raise ValueError(f"source_noun_entities_changed:variant={variant_index}")

        option = base[:start] + replacement + base[end:]
        if len(option) > MAX_BASE_CHARS:
            raise ValueError(f"source_variant_too_long:variant={variant_index}")
        normalized = _canonical(option)
        if normalized in canonical:
            code = "source_variant_not_distinct" if normalized == _canonical(base) else "duplicate_source_variant"
            raise ValueError(f"{code}:variant={variant_index}")
        canonical.add(normalized)
        materialized.append(option)

    return tuple(materialized)
