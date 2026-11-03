"""Closed request-bound auxiliary shapes; semantic source checks remain separate."""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, cast

CONTRACT_PREFIX = "v3_aux_"
_CATEGORIES = ["procedural_confusion", "role_confusion", "timing_violation", "unauthorized_action", "threshold_error"]


def _ids(values: list[str]) -> list[str]:
    if (type(values) is not list or not values or any(type(v) is not str or not v.strip() for v in values)
            or len(values) != len(set(values))):
        raise ValueError("auxiliary_identity_invalid")
    return sorted(values)


def _string(values: list[str] | None = None) -> dict[str, Any]:
    return {"type": "string", **({"enum": _ids(values)} if values is not None else {})}


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _array(items: dict[str, Any], minimum: int = 0, maximum: int | None = None) -> dict[str, Any]:
    return {"type": "array", "items": items, "minItems": minimum, **({"maxItems": maximum} if maximum is not None else {})}


def _format(name: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "json_schema", "json_schema": {"name": CONTRACT_PREFIX + name, "strict": True, "schema": _object(properties)}}


def _repairs(name: str, ids: list[str], fields: dict[str, Any], key: str = "variant_id", *, partial: bool = False) -> dict[str, Any]:
    ids = _ids(ids)
    return _format(name, {"repairs": _array(_object({key: _string(ids), **fields}), 0 if partial else len(ids), len(ids))})


def _distractors() -> dict[str, Any]:
    return _array(_object({"text": _string(), "category": _string(_CATEGORIES)}), 3, 3)


def explanation_repair_format(ids: list[str]) -> dict[str, Any]:
    return _repairs("explanation_repair", ids, {"explanation": _string()})


def prose_repair_format(ids: list[str]) -> dict[str, Any]:
    return _repairs("prose_repair", ids, {"old": _string(), "new": _string()}, "id")


def length_repair_format(ids: list[str]) -> dict[str, Any]:
    return _repairs("length_repair", ids, {"distractors": _distractors()})


def distractor_feedback_format(indices: list[int]) -> dict[str, Any]:
    if (type(indices) is not list or not indices or any(type(v) is not int or not 0 <= v <= 3 for v in indices)
            or len(indices) != len(set(indices))):
        raise ValueError("auxiliary_identity_invalid")
    row = _object({"index": {"type": "integer", "enum": sorted(indices)}, "replacement": _string()})
    return _format("distractor_feedback", {"repairs": _array(row, len(indices), len(indices))})


def option_repair_format(ids: list[str], *, include_prompt: bool = False, allow_partial: bool = False) -> dict[str, Any]:
    if type(include_prompt) is not bool or type(allow_partial) is not bool:
        raise ValueError("auxiliary_mode_invalid")
    fields = {"correct": _string(), "distractors": _distractors(), "explanation": _string()}
    if include_prompt:
        fields["prompt"] = _string()
    name = "question_repair" if include_prompt else "option_repair"
    return _repairs(name + ("_partial" if allow_partial else ""), ids, fields, partial=allow_partial)


def citation_review_format(ids: list[str]) -> dict[str, Any]:
    ids = _ids(ids)
    row = _object({"id": _string(ids), "verdict": _string(["COMPLETE", "PARTIAL", "UNSUPPORTED", "UNKNOWN"]),
                   "unsupported": _array(_string()), "summary": _string()})
    return _format("citation_review", {"items": _array(row, len(ids), len(ids))})


