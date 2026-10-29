"""Strict JSON value equivalence for persisted evidence, not provenance."""
import json
from typing import Any


def _valid(value: Any) -> bool:
    if value is None or type(value) in (str, bool, int, float):
        return True
    if type(value) in (tuple, list):
        return all(_valid(row) for row in value)
    if type(value) is dict:
        return all(type(key) is str and _valid(row) for key, row in value.items())
    return False


def equivalent(left: Any, right: Any) -> bool:
    """Compare JSON types/values; tuples represent arrays, never provenance."""
    try:
        if not _valid(left) or not _valid(right):
            return False
        return json.dumps(left, ensure_ascii=True, sort_keys=True, allow_nan=False, separators=(",", ":")) == json.dumps(
            right, ensure_ascii=True, sort_keys=True, allow_nan=False, separators=(",", ":"))
    except (ValueError, TypeError, OverflowError, RecursionError):
        return False
