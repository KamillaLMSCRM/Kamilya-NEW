"""Parse source-first output without silently rewriting malformed JSON."""
from __future__ import annotations

import json
import math
from typing import Any


def parse_source_first_response(content: str) -> dict[str, Any]:
    """Reject duplicate keys and non-finite values before a draft is checkpointed."""
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("source_first_qa_duplicate_key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise ValueError("source_first_qa_nonfinite_number")

    def finite_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("source_first_qa_nonfinite_number")
        return number

    parsed = json.loads(content, object_pairs_hook=unique_pairs, parse_constant=reject_constant,
                        parse_float=finite_float)
    if not isinstance(parsed, dict):
        raise ValueError("source_first_qa_response_invalid")
    return parsed
