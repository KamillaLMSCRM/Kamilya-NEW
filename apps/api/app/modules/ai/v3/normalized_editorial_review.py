"""Versioned format identity for normalized editorial review custody."""
from __future__ import annotations

import copy
from typing import Any

from app.modules.ai.v3.practical_contract import PracticalSourcePacket
from app.modules.ai.v3.practical_editorial_contract import (
    REVIEW_NAME,
    _review_format,
    editorial_review_format,
    is_editorial_review_format,
    matches_editorial_review,
)

NORMALIZED_REVIEW_NAME = 'v3_practical_editorial_review_v2'


def _renamed(fmt: dict[str, Any], name: str) -> dict[str, Any]:
    result = copy.deepcopy(fmt)
    result['json_schema']['name'] = name
    return result


def normalized_editorial_review_format(packet: PracticalSourcePacket, course: dict[str, Any]) -> dict[str, Any]:
    return _renamed(editorial_review_format(packet, course), NORMALIZED_REVIEW_NAME)


def normalized_review_format(refs: list[str], lesson_ids: list[str], question_ids: list[str],
                             source_fp: str, course_fp: str) -> dict[str, Any]:
    return _renamed(_review_format(refs, lesson_ids, question_ids, source_fp, course_fp), NORMALIZED_REVIEW_NAME)


def _reference_properties(fmt: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    props = fmt['json_schema']['schema']['properties']
    return (
        props['source_notes']['items']['properties']['source_refs']['items']['enum'],
        props['narrative_sources']['properties'],
    )


def compact_review_wire(fmt: dict[str, Any]) -> dict[str, Any]:
    """Represent the same owned reference inventory once on the wire."""
    compact = copy.deepcopy(fmt)
    _, lessons = _reference_properties(compact)
    for row in lessons.values():
        row['items'].pop('enum', None)
    return compact


def expanded_review_wire(fmt: Any) -> dict[str, Any] | None:
    try:
        if fmt['json_schema']['name'] != NORMALIZED_REVIEW_NAME:
            return None
        expanded = copy.deepcopy(fmt)
        refs, lessons = _reference_properties(expanded)
        for row in lessons.values():
            row['items'].setdefault('enum', refs)
        if not is_editorial_review_format(_renamed(expanded, REVIEW_NAME)):
            return None
        return expanded if fmt == expanded or fmt == compact_review_wire(expanded) else None
    except (AttributeError, KeyError, TypeError, IndexError):
        return None


def is_normalized_editorial_review_format(fmt: Any) -> bool:
    return expanded_review_wire(fmt) is not None


def matches_normalized_editorial_review(value: Any, fmt: Any) -> bool:
    expanded = expanded_review_wire(fmt)
    return expanded is not None and matches_editorial_review(value, _renamed(expanded, REVIEW_NAME))
