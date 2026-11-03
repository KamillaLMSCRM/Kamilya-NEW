"""Exact source-owned parts for bounded question construction."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NoReturn

from app.modules.ai.source_layout import parse_source_marker

_DERIVED_KEYS = {"source_id", "proposition", "position"}
_RAW_KEYS = {"source_id", "proposition", "fixed_text", "position"}
_OFFSET_KEYS = {
    "proposition_start",
    "proposition_end",
    "variable_start",
    "variable_end",
    "fixed_start",
    "fixed_end",
}
_CANONICAL_KEYS = _RAW_KEYS | _OFFSET_KEYS


def _fail(code: str) -> NoReturn:
    raise ValueError(code)


def _is_stripped_text(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _unique_start(haystack: str, needle: str) -> int | None:
    first = haystack.find(needle)
    if first < 0 or haystack.find(needle, first + 1) >= 0:
        return None
    return first


def validate_fixed_source_context(
    record: Mapping[str, Any],
    *,
    source_id: str,
    source_text: str,
    variable: str,
    full_set: bool = False,
    component_count: int = 1,
) -> dict[str, Any]:
    """Return exact source-relative offsets for one literal fixed/variable split."""

    if not isinstance(record, Mapping):
        _fail("fixed_source_context_invalid_shape")
    keys = set(record)
    if keys not in (_DERIVED_KEYS, _RAW_KEYS, _CANONICAL_KEYS):
        _fail("fixed_source_context_invalid_shape")
    if not _is_stripped_text(source_id):
        _fail("fixed_source_context_invalid_source_id")
    if not isinstance(source_text, str) or not source_text:
        _fail("fixed_source_context_invalid_source_text")
    if not _is_stripped_text(variable):
        _fail("fixed_source_context_invalid_variable")
    if type(full_set) is not bool or type(component_count) is not int:
        _fail("fixed_source_context_invalid_mode")
    if full_set or component_count != 1:
        _fail("fixed_source_context_requires_single_component")

    record_source_id = record["source_id"]
    proposition = record["proposition"]
    position = record["position"]
    if not _is_stripped_text(record_source_id):
        _fail("fixed_source_context_invalid_source_id")
    if record_source_id != source_id:
        _fail("fixed_source_context_owner_mismatch")
    if not _is_stripped_text(proposition):
        _fail("fixed_source_context_invalid_proposition")
    if not 240 < len(proposition) <= 512:
        _fail("fixed_source_context_proposition_bounds")
    if len(variable) > 240:
        _fail("fixed_source_context_variable_bounds")
    if not isinstance(position, str) or position not in {"prefix", "suffix"}:
        _fail("fixed_source_context_invalid_position")

    if keys == _DERIVED_KEYS:
        variable_offset = _unique_start(proposition, variable)
        if variable_offset is None:
            _fail("fixed_source_context_part_not_unique")
        variable_end = variable_offset + len(variable)
        if position == "suffix":
            if variable_offset != 0:
                marker = parse_source_marker(proposition)
                if (marker is None or marker.content_start != variable_offset
                        or _unique_start(source_text, proposition) is None):
                    _fail("fixed_source_context_position_mismatch")
                # Omit verified layout metadata from the semantic envelope only;
                # the strict canonical validator still binds its exact raw body.
                proposition = proposition[marker.content_start:]
                variable_offset = 0
                variable_end = len(variable)
            fixed_text = proposition[variable_end:].lstrip()
        else:
            if variable_end != len(proposition):
                _fail("fixed_source_context_position_mismatch")
            fixed_text = proposition[:variable_offset].rstrip()
        return validate_fixed_source_context(
            {
                "source_id": record_source_id,
                "proposition": proposition,
                "fixed_text": fixed_text,
                "position": position,
            },
            source_id=source_id,
            source_text=source_text,
            variable=variable,
            full_set=full_set,
            component_count=component_count,
        )

    fixed_text = record["fixed_text"]
    if not _is_stripped_text(fixed_text):
        _fail("fixed_source_context_invalid_fixed_text")
    if len(fixed_text) > 300:
        _fail("fixed_source_context_fixed_bounds")

    proposition_start = _unique_start(source_text, proposition)
    if proposition_start is None:
        _fail("fixed_source_context_proposition_not_unique")
    variable_offset = _unique_start(proposition, variable)
    fixed_offset = _unique_start(proposition, fixed_text)
    if variable_offset is None or fixed_offset is None:
        _fail("fixed_source_context_part_not_unique")
    variable_internal_end = variable_offset + len(variable)
    fixed_internal_end = fixed_offset + len(fixed_text)
    if not (
        variable_internal_end <= fixed_offset
        or fixed_internal_end <= variable_offset
    ):
        _fail("fixed_source_context_parts_overlap")

    if position == "suffix":
        if variable_offset > fixed_offset:
            _fail("fixed_source_context_position_mismatch")
        first_start, first_end = variable_offset, variable_internal_end
        second_start, second_end = fixed_offset, fixed_internal_end
    else:
        if fixed_offset > variable_offset:
            _fail("fixed_source_context_position_mismatch")
        first_start, first_end = fixed_offset, fixed_internal_end
        second_start, second_end = variable_offset, variable_internal_end
    separator = proposition[first_end:second_start]
    if (
        first_start != 0
        or second_end != len(proposition)
        or not separator
        or not separator.isspace()
    ):
        _fail("fixed_source_context_material_gap")

    canonical = {
        "source_id": record_source_id,
        "proposition": proposition,
        "fixed_text": fixed_text,
        "position": position,
        "proposition_start": proposition_start,
        "proposition_end": proposition_start + len(proposition),
        "variable_start": proposition_start + variable_offset,
        "variable_end": proposition_start + variable_offset + len(variable),
        "fixed_start": proposition_start + fixed_offset,
        "fixed_end": proposition_start + fixed_offset + len(fixed_text),
    }
    if keys == _CANONICAL_KEYS and any(
        type(record[key]) is not int or record[key] != canonical[key]
        for key in _OFFSET_KEYS
    ):
        _fail("fixed_source_context_offset_mismatch")
    return canonical
