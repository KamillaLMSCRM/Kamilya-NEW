"""Closed JSON-Schema shapes for intent-specific assessment receipts.

These schemas constrain model transport only.  Dynamic question cardinality,
literal source ownership, option coverage, and semantic consistency remain the
responsibility of the existing native validators.
"""

from __future__ import annotations

from typing import Any

__all__ = ["receipt_schema"]

_KINDS = frozenset({
    "qualification_realizations",
    "option_recall",
    "fulfillment_checks",
    "conditional_cases",
})


def _nonblank(*, maximum: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "string", "minLength": 1, "pattern": r"\S"}
    if maximum is not None:
        result["maxLength"] = maximum
    return result


def _closed(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _qualification_schema() -> dict[str, Any]:
    def row(*, preserved: bool, relations: tuple[str, ...], spans_required: bool) -> dict[str, Any]:
        spans: dict[str, Any] = {
            "type": "array",
            "uniqueItems": True,
            "items": _closed({"ref": {"type": "string", "pattern": r"^P[1-9]\d*$"}}),
        }
        if spans_required:
            spans["minItems"] = 1
        return _closed({
            "binding_id": {"type": "string", "pattern": r"^B[1-9]\d*$"},
            "relation": {"type": "string", "enum": list(relations)},
            "preserved": {"type": "boolean", "enum": [preserved]},
            "premise_spans": spans,
            "reason": _nonblank(maximum=300),
        })

    return {
        "type": "array",
        "minItems": 1,
        "items": {"oneOf": [
            row(preserved=True, relations=("equivalent", "entailed_specialization"), spans_required=True),
            row(preserved=False, relations=("broader", "unknown"), spans_required=False),
        ]},
    }


def _recall_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": 1,
        "items": _closed({
            "index": {"type": "integer", "minimum": 0},
            "slot_faithful": {"type": "boolean"},
            "material_difference": {"type": "boolean"},
            "reason": _nonblank(maximum=300),
        }),
    }


def _coverage_option_schema() -> dict[str, Any]:
    common = {
        "index": {"type": "integer", "minimum": 0},
        "reason": _nonblank(maximum=300),
    }
    return {"oneOf": [
        _closed(common | {
            "relation": {"type": "string", "enum": ["covered"]},
            "option_quote": _nonblank(),
        }),
        _closed(common | {
            "relation": {"type": "string", "enum": ["omitted", "unknown"]},
            "option_quote": {"type": "string", "enum": [""]},
        }),
    ]}


def _fulfillment_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": 1,
        "maxItems": 24,
        "items": _closed({
            "source_ref": _nonblank(),
            "source_quote": {"type": "string", "minLength": 1},
            "options": {
                "type": "array",
                "minItems": 1,
                "items": _coverage_option_schema(),
            },
        }),
    }


def _conditions_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "items": _closed({
            "source_ref": _nonblank(),
            "condition_quote": {"type": "string", "minLength": 1},
            "inactive_options": {
                "type": "array",
                "minItems": 1,
                "items": _closed({
                    "index": {"type": "integer", "minimum": 0},
                    "relation": {
                        "type": "string",
                        "enum": ["fulfilled", "not_fulfilled", "unknown"],
                    },
                    "reason": _nonblank(maximum=300),
                }),
            },
        }),
    }


def receipt_schema(kind: str) -> dict[str, Any]:
    """Return a fresh closed wire schema for one intent-specific receipt field."""

    if not isinstance(kind, str) or kind not in _KINDS:
        raise ValueError("assessment_receipt_schema_kind")
    if kind == "qualification_realizations":
        return _qualification_schema()
    if kind == "option_recall":
        return _recall_schema()
    if kind == "fulfillment_checks":
        return _fulfillment_schema()
    return _conditions_schema()
