"""Closed versioned model artifacts; shape validation grants no semantic approval."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from app.modules.ai.v3.author_response_schema import is_lesson_author_response, is_lesson_author_response_format
from app.modules.ai.v3.extraction_response_schema import is_rule_extraction_response, is_rule_extraction_response_format


def response_contract(value: object) -> str | None:
    if is_lesson_author_response_format(value):
        return "lesson"
    if is_rule_extraction_response_format(value):
        return "extraction"
    return None


def response_contract_hash(value: dict[str, Any]) -> str:
    if response_contract(value) is None:
        raise ValueError("v3_response_format_unknown")
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def matches_response_contract(value: object, response_format: dict[str, Any]) -> bool:
    kind = response_contract(response_format)
    if kind == "lesson":
        return is_lesson_author_response(value)
    if kind == "extraction":
        return is_rule_extraction_response(value)
    return False
