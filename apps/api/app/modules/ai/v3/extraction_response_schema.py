"""Versioned transport shape for V3 rule extraction; not source approval."""
from __future__ import annotations

import hashlib
import json
from typing import Any

NAME = "v3_rule_extraction_v1"
_STRING_FIELDS = ("rule_id", "section", "title", "statement", "timing", "consequences", "source_quote")
_ARRAY_FIELDS = ("conditions", "exceptions", "actors")


def rule_extraction_response_format() -> dict[str, Any]:
    """Create a fresh, closed schema without sharing mutable subobjects."""
    properties: dict[str, Any] = {key: {"type": "string"} for key in _STRING_FIELDS}
    properties.update({key: {"type": "array", "items": {"type": "string"}} for key in _ARRAY_FIELDS})
    rule = {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}
    root_properties = {"document_title": {"type": "string"}, "overview": {"type": "string"},
                       "rules": {"type": "array", "items": rule}}
    root = {"type": "object", "properties": root_properties, "required": list(root_properties),
            "additionalProperties": False}
    return {"type": "json_schema", "json_schema": {"name": NAME, "strict": True, "schema": root}}


def rule_extraction_schema_hash() -> str:
    data = json.dumps(rule_extraction_response_format(), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _same_json(actual: object, expected: object) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict) and isinstance(actual, dict):
        return (all(type(key) is str for key in actual) and actual.keys() == expected.keys()
                and all(_same_json(actual[key], value) for key, value in expected.items()))
    if isinstance(expected, list) and isinstance(actual, list):
        return len(actual) == len(expected) and all(_same_json(a, b) for a, b in zip(actual, expected, strict=True))
    return actual == expected


def is_rule_extraction_response_format(value: object) -> bool:
    """Require the exact format and JSON types, independent of object key order."""
    return _same_json(value, rule_extraction_response_format())


def is_rule_extraction_response(value: object) -> bool:
    """Check raw JSON shape independently; no normalization or semantic verdict."""
    if type(value) is not dict or set(value) != {"document_title", "overview", "rules"}:
        return False
    if type(value["document_title"]) is not str or type(value["overview"]) is not str or type(value["rules"]) is not list:
        return False
    for rule in value["rules"]:
        if type(rule) is not dict or set(rule) != set(_STRING_FIELDS + _ARRAY_FIELDS):
            return False
        if any(type(rule[field]) is not str for field in _STRING_FIELDS):
            return False
        if any(type(rule[field]) is not list or any(type(item) is not str for item in rule[field])
               for field in _ARRAY_FIELDS):
            return False
    return True
