"""Closed versioned model artifacts; shape validation grants no semantic approval."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.modules.ai.v3.author_response_schema import is_lesson_author_response, is_lesson_author_response_format
from app.modules.ai.v3.auxiliary_response_contracts import (
    auxiliary_contract,
    is_auxiliary_format,
    matches_auxiliary_response,
)
from app.modules.ai.v3.batch_review_response_schema import is_batch_review_response, is_batch_review_response_format
from app.modules.ai.v3.diversity_response_schema import is_diversity_author_format, is_diversity_author_response
from app.modules.ai.v3.extraction_response_schema import is_rule_extraction_response, is_rule_extraction_response_format
from app.modules.ai.v3.typed_review_buckets import is_typed_review_format, is_typed_review_response


def response_contract(value: object) -> str | None:
    if is_diversity_author_format(value):
        return "diversity_author"
    auxiliary = auxiliary_contract(value)
    if auxiliary is not None and is_auxiliary_format(value):
        return "aux:" + auxiliary
    if is_lesson_author_response_format(value):
        return "lesson"
    if is_rule_extraction_response_format(value):
        return "extraction"
    if is_batch_review_response_format(value):
        return "batch_review"
    if is_typed_review_format(value):
        return "batch_review_buckets"
    return None


def response_contract_hash(value: dict[str, Any]) -> str:
    if response_contract(value) is None:
        raise ValueError("v3_response_format_unknown")
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    ).hexdigest()


def matches_response_contract(value: object, response_format: dict[str, Any]) -> bool:
    kind = response_contract(response_format)
    if kind == "diversity_author":
        return is_diversity_author_response(value, response_format)
    if kind is not None and kind.startswith("aux:"):
        return matches_auxiliary_response(value, response_format)
    if kind == "lesson":
        return is_lesson_author_response(value)
    if kind == "extraction":
        return is_rule_extraction_response(value)
    if kind == "batch_review":
        return is_batch_review_response(value)
    if kind == "batch_review_buckets":
        return is_typed_review_response(value, response_format)
    return False
