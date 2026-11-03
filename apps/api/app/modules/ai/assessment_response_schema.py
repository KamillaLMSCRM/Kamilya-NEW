"""Pure JSON-Schema transport contract for independent assessment critics.

The schema requires evidence fields but never supplies votes, answer keys,
defaults, or semantic approval. Native validators remain authoritative for
source truth, option exclusivity, component coverage, and application evidence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from app.modules.ai.application_evidence import APPLICATION_PROOF_FIELDS
from app.modules.ai.assessment_receipt_schema import receipt_schema
from app.modules.ai.component_fulfillment import (
    component_fulfillment_inventory_schema,
    component_fulfillment_schema,
)

CriticRole = Literal["review", "counter"]
__all__ = ["critic_response_schema"]

_RELATIONS = ("supported", "contradicted", "unknown")
_MODES = frozenset({"ordinary", "recall", "fulfillment", "qualified"})
_APPLICATION_PROPERTIES: dict[str, dict[str, Any]] = {
    "target_id": {"type": "string", "minLength": 1},
    "applied": {"type": "boolean"},
    "premise_quote": {"type": "string", "maxLength": 1000},
    "action_quote": {"type": "string", "maxLength": 1000},
    "reason": {"type": "string", "minLength": 1, "maxLength": 300, "pattern": r"\S"},
}
if frozenset(_APPLICATION_PROPERTIES) != APPLICATION_PROOF_FIELDS:  # pragma: no cover - drift tripwire
    raise RuntimeError("application_proof_schema_fields_drifted")


def _nonblank_string(*, maximum: int | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string", "minLength": 1, "pattern": r"\S"}
    if maximum is not None:
        schema["maxLength"] = maximum
    return schema


def _option_schema(*, fulfillment: bool = False) -> dict[str, Any]:
    properties = {
        "index": {"type": "integer", "minimum": 0},
        "relation": {"type": "string", "enum": list(
            ("fulfilled", "not_fulfilled", "unknown") if fulfillment else _RELATIONS)},
        "source_ref": _nonblank_string(),
    }
    if fulfillment:
        properties |= {"component_id": _nonblank_string(), "reason": _nonblank_string(maximum=300)}
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _option_language_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "index": {"type": "integer", "minimum": 0},
                "grammatical": {"type": "boolean"},
                "reason": _nonblank_string(maximum=300),
            },
            "required": ["index", "grammatical", "reason"],
            "additionalProperties": False,
        },
    }


def _application_proofs_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {key: dict(value) for key, value in _APPLICATION_PROPERTIES.items()},
            "required": sorted(APPLICATION_PROOF_FIELDS),
            "additionalProperties": False,
        },
    }


def _target_proof_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "target_id": _nonblank_string(),
                "question_part": {"type": "string", "enum": ["stem", "answer", "both"]},
                "source_ref": _nonblank_string(),
            },
            "required": ["target_id", "question_part", "source_ref"],
            "additionalProperties": False,
        },
    }


def _component_maps() -> dict[str, Any]:
    shapes = []
    for part, role in (("answer", "discriminating_answer"), ("stem", "fixed_context")):
        for selector, value in (("quote", _nonblank_string()), ("whole_part", {"enum": [True]})):
            properties = {"part": {"enum": [part]}, "role": {"enum": [role]}, selector: value}
            shapes.append({"type": "object", "properties": properties,
                           "required": list(properties), "additionalProperties": False})
    properties = {"target_id": _nonblank_string(), "component_id": _nonblank_string(),
                  "source_ref": _nonblank_string(),
                  "realizations": {"type": "array", "minItems": 1, "items": {"oneOf": shapes}}}
    return {"type": "array", "items": {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}}


def critic_response_schema(
    role: CriticRole,
    *,
    application_required: bool,
    separate_language: bool,
    question_modes: Mapping[str, str] | None = None,
    option_counts: Mapping[str, int] | None = None,
    application_targets: Mapping[str, Sequence[str]] | None = None,
    component_ids: Mapping[str, Sequence[str]] | None = None,
    lesson_reference_ids: Sequence[str] | None = None,
    teaching_requirement_ids: Mapping[str, Sequence[str]] | None = None,
    teaching_reference_ids: Sequence[str] = (),
    teaching_inventory_items: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
) -> dict[str, Any]:
    """Return a fresh closed-root schema for one independent critic response."""

    if role not in ("review", "counter"):
        raise ValueError("critic_response_schema_role")
    if type(application_required) is not bool or type(separate_language) is not bool:
        raise TypeError("critic_response_schema_flags")
    if question_modes is not None and (not isinstance(question_modes, Mapping)
            or any(not isinstance(key, str) or not key or not isinstance(mode, str) or mode not in _MODES
                   for key, mode in question_modes.items())):
        raise ValueError("critic_response_schema_question_modes")
    for metadata in (option_counts, application_targets, component_ids, teaching_requirement_ids, teaching_inventory_items):
        if metadata is not None and (not question_modes or set(metadata) != set(question_modes)):
            raise ValueError("critic_response_schema_question_inventory")
    if option_counts is not None and any(type(value) is not int or not 2 <= value <= 24
                                         for value in option_counts.values()):
        raise ValueError("critic_response_schema_option_counts")
    if application_targets is not None and any(not isinstance(values, list | tuple)
            or any(not isinstance(value, str) or not value for value in values)
            or len(set(values)) != len(values) for values in application_targets.values()):
        raise ValueError("critic_response_schema_application_targets")
    if component_ids is not None:
        try:
            for values in component_ids.values():
                component_fulfillment_inventory_schema(values)
        except ValueError as exc:
            raise ValueError("critic_response_schema_component_ids") from exc
    if lesson_reference_ids is not None and (
        role != "review"
        or not isinstance(lesson_reference_ids, list | tuple)
        or not lesson_reference_ids
        or any(not isinstance(value, str) or not value for value in lesson_reference_ids)
        or len(set(lesson_reference_ids)) != len(lesson_reference_ids)
    ):
        raise ValueError("critic_response_schema_lesson_references")
    if teaching_inventory_items is not None and (
        teaching_requirement_ids is None
        or any(not isinstance(rows, Mapping) or not set(rows) <= set(teaching_requirement_ids[key])
            or any(not isinstance(values, list | tuple) or not values
                   or any(not isinstance(value, str) or not value for value in values)
                   or len(values) != len(set(values)) for values in rows.values())
            for key, rows in teaching_inventory_items.items())
    ):
        raise ValueError("critic_response_schema_teaching_inventory_items")

    common_properties: dict[str, Any] = {
        "question_id": _nonblank_string(),
        "options": {"type": "array", "items": _option_schema(), "minItems": 1},
        "component_realizations": _component_maps(),
        "component_fulfillments": component_fulfillment_schema(),
        "application_proofs": _application_proofs_schema(),
    }
    required = ["question_id", "options", "component_realizations", "component_fulfillments"]
    if teaching_requirement_ids is not None:
        if (any(not isinstance(value, str) or not value for value in teaching_reference_ids)
                or len(set(teaching_reference_ids)) != len(teaching_reference_ids)
                or any(not isinstance(values, list | tuple) or not values
                       or any(not isinstance(value, str) or not value for value in values)
                       or len(set(values)) != len(values) for values in teaching_requirement_ids.values())):
            raise ValueError("critic_response_schema_teaching_inventory")
        common_properties["teaching_proofs"] = {"type": "array", "items": {
            "type": "object", "properties": {
                "requirement_id": _nonblank_string(),
                "relation": {"type": "string", "enum": ["preserved", "missing", "unknown"]},
                "teaching_quotes": {"type": "object", "additionalProperties": _nonblank_string(),
                    **({"propertyNames": {"enum": list(teaching_reference_ids)}} if teaching_reference_ids else
                       {"maxProperties": 0})},
                "reason": _nonblank_string(maximum=300),
            }, "required": ["requirement_id", "relation", "teaching_quotes", "reason"],
            "additionalProperties": False,
            "allOf": [{"if": {"properties": {"relation": {"const": "preserved"}}, "required": ["relation"]},
                       "then": {"properties": {"teaching_quotes": {"minProperties": 1}}}}]}}
        if teaching_inventory_items is not None and any(teaching_inventory_items.values()):
            common_properties["teaching_proofs"]["items"]["properties"]["inventory_matches"] = {
                "type": "array", "items": {"type": "object", "properties": {
                    "item_id": _nonblank_string(),
                    "teaching_ref": {"type": "string", "enum": list(teaching_reference_ids)},
                    "learner_quote": _nonblank_string(),
                    "relation": {"type": "string", "enum": ["same_entity", "different", "unknown"]},
                    "reason": _nonblank_string(maximum=300),
                }, "required": ["item_id", "teaching_ref", "learner_quote", "relation", "reason"],
                "additionalProperties": False}}
        required.append("teaching_proofs")
    if not separate_language:
        common_properties["option_language"] = _option_language_schema()
        required.append("option_language")
    if application_required:
        required.append("application_proofs")

    if role == "review":
        root_field = "reviews"
        properties = common_properties | {
            "educational": {"type": "boolean"},
            "educational_reason": _nonblank_string(maximum=300),
            "lesson_answerable": {"type": "boolean"},
            "unambiguous": {"type": "boolean"},
            "explanation_supported": {"type": "boolean"},
            "target_ids": {
                "type": "array",
                "items": _nonblank_string(),
                "uniqueItems": True,
            },
            "explanation": _nonblank_string(),
            "lesson_ref": (_nonblank_string() if lesson_reference_ids is None else
                           {"type": "string", "enum": list(lesson_reference_ids)}),
        }
        if lesson_reference_ids is not None:
            properties["lesson_refs"] = {
                "type": "array",
                "items": {"type": "string", "enum": list(lesson_reference_ids)},
                "minItems": 1,
                "maxItems": min(8, len(lesson_reference_ids)),
                "uniqueItems": True,
            }
        required.extend([
            "educational",
            "educational_reason",
            "lesson_answerable",
            "unambiguous",
            "explanation_supported",
            "target_ids",
            "explanation",
        ])
        if lesson_reference_ids is None:
            required.append("lesson_ref")
    else:
        root_field = "audits"
        properties = common_properties | {
            "target_proofs": _target_proof_schema(),
            "reason": _nonblank_string(maximum=300),
            "admit": {"type": "boolean"},
        }
        required.extend(["target_proofs", "reason", "admit"])

    variants = []
    for mode in dict.fromkeys(question_modes.values() if question_modes else ("ordinary",)):
        mode_properties, mode_required = dict(properties), list(required)
        if question_modes:
            mode_properties["question_id"] = {"type": "string", "enum": [
                key for key, value in question_modes.items() if value == mode]}
        if mode == "fulfillment":
            mode_properties["options"] = {"type": "array", "minItems": 1,
                                           "items": _option_schema(fulfillment=True)}
            for field in ("fulfillment_checks", "conditional_cases"):
                mode_properties[field] = receipt_schema(field)
                mode_required.append(field)
        elif mode == "qualified":
            mode_properties["qualification_realizations"] = receipt_schema("qualification_realizations")
            mode_required.append("qualification_realizations")
        elif mode == "recall":
            mode_properties["option_recall"] = receipt_schema("option_recall")
            mode_required.append("option_recall")
        variant: dict[str, Any] = {"type": "object", "properties": mode_properties,
                                   "required": mode_required, "additionalProperties": False}
        if role == "review" and lesson_reference_ids is not None:
            variant["oneOf"] = [
                {"required": ["lesson_ref"], "not": {"required": ["lesson_refs"]}},
                {"required": ["lesson_refs"], "not": {"required": ["lesson_ref"]}},
            ]
        variants.append(variant)
    row = variants[0] if len(variants) == 1 else {"oneOf": variants}
    constraints = []
    for question_id in question_modes or ():
        question_properties: dict[str, Any] = {}
        if option_counts is not None:
            count = option_counts[question_id]
            question_properties["options"] = _exact_inventory("index", tuple(range(count)))
        if application_targets is not None:
            ids = list(application_targets[question_id])
            question_properties["application_proofs"] = {"type": "array", "maxItems": len(ids),
                "items": {"properties": {"target_id": {"enum": ids}}, "required": ["target_id"]}}
        if component_ids is not None:
            question_properties["component_fulfillments"] = component_fulfillment_inventory_schema(
                component_ids[question_id])
        if teaching_requirement_ids is not None:
            question_properties["teaching_proofs"] = _exact_inventory(
                "requirement_id", tuple(teaching_requirement_ids[question_id]))
            if teaching_inventory_items is not None and any(teaching_inventory_items.values()):
                item_contracts = teaching_inventory_items[question_id]
                per_requirement = []
                for requirement_id in teaching_requirement_ids[question_id]:
                    if requirement_id in item_contracts:
                        inventory_ids = tuple(item_contracts[requirement_id])
                        per_requirement.append({
                            "if": {"properties": {"requirement_id": {"const": requirement_id}},
                                   "required": ["requirement_id"]},
                            "then": {
                                "if": {"properties": {"relation": {"const": "preserved"}},
                                       "required": ["relation"]},
                                "then": {"required": ["inventory_matches"], "properties": {
                                    "inventory_matches": _exact_inventory("item_id", inventory_ids) | {
                                        "items": {"properties": {"item_id": {"enum": list(inventory_ids)}}},
                                        "prefixItems": [{"properties": {"item_id": {"const": value}}}
                                                        for value in inventory_ids]}}},
                                "else": {"not": {"required": ["inventory_matches"]}}}})
                    else:
                        per_requirement.append({"if": {"properties": {"requirement_id": {"const": requirement_id}},
                                                       "required": ["requirement_id"]},
                                                "then": {"not": {"required": ["inventory_matches"]}}})
                question_properties["teaching_proofs"]["items"] = {"allOf": per_requirement}
        if question_properties:
            constraints.append({"if": {"properties": {"question_id": {"enum": [question_id]}},
                                       "required": ["question_id"]},
                                "then": {"properties": question_properties}})
    if constraints:
        row["allOf"] = constraints
    collection = {"type": "array", "items": row}
    if question_modes:
        collection |= _exact_inventory("question_id", tuple(question_modes))
    return {
        "type": "object",
        "properties": {
            root_field: collection,
        },
        "required": [root_field],
        "additionalProperties": False,
    }


def _exact_inventory(field: str, values: tuple[str, ...] | tuple[int, ...]) -> dict[str, Any]:
    return {"type": "array", "minItems": len(values), "maxItems": len(values), "allOf": [
        {"contains": {"properties": {field: {"enum": [value]}}, "required": [field]},
         "minContains": 1, "maxContains": 1} for value in values]}
