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


def is_normalized_editorial_review_format(fmt: Any) -> bool:
    try:
        if fmt['json_schema']['name'] != NORMALIZED_REVIEW_NAME:
            return False
        return is_editorial_review_format(_renamed(fmt, REVIEW_NAME))
    except (KeyError, TypeError, IndexError):
        return False


def matches_normalized_editorial_review(value: Any, fmt: Any) -> bool:
    if not is_normalized_editorial_review_format(fmt):
        return False
    return matches_editorial_review(value, _renamed(fmt, REVIEW_NAME))