def diversity_review_format(fingerprint: str, count: int, rule_ids: list[str]) -> dict[str, Any]:
    if type(fingerprint) is not str or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None or type(count) is not int or not 1 <= count <= 80:
        raise ValueError("auxiliary_identity_invalid")
    pair = _array({"type": "integer", "enum": list(range(1, count + 1))}, 2, 2)
    omission = _object({"rule_id": _string(rule_ids), "exact_quote": _string()})
    return _format("diversity_review", {"fingerprint": _string([fingerprint]), "status": _string(["observed", "unknown"]),
        "overlaps": _array(pair, 0, min(160, count * (count - 1) // 2)), "omissions": _array(omission, 0, 160)})


def _canonical_format(value: object) -> tuple[str, dict[str, Any]]:
    try:
        if type(value) is not dict:
            raise ValueError
        name = value["json_schema"]["name"]
        props = value["json_schema"]["schema"]["properties"]
        if type(name) is not str or not name.startswith(CONTRACT_PREFIX):
            raise ValueError
        kind = name[len(CONTRACT_PREFIX):]
        factories: dict[str, Callable[[list[str]], dict[str, Any]]] = {"prose_repair": prose_repair_format, "explanation_repair": explanation_repair_format,
                     "length_repair": length_repair_format, "option_repair": option_repair_format,
                     "question_repair": lambda ids: option_repair_format(ids, include_prompt=True),
                     "option_repair_partial": lambda ids: option_repair_format(ids, allow_partial=True),
                     "question_repair_partial": lambda ids: option_repair_format(ids, include_prompt=True, allow_partial=True)}
        if kind in factories:
            key = "id" if kind == "prose_repair" else "variant_id"
            rebuilt = factories[kind](props["repairs"]["items"]["properties"][key]["enum"])
        elif kind == "distractor_feedback":
            rebuilt = distractor_feedback_format(props["repairs"]["items"]["properties"]["index"]["enum"])
        elif kind == "citation_review":
            rebuilt = citation_review_format(props["items"]["items"]["properties"]["id"]["enum"])
        elif kind == "diversity_review":
            fp = props["fingerprint"]["enum"]
            indices = props["overlaps"]["items"]["items"]["enum"]
            if type(fp) is not list or len(fp) != 1 or type(indices) is not list:
                raise ValueError
            rebuilt = diversity_review_format(fp[0], len(indices), props["omissions"]["items"]["properties"]["rule_id"]["enum"])
        else:
            raise ValueError
        if json.dumps(value, sort_keys=True, allow_nan=False) != json.dumps(rebuilt, sort_keys=True, allow_nan=False):
            raise ValueError
        return kind, rebuilt
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, RecursionError):
        raise ValueError("auxiliary_format_invalid") from None


def auxiliary_contract(value: object) -> str | None:
    try:
        return _canonical_format(value)[0]
    except ValueError:
        return None


def is_auxiliary_format(value: object) -> bool:
    return auxiliary_contract(value) is not None


def _matches(value: Any, schema: dict[str, Any]) -> bool:
    kind = schema["type"]
    if kind == "object":
        return type(value) is dict and set(value) == set(schema["properties"]) and all(
            _matches(value[key], child) for key, child in schema["properties"].items())
    if kind == "array":
        return type(value) is list and schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 10000) and all(
            _matches(item, schema["items"]) for item in value)
    if kind == "string":
        return type(value) is str and bool(value.strip()) and ("enum" not in schema or value in schema["enum"])
    if kind == "integer":
        return type(value) is int and ("enum" not in schema or value in schema["enum"])
    return False


def matches_auxiliary_response(value: object, response_format: dict[str, Any]) -> bool:
    try:
        kind, canonical = _canonical_format(response_format)
        if not _matches(value, canonical["json_schema"]["schema"]):
            return False
        value = cast(dict[str, Any], value)
        if kind == "diversity_review":
            pairs = value["overlaps"]
            omissions = value["omissions"]
            return (all(pair[0] < pair[1] for pair in pairs) and len({tuple(pair) for pair in pairs}) == len(pairs)
                    and len({(item["rule_id"], item["exact_quote"]) for item in omissions}) == len(omissions))
        rows = value["items" if kind == "citation_review" else "repairs"]
        key = "id" if kind in {"prose_repair", "citation_review"} else "index" if kind == "distractor_feedback" else "variant_id"
        return len({row[key] for row in rows}) == len(rows)
    except (KeyError, TypeError, ValueError, RecursionError):
        return False
