"""Derive bounded source-edit descriptors from complete literal alternatives."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.ai.source_question_variants import materialize_source_variants

MAX_TEXT_CHARS = 240
MAX_ALTERNATIVES = 3
MAX_EDIT_TOKENS = 4
MAX_FOCUS_REPLACEMENT_CHARS = 160
_LINE_BREAKS = frozenset("\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029")
_NON_WHITESPACE = re.compile(r"\S+")


@dataclass(frozen=True)
class _Token:
    text: str
    start: int
    end: int


def _tokens(value: str) -> list[_Token]:
    return [
        _Token(text=match.group(), start=match.start(), end=match.end())
        for match in _NON_WHITESPACE.finditer(value)
    ]


def _single_line(value: str) -> bool:
    return not any(character in _LINE_BREAKS for character in value)


def _validate_base(base: str) -> None:
    if (
        not isinstance(base, str)
        or not base
        or base != base.strip()
        or len(base) > MAX_TEXT_CHARS
        or not _single_line(base)
    ):
        raise ValueError("invalid_source_alternative_base")


def _bounded_literal_pattern(value: str) -> re.Pattern[str]:
    prefix = r"(?<!\w)" if value[:1].isalnum() else ""
    suffix = r"(?!\w)" if value[-1:].isalnum() else ""
    return re.compile(prefix + re.escape(value) + suffix)


def derive_source_edits(
    base: str,
    alternatives: Sequence[str],
) -> tuple[dict[str, object], ...]:
    """Return exact bounded edits that reconstruct supplied full alternatives."""
    _validate_base(base)
    if (
        isinstance(alternatives, str | bytes)
        or not isinstance(alternatives, Sequence)
        or not 1 <= len(alternatives) <= MAX_ALTERNATIVES
    ):
        raise ValueError("invalid_source_alternatives_bounds")

    base_tokens = _tokens(base)
    if not base_tokens:
        raise ValueError("invalid_source_alternative_base")

    edits: list[dict[str, object]] = []
    for alternative_index, alternative in enumerate(alternatives):
        if (
            not isinstance(alternative, str)
            or not alternative
            or alternative != alternative.strip()
            or len(alternative) > MAX_TEXT_CHARS
            or not _single_line(alternative)
        ):
            raise ValueError(
                f"invalid_source_alternative:alternative={alternative_index}"
            )
        alternative_tokens = _tokens(alternative)
        if not alternative_tokens:
            raise ValueError(
                f"invalid_source_alternative:alternative={alternative_index}"
            )

        prefix_count = 0
        while (
            prefix_count < len(base_tokens)
            and prefix_count < len(alternative_tokens)
            and base_tokens[prefix_count].text == alternative_tokens[prefix_count].text
        ):
            prefix_count += 1

        suffix_count = 0
        while (
            suffix_count < len(base_tokens) - prefix_count
            and suffix_count < len(alternative_tokens) - prefix_count
            and base_tokens[-suffix_count - 1].text
            == alternative_tokens[-suffix_count - 1].text
        ):
            suffix_count += 1

        source_stop = len(base_tokens) - suffix_count
        alternative_stop = len(alternative_tokens) - suffix_count
        source_changed = base_tokens[prefix_count:source_stop]
        alternative_changed = alternative_tokens[prefix_count:alternative_stop]
        if not source_changed and not alternative_changed:
            raise ValueError(
                f"source_alternative_requires_replacement:alternative={alternative_index}"
            )
        if not source_changed or not alternative_changed:
            if suffix_count:
                suffix_count -= 1
            elif prefix_count:
                prefix_count -= 1
            else:
                raise ValueError(
                    f"source_alternative_requires_replacement:alternative={alternative_index}"
                )
            source_stop = len(base_tokens) - suffix_count
            alternative_stop = len(alternative_tokens) - suffix_count
            source_changed = base_tokens[prefix_count:source_stop]
            alternative_changed = alternative_tokens[prefix_count:alternative_stop]
        if (
            len(source_changed) > MAX_EDIT_TOKENS
            or len(alternative_changed) > MAX_EDIT_TOKENS
        ):
            raise ValueError(
                f"source_alternative_edit_too_wide:alternative={alternative_index}"
            )

        source_start = source_changed[0].start
        source_end = source_changed[-1].end
        alternative_start = alternative_changed[0].start
        alternative_end = alternative_changed[-1].end
        if (
            base[:source_start] != alternative[:alternative_start]
            or base[source_end:] != alternative[alternative_end:]
        ):
            raise ValueError(
                f"source_alternative_whitespace_mismatch:alternative={alternative_index}"
            )

        edits.append(
            {
                "token_span": [
                    prefix_count + 1,
                    len(base_tokens) - suffix_count,
                ],
                "replacement": alternative[alternative_start:alternative_end],
            }
        )

    materialized = materialize_source_variants(base, edits, preserve_nouns=True)
    if materialized[1:] != tuple(alternatives):
        raise ValueError("source_alternative_reconstruction_mismatch")
    return tuple(edits)


def project_focus_replacements(
    base: str,
    focus: str,
    replacements: Sequence[str],
) -> tuple[str, ...]:
    """Project bounded replacements into one exact source-owned focus span."""
    _validate_base(base)
    if (
        not isinstance(focus, str)
        or not focus
        or focus != focus.strip()
        or len(focus) > MAX_TEXT_CHARS
        or not _single_line(focus)
    ):
        raise ValueError("invalid_source_alternative_focus")
    focus_matches = tuple(_bounded_literal_pattern(focus).finditer(base))
    if not focus_matches:
        raise ValueError("source_alternative_focus_not_literal")
    if len(focus_matches) != 1:
        raise ValueError("source_alternative_focus_not_unique")
    if (
        isinstance(replacements, str | bytes)
        or not isinstance(replacements, Sequence)
        or not 1 <= len(replacements) <= MAX_ALTERNATIVES
    ):
        raise ValueError("invalid_source_focus_replacements_bounds")

    alternatives: list[str] = []
    focus_match = focus_matches[0]
    for replacement_index, replacement in enumerate(replacements):
        if (
            not isinstance(replacement, str)
            or not replacement
            or replacement != replacement.strip()
            or len(replacement) > MAX_FOCUS_REPLACEMENT_CHARS
            or not _single_line(replacement)
        ):
            raise ValueError(
                f"invalid_source_focus_replacement:replacement={replacement_index}"
            )
        alternatives.append(
            base[: focus_match.start()] + replacement + base[focus_match.end() :]
        )

    derive_source_edits(base, alternatives)
    return tuple(alternatives)
