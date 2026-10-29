"""Structural validation for requirement-fulfillment option receipts.

This module deliberately validates shape and explicit bindings only.  It does
not create receipts or infer whether an option is substantively true.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Literal

INTENT = "requirement_fulfillment"
INSTRUCTION = (
    "Каждый вариант — полный план действий для указанной проверки. "
    "Выберите план, полностью выполняющий требование."
)

_ROW_KEYS = {"index", "relation", "component_id", "source_ref", "reason"}
_RELATIONS = {"fulfilled", "not_fulfilled"}
_CONDITION_ROW_KEYS = {"source_ref", "condition_quote", "inactive_options"}
_INACTIVE_OPTION_KEYS = {"index", "relation", "reason"}
_COVERAGE_ROW_KEYS = {"source_ref", "source_quote", "options"}
_COVERAGE_OPTION_KEYS = {"index", "relation", "option_quote", "reason"}
_COVERAGE_RELATIONS = {"covered", "omitted", "unknown"}
_MAIN_RELATIONS = {"fulfilled", "not_fulfilled", "unknown"}
_MAX_COVERAGE_ROWS = 24
_WORD_TOKEN = re.compile(r"\w+", re.UNICODE)


def positive_relation(intent: object) -> str:
    """Return the positive relation for the requested intent."""
    return "fulfilled" if intent == INTENT else "supported"


def negative_relation(intent: object) -> str:
    """Return the negative relation for the requested intent."""
    return "not_fulfilled" if intent == INTENT else "contradicted"


def _plain_int(value: object) -> bool:
    return type(value) is int


def coverage_issue(
    rows: object,
    *,
    component_id: str,
    source_refs: set[str],
    component_text: str,
    options: tuple[str, ...],
    option_relations: Mapping[int, str],
) -> None | Literal["format", "semantic"]:
    """Validate symmetric source-to-option coverage evidence.

    The receipt proves only that the critic supplied complete, source-bound
    evidence consistent with its main relation vector.  Literal spans are not
    semantic entailment and this function does not approve an answer or infer a
    key.
    """
    try:
        if not isinstance(component_id, str) or not component_id:
            return "format"
        if (
            type(source_refs) is not set
            or not source_refs
            or any(not isinstance(source_ref, str) or not source_ref for source_ref in source_refs)
        ):
            return "format"
        if not isinstance(component_text, str) or not component_text:
            return "format"
        if (
            type(options) is not tuple
            or not options
            or any(not isinstance(option, str) or not option for option in options)
        ):
            return "format"
        if not isinstance(option_relations, Mapping):
            return "format"

        expected_indices = set(range(len(options)))
        if (
            any(not _plain_int(index) for index in option_relations)
            or set(option_relations) != expected_indices
            or any(relation not in _MAIN_RELATIONS for relation in option_relations.values())
        ):
            return "format"
        if not isinstance(rows, list) or not 1 <= len(rows) <= _MAX_COVERAGE_ROWS:
            return "format"

        source_coverage = [False] * len(component_text)
        seen_quotes: set[str] = set()
        coverage_relations: dict[int, list[str]] = {index: [] for index in expected_indices}
        for row in rows:
            if not isinstance(row, Mapping) or set(row) != _COVERAGE_ROW_KEYS:
                return "format"
            source_ref = row["source_ref"]
            source_quote = row["source_quote"]
            if source_ref not in source_refs or not isinstance(source_ref, str):
                return "format"
            if not isinstance(source_quote, str) or not source_quote or source_quote in seen_quotes:
                return "format"
            quote_start = component_text.find(source_quote)
            if quote_start < 0 or component_text.find(source_quote, quote_start + 1) >= 0:
                return "format"
            seen_quotes.add(source_quote)
            for offset in range(quote_start, quote_start + len(source_quote)):
                source_coverage[offset] = True

            option_rows = row["options"]
            if not isinstance(option_rows, list) or len(option_rows) != len(options):
                return "format"
            seen_indices: set[int] = set()
            for option_row in option_rows:
                if not isinstance(option_row, Mapping) or set(option_row) != _COVERAGE_OPTION_KEYS:
                    return "format"
                index = option_row["index"]
                relation = option_row["relation"]
                option_quote = option_row["option_quote"]
                reason = option_row["reason"]
                if not _plain_int(index) or index not in expected_indices or index in seen_indices:
                    return "format"
                seen_indices.add(index)
                if relation not in _COVERAGE_RELATIONS:
                    return "format"
                if not isinstance(option_quote, str):
                    return "format"
                if relation == "covered":
                    if not option_quote.strip() or option_quote not in options[index]:
                        return "format"
                elif option_quote != "":
                    return "format"
                if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
                    return "format"
                coverage_relations[index].append(relation)
            if seen_indices != expected_indices:
                return "format"

        if any(
            not all(source_coverage[offset] for offset in range(match.start(), match.end()))
            for match in _WORD_TOKEN.finditer(component_text)
        ):
            return "format"

        expected_relations: dict[int, str] = {}
        for index, relations in coverage_relations.items():
            if all(relation == "covered" for relation in relations):
                expected_relations[index] = "fulfilled"
            elif any(relation == "omitted" for relation in relations):
                expected_relations[index] = "not_fulfilled"
            else:
                expected_relations[index] = "unknown"
        return "semantic" if dict(option_relations) != expected_relations else None
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return "format"


def validate_receipt(
    rows: object,
    *,
    option_count: int,
    key: int,
    component_refs: Mapping[str, set[str]],
    option_relations: Mapping[int, str],
) -> bool:
    """Validate a receipt's explicit structural contract.

    Invalid ordinary input is rejected as ``False``.  No text or relation
    meaning is inferred here; every relation must be supplied by the caller
    and match the keyed option contract.
    """
    try:
        if not _plain_int(option_count) or option_count < 1:
            return False
        if not _plain_int(key) or not 0 <= key < option_count:
            return False
        if not isinstance(rows, list | tuple) or len(rows) != option_count:
            return False
        if not isinstance(component_refs, Mapping) or len(component_refs) != 1:
            return False
        if not isinstance(option_relations, Mapping):
            return False

        component_id, source_refs = next(iter(component_refs.items()))
        if (
            not isinstance(component_id, str)
            or not component_id
            or type(source_refs) is not set
            or not source_refs
            or any(not isinstance(source_ref, str) or not source_ref for source_ref in source_refs)
        ):
            return False

        expected_keys = set(range(option_count))
        if any(not _plain_int(index) for index in option_relations) or set(option_relations) != expected_keys:
            return False
        expected_relations = {
            index: ("fulfilled" if index == key else "not_fulfilled")
            for index in range(option_count)
        }
        if dict(option_relations) != expected_relations:
            return False

        seen_indices: set[int] = set()
        for row in rows:
            if not isinstance(row, Mapping) or set(row) != _ROW_KEYS:
                return False
            index = row["index"]
            relation = row["relation"]
            if not _plain_int(index) or index not in expected_keys or index in seen_indices:
                return False
            seen_indices.add(index)
            if relation not in _RELATIONS or relation != option_relations[index]:
                return False
            if row["component_id"] != component_id:
                return False
            if row["source_ref"] not in source_refs:
                return False
            reason = row["reason"]
            if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
                return False
        return seen_indices == expected_keys
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return False


def validate_condition_cases(
    rows: object,
    *,
    conditions: set[tuple[str, str]],
    option_count: int,
    key: int,
) -> bool:
    """Validate explicit inactive-case receipts."""
    return condition_case_issue(
        rows, conditions=conditions, option_count=option_count, key=key
    ) is None


def condition_case_issue(
    rows: object,
    *,
    conditions: set[tuple[str, str]],
    option_count: int,
    key: int,
) -> None | str:
    """Classify an inactive-case receipt as structurally or semantically invalid."""
    try:
        if type(conditions) is not set or any(
            type(condition) is not tuple
            or len(condition) != 2
            or any(not isinstance(part, str) or not part for part in condition)
            for condition in conditions
        ):
            return "format"
        if not _plain_int(option_count) or option_count < 1:
            return "format"
        if not _plain_int(key) or not 0 <= key < option_count:
            return "format"
        if not conditions:
            return None if rows is None or (isinstance(rows, list | tuple) and not rows) else "format"
        if not isinstance(rows, list | tuple) or len(rows) != len(conditions):
            return "format"

        expected_indices = set(range(option_count))
        seen_conditions: set[tuple[str, str]] = set()
        semantic_veto = False
        for row in rows:
            if not isinstance(row, Mapping) or set(row) != _CONDITION_ROW_KEYS:
                return "format"
            condition = (row["source_ref"], row["condition_quote"])
            if condition not in conditions or condition in seen_conditions:
                return "format"
            seen_conditions.add(condition)
            inactive_options = row["inactive_options"]
            if not isinstance(inactive_options, list | tuple) or len(inactive_options) != option_count:
                return "format"
            seen_indices: set[int] = set()
            for option in inactive_options:
                if not isinstance(option, Mapping) or set(option) != _INACTIVE_OPTION_KEYS:
                    return "format"
                index = option["index"]
                if not _plain_int(index) or index not in expected_indices or index in seen_indices:
                    return "format"
                seen_indices.add(index)
                relation = option["relation"]
                if not isinstance(relation, str) or relation not in {"fulfilled", "not_fulfilled", "unknown"}:
                    return "format"
                if relation == "unknown" or (index == key and relation != "fulfilled") or (
                    index != key and relation != "not_fulfilled"
                ):
                    semantic_veto = True
                reason = option["reason"]
                if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
                    return "format"
            if seen_indices != expected_indices:
                return "format"
        if seen_conditions != conditions:
            return "format"
        return "semantic" if semantic_veto else None
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return "format"


__all__ = [
    "INTENT",
    "INSTRUCTION",
    "condition_case_issue",
    "coverage_issue",
    "negative_relation",
    "positive_relation",
    "validate_condition_cases",
    "validate_receipt",
]
