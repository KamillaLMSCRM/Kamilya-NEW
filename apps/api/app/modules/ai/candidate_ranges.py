"""Exact candidate token inventories and realization-range resolution."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NoReturn, TypedDict

from app.modules.ai.assessment_components import (
    MAX_ALTERNATIVES,
    MAX_CANDIDATE_SPAN_CHARS,
    MAX_CANDIDATE_TEXT_CHARS,
    MAX_ID_CHARS,
    MAX_REALIZATIONS,
    MAX_ROWS,
    MAX_SOURCE_REF_CHARS,
)

MAX_CANDIDATE_TOKENS = 512

_NON_WHITESPACE = re.compile(r"\S+")
_SOURCE_REF = re.compile(r"^S[1-9]\d*P[1-9]\d*$")
_PART_ROLES = {"stem": "fixed_context", "answer": "discriminating_answer"}


class CandidateToken(TypedDict):
    index: int
    text: str


class CandidateTokenInventory(TypedDict):
    stem: list[CandidateToken]
    options: list[list[CandidateToken]]


@dataclass(frozen=True)
class _Token:
    text: str
    start: int
    end: int


def _tokens(value: str, *, field: str) -> list[_Token]:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > MAX_CANDIDATE_TEXT_CHARS
    ):
        raise ValueError(f"invalid_{field}")
    tokens = [
        _Token(match.group(), match.start(), match.end())
        for match in _NON_WHITESPACE.finditer(value)
    ]
    if not 1 <= len(tokens) <= MAX_CANDIDATE_TOKENS:
        raise ValueError(f"invalid_{field}_token_bounds")
    return tokens


def _inventory(tokens: Sequence[_Token]) -> list[CandidateToken]:
    return [
        {"index": index, "text": token.text}
        for index, token in enumerate(tokens, start=1)
    ]


def _bounded_identifier(value: Any, maximum: int = MAX_ID_CHARS) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and value[0].isalnum()
        and all(character.isalnum() or character in ":._-" for character in value)
    )


def _fail(
    code: str,
    *,
    row: int | None = None,
    realization: int | None = None,
) -> NoReturn:
    location = ""
    if row is not None:
        location += f":row={row}"
    if realization is not None:
        location += f":realization={realization}"
    raise ValueError(f"{code}{location}")


def candidate_token_inventory(
    stem: str,
    options: Sequence[str],
) -> CandidateTokenInventory:
    """Return exact 1-based tokens for the stem and every unmarked option."""

    if (
        isinstance(options, str | bytes)
        or not isinstance(options, Sequence)
        or not 1 <= len(options) <= MAX_ALTERNATIVES
    ):
        raise ValueError("invalid_options_bounds")
    stem_tokens = _tokens(stem, field="stem")
    option_tokens = [
        _tokens(option, field=f"option_{index}")
        for index, option in enumerate(options, start=1)
    ]
    return {
        "stem": _inventory(stem_tokens),
        "options": [_inventory(tokens) for tokens in option_tokens],
    }


def candidate_clause_inventory(options: Sequence[str]) -> list[list[str]]:
    """Key-blind literal locators, not grammatical/source/semantic assertions.

    Only unique maximal semicolon-delimited pieces are offered. Operators stay
    inside their original piece; no new words, completion or offsets are inferred.
    Critics explicitly select a literal from their independently supported option
    using the existing quote protocol. Other candidates keep existing selectors.
    """
    if isinstance(options, str | bytes) or not isinstance(options, Sequence) or not 1 <= len(options) <= MAX_ALTERNATIVES:
        raise ValueError("invalid_options_bounds")
    result = []
    for index, option in enumerate(options):
        _tokens(option, field=f"option_{index}")
        clauses = [part.strip() for part in option.split(";")]
        result.append(clauses if len(clauses) > 1 and all(
            clause and len(clause) <= MAX_CANDIDATE_SPAN_CHARS and option.count(clause) == 1
            for clause in clauses
        ) else [])
    return result


def resolve_candidate_realizations(
    rows: Sequence[Mapping[str, Any]],
    *,
    stem: str,
    answer: str,
) -> list[dict[str, Any]]:
    """Resolve candidate token spans into strict literal realization quotes."""

    if (
        isinstance(rows, str | bytes)
        or not isinstance(rows, Sequence)
        or not 1 <= len(rows) <= MAX_ROWS
    ):
        _fail("invalid_rows_bounds")
    candidate_tokens = {
        "stem": _tokens(stem, field="stem"),
        "answer": _tokens(answer, field="answer"),
    }
    candidate_text = {"stem": stem, "answer": answer}
    resolved_rows: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows):
        if not isinstance(row, Mapping) or set(row) != {
            "target_id",
            "component_id",
            "source_ref",
            "realizations",
        }:
            _fail("invalid_component_mapping_shape", row=row_index)
        target_id = row["target_id"]
        component_id = row["component_id"]
        source_ref = row["source_ref"]
        if not _bounded_identifier(target_id) or not _bounded_identifier(component_id):
            _fail("invalid_component_mapping_ids", row=row_index)
        if (
            not isinstance(source_ref, str)
            or len(source_ref) > MAX_SOURCE_REF_CHARS
            or not _SOURCE_REF.fullmatch(source_ref)
        ):
            _fail("invalid_source_ref", row=row_index)
        realizations = row["realizations"]
        if (
            not isinstance(realizations, list)
            or not 1 <= len(realizations) <= MAX_REALIZATIONS
        ):
            _fail("invalid_component_realizations_bounds", row=row_index)

        resolved_realizations: list[dict[str, Any]] = []
        for realization_index, realization in enumerate(realizations):
            if not isinstance(realization, Mapping):
                _fail(
                    "invalid_realization_shape",
                    row=row_index,
                    realization=realization_index,
                )
            keys = set(realization)
            if keys not in (
                {"part", "role", "token_span"},
                {"part", "role", "whole_part"},
                {"part", "role", "quote"},
                {
                    "part",
                    "role",
                    "quote",
                    "candidate_start",
                    "candidate_end",
                },
            ):
                _fail(
                    "invalid_realization_shape",
                    row=row_index,
                    realization=realization_index,
                )
            part = realization["part"]
            role = realization["role"]
            if not isinstance(part, str) or part not in _PART_ROLES:
                _fail(
                    "invalid_realization_part",
                    row=row_index,
                    realization=realization_index,
                )
            if not isinstance(role, str) or role not in _PART_ROLES.values():
                _fail(
                    "invalid_realization_role",
                    row=row_index,
                    realization=realization_index,
                )
            if _PART_ROLES[part] != role:
                _fail(
                    "realization_role_part_mismatch",
                    row=row_index,
                    realization=realization_index,
                )

            if "whole_part" in realization:
                if realization["whole_part"] is not True:
                    _fail(
                        "invalid_whole_part_selector",
                        row=row_index,
                        realization=realization_index,
                    )
                quote = candidate_text[part]
                candidate_start = 0
                candidate_end = len(quote)
                if len(quote) > MAX_CANDIDATE_SPAN_CHARS:
                    _fail(
                        "resolved_quote_too_long",
                        row=row_index,
                        realization=realization_index,
                    )
            elif "quote" in realization:
                quote = realization["quote"]
                if (
                    not isinstance(quote, str)
                    or not quote.strip()
                    or quote != quote.strip()
                    or len(quote) > MAX_CANDIDATE_SPAN_CHARS
                    or quote not in candidate_text[part]
                ):
                    _fail(
                        "invalid_realization_quote",
                        row=row_index,
                        realization=realization_index,
                    )
                if "candidate_start" in realization:
                    candidate_start = realization["candidate_start"]
                    candidate_end = realization["candidate_end"]
                    if any(
                        not isinstance(offset, int) or isinstance(offset, bool)
                        for offset in (candidate_start, candidate_end)
                    ):
                        _fail(
                            "invalid_candidate_offsets",
                            row=row_index,
                            realization=realization_index,
                        )
                    if (
                        not 0 <= candidate_start < candidate_end <= len(candidate_text[part])
                        or candidate_text[part][candidate_start:candidate_end] != quote
                    ):
                        _fail(
                            "candidate_offsets_quote_mismatch",
                            row=row_index,
                            realization=realization_index,
                        )
                else:
                    candidate_start = candidate_text[part].find(quote)
                    candidate_end = candidate_start + len(quote)
            else:
                token_span = realization["token_span"]
                if not isinstance(token_span, list) or len(token_span) != 2:
                    _fail(
                        "invalid_token_span_shape",
                        row=row_index,
                        realization=realization_index,
                    )
                first, last = token_span
                if any(
                    not isinstance(index, int) or isinstance(index, bool)
                    for index in (first, last)
                ):
                    _fail(
                        "invalid_token_span_index",
                        row=row_index,
                        realization=realization_index,
                    )
                tokens = candidate_tokens[part]
                if not 1 <= first <= last <= len(tokens):
                    _fail(
                        "token_span_out_of_range",
                        row=row_index,
                        realization=realization_index,
                    )
                quote = candidate_text[part][tokens[first - 1].start : tokens[last - 1].end]
                candidate_start = tokens[first - 1].start
                candidate_end = tokens[last - 1].end
                if len(quote) > MAX_CANDIDATE_SPAN_CHARS:
                    _fail(
                        "resolved_quote_too_long",
                        row=row_index,
                        realization=realization_index,
                    )
            resolved_realizations.append(
                {
                    "part": part,
                    "role": role,
                    "quote": quote,
                    "candidate_start": candidate_start,
                    "candidate_end": candidate_end,
                }
            )
        resolved_rows.append(
            {
                "target_id": target_id,
                "component_id": component_id,
                "source_ref": source_ref,
                "realizations": resolved_realizations,
            }
        )
    return resolved_rows
