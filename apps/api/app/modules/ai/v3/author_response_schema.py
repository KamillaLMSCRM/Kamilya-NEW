"""Versioned strict transport schema for the normal V3 lesson author output.

This describes shape, not grounding, semantic correctness, or course approval.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, cast

NAME = "v3_lesson_author_v1"


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _array(items: dict[str, Any], *, min_items: int = 0) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "array", "items": items}
    if min_items:
        result["minItems"] = min_items
    return result


def lesson_author_response_format() -> dict[str, Any]:
    """Return a fresh independent JSON Schema response format on every call."""
    text = {"type": "string"}
    correct = _object({"text": text})
    distractor = _object({"text": text, "distractor_category": {"type": "string", "enum": [
        "procedural_confusion", "role_confusion", "timing_violation", "unauthorized_action", "threshold_error",
    ]}})
    variant = _object({"variant_id": text, "branch_context": text, "scenario_premise": text, "prompt": text,
                       "correct_option": correct, "distractor_pool": _array(distractor, min_items=3),
                       "explanation": text, "source_quote": text})
    case = _object({"case_id": text, "rule_id": text, "learning_objective": text,
                    "variants": _array(variant)})
    schema = _object({"lesson_id": text, "title": text, "module_title": text, "content": text,
                      "cases": _array(case)})
    # JSON round-trip eliminates shared nested references as well as returning fresh copies.
    response_format = {"type": "json_schema", "json_schema": {"name": NAME, "strict": True, "schema": schema}}
    return cast(dict[str, Any], json.loads(json.dumps(response_format, ensure_ascii=False)))


def lesson_author_schema_hash() -> str:
    encoded = json.dumps(lesson_author_response_format(), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def is_lesson_author_response_format(value: object) -> bool:
    """Match the entire versioned contract, including JSON value types."""
    try:
        actual = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError):
        return False
    expected = json.dumps(lesson_author_response_format(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return actual == expected


def is_lesson_author_response(value: object) -> bool:
    """Validate transport shape independently of a connector's schema claim."""
    def matches(item: object, schema: dict[str, Any]) -> bool:
        kind = schema["type"]
        if kind == "string":
            return type(item) is str and ("enum" not in schema or item in schema["enum"])
        if kind == "array":
            return (type(item) is list and len(item) >= schema.get("minItems", 0)
                    and all(matches(child, schema["items"]) for child in item))
        if kind == "object":
            properties = schema["properties"]
            return (type(item) is dict and set(item) == set(properties)
                    and all(matches(item[key], child) for key, child in properties.items()))
        return False
    return matches(value, lesson_author_response_format()["json_schema"]["schema"])
