"""Bind critic component semantics to validated custody; never authorize a key."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from app.modules.ai.assessment_components import ComponentRequirement, ComponentValidationResult

COMPONENT_FULFILLMENT_FIELDS = frozenset({"component_id", "relation", "reason"})
COMPONENT_RELATIONS = frozenset({"preserved", "weakened", "unknown"})
MAX_REASON_CHARS, MAX_OPTIONS = 300, 24


@dataclass(frozen=True)
class ComponentFulfillmentFailure:
    code: str
    component_id: str = ""


@dataclass(frozen=True)
class BoundComponentFulfillment:
    role: Literal["review", "counter"]
    target_id: str
    component_id: str
    source_id: str
    source_ref: str
    relation: Literal["preserved", "weakened", "unknown"]
    reason: str
    subject_sha256: str
    binding_sha256: str


@dataclass(frozen=True)
class ComponentFulfillmentResult:
    role: str
    evidence: tuple[BoundComponentFulfillment, ...]
    failures: tuple[ComponentFulfillmentFailure, ...]
    negative_component_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ComponentFulfillmentAgreement:
    component_ids: tuple[str, ...]
    binding_sha256: str
    failures: tuple[ComponentFulfillmentFailure, ...]


def component_fulfillment_schema() -> dict[str, Any]:
    properties = {
        "component_id": {"type": "string", "minLength": 1},
        "relation": {"type": "string", "enum": sorted(COMPONENT_RELATIONS)},
        "reason": {"type": "string", "minLength": 1, "maxLength": MAX_REASON_CHARS, "pattern": r"\S"},
    }
    item = {"type": "object", "properties": properties,
            "required": sorted(COMPONENT_FULFILLMENT_FIELDS), "additionalProperties": False}
    return {"type": "array", "items": item}


def component_fulfillment_inventory_schema(component_ids: Sequence[str]) -> dict[str, Any]:
    if (not _sequence(component_ids)
            or any(not isinstance(value, str) or not value for value in component_ids)):
        raise ValueError("component_fulfillment_schema_inventory")
    if len(set(component_ids)) != len(component_ids):
        raise ValueError("component_fulfillment_schema_inventory")
    values = tuple(component_ids)
    item = {"properties": {"component_id": {"enum": list(values)}}, "required": ["component_id"]}
    return {"type": "array", "maxItems": len(values), "items": item}


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sequence(value: Any) -> bool:
    return not isinstance(value, str | bytes) and isinstance(value, Sequence)


def _failure(code: str, component_id: Any = "") -> ComponentFulfillmentFailure:
    return ComponentFulfillmentFailure(code, component_id if isinstance(component_id, str) else "")


def bind_component_fulfillments(
    custody: ComponentValidationResult,
    fulfillments: Any,
    *,
    role: str,
    policy: str,
    packet_identity: str,
    question_id: str,
    stem: str,
    options: Sequence[str],
    selected_index: int,
    option_vector: Sequence[Mapping[str, Any]],
    requirements: Sequence[ComponentRequirement],
    component_rows: Sequence[Mapping[str, Any]],
    source_passages: Mapping[str, tuple[str, str]],
) -> ComponentFulfillmentResult:
    failures: list[ComponentFulfillmentFailure] = []
    if not isinstance(role, str) or role not in {"review", "counter"}:
        return ComponentFulfillmentResult(role, (), (_failure("invalid_component_fulfillment_role"),))
    if any(not isinstance(value, str) or not value.strip()
           for value in (policy, packet_identity, question_id, stem)):
        return ComponentFulfillmentResult(role, (), (_failure("invalid_component_fulfillment_context"),))
    if not isinstance(custody, ComponentValidationResult) or custody.failures:
        return ComponentFulfillmentResult(role, (), (_failure("invalid_component_custody"),))
    if not isinstance(source_passages, Mapping):
        return ComponentFulfillmentResult(role, (), (_failure("invalid_component_source_passages"),))
    if (not _sequence(options) or not 1 <= len(options) <= MAX_OPTIONS
            or any(not isinstance(option, str) for option in options)
            or type(selected_index) is not int or not 0 <= selected_index < len(options)):
        return ComponentFulfillmentResult(role, (), (_failure("invalid_component_candidate"),))
    if (not _sequence(option_vector) or len(option_vector) != len(options)
            or any(not isinstance(row, Mapping) or type(row.get("index")) is not int for row in option_vector)
            or sorted(row["index"] for row in option_vector) != list(range(len(options)))):
        return ComponentFulfillmentResult(role, (), (_failure("invalid_component_option_vector"),))
    try:
        candidate_sha256 = _digest({"question_id": question_id, "stem": stem, "options": list(options)})
        option_vector_sha256 = _digest([dict(row) for row in option_vector])
        option_relations_sha256 = _digest([
            {"index": row["index"], "relation": row.get("relation")} for row in option_vector
        ])
    except (TypeError, ValueError):
        return ComponentFulfillmentResult(role, (), (_failure("invalid_component_binding_json"),))
    bindings = custody.component_bindings
    if not bindings:
        empty_failures = () if fulfillments in ([], ()) and not custody.valid_target_ids else (
            _failure("invalid_component_custody_inventory"),)
        return ComponentFulfillmentResult(role, (), empty_failures)
    if (not _sequence(custody.valid_target_ids)
            or any(not isinstance(target, str) or not target for target in custody.valid_target_ids)
            or any(not isinstance(row.target_id, str) or not isinstance(row.component_id, str)
                   or not isinstance(row.source_id, str) for row in bindings)):
        return ComponentFulfillmentResult(role, (), (_failure("invalid_component_custody_inventory"),))
    binding_targets = tuple(dict.fromkeys(row.target_id for row in bindings))
    if binding_targets != custody.valid_target_ids:
        return ComponentFulfillmentResult(role, (), (_failure("invalid_component_custody_inventory"),))
    if (not _sequence(requirements) or any(not isinstance(row, ComponentRequirement)
            or not isinstance(row.target_id, str) or not isinstance(row.component_id, str) for row in requirements)):
        return ComponentFulfillmentResult(role, (), (_failure("invalid_component_requirements"),))
    requirement_by_id = {row.component_id: row for row in requirements}
    binding_by_id = {row.component_id: row for row in bindings}
    if len(requirement_by_id) != len(requirements) or set(requirement_by_id) != set(binding_by_id):
        return ComponentFulfillmentResult(role, (), (_failure("component_requirement_inventory_mismatch"),))
    if any(requirement_by_id[key].target_id != binding.target_id for key, binding in binding_by_id.items()):
        return ComponentFulfillmentResult(role, (), (_failure("invalid_component_custody_inventory"),))
    if (not _sequence(component_rows) or any(not isinstance(row, Mapping) for row in component_rows)):
        return ComponentFulfillmentResult(role, (), (_failure("invalid_component_rows"),))
    rows_by_id: dict[str, Mapping[str, Any]] = {}
    for row in component_rows:
        component_id = row.get("component_id")
        if not isinstance(component_id, str) or component_id in rows_by_id:
            failures.append(_failure("duplicate_or_invalid_component_row", component_id))
        else:
            rows_by_id[component_id] = row
    if set(rows_by_id) != set(binding_by_id):
        failures.append(_failure("component_row_inventory_mismatch"))
    raw_rows: dict[str, Mapping[str, Any]] = {}
    negative_ids = list(dict.fromkeys(
        row.get("component_id") for row in fulfillments
        if isinstance(row, Mapping) and isinstance(row.get("component_id"), str)
        and row.get("component_id") in binding_by_id and isinstance(row.get("relation"), str)
        and row.get("relation") in {"weakened", "unknown"}
    )) if _sequence(fulfillments) else []
    if not _sequence(fulfillments):
        failures.append(_failure("invalid_component_fulfillments_shape"))
    else:
        for row in fulfillments:
            if not isinstance(row, Mapping) or set(row) != COMPONENT_FULFILLMENT_FIELDS:
                failures.append(_failure("invalid_component_fulfillment_shape"))
                continue
            component_id, relation, reason = (row.get(key) for key in ("component_id", "relation", "reason"))
            if not isinstance(component_id, str) or component_id not in binding_by_id:
                failures.append(_failure("foreign_component_fulfillment", component_id))
                continue
            if component_id in raw_rows:
                failures.append(_failure("duplicate_component_fulfillment", component_id))
                continue
            raw_rows[component_id] = row
            if not isinstance(relation, str) or relation not in COMPONENT_RELATIONS:
                failures.append(_failure("invalid_component_fulfillment_relation", component_id))
                continue
            if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > MAX_REASON_CHARS:
                failures.append(_failure("invalid_component_fulfillment_reason", component_id))
    for component_id in binding_by_id:
        if component_id not in raw_rows:
            failures.append(_failure("missing_component_fulfillment", component_id))

    evidence: list[BoundComponentFulfillment] = []
    failed_ids = {failure.component_id for failure in failures if failure.component_id}
    if not any(not failure.component_id for failure in failures):
        for component_id, binding in binding_by_id.items():
            if component_id in failed_ids:
                continue
            component_row = rows_by_id.get(component_id)
            fulfillment = raw_rows.get(component_id)
            if component_row is None or fulfillment is None:
                continue
            source_ref = component_row.get("source_ref")
            realizations = component_row.get("realizations")
            passage = source_passages.get(source_ref) if isinstance(source_ref, str) else None
            requirement = requirement_by_id[component_id]
            if (component_row.get("target_id") != binding.target_id or not isinstance(source_ref, str)
                    or not isinstance(passage, tuple) or len(passage) != 2
                    or passage[0] != binding.source_id or not isinstance(passage[1], str)
                    or not _sequence(realizations)):
                failures.append(_failure("component_custody_binding_drift", component_id))
                continue
            realizations = cast(Sequence[Any], realizations)
            if any(not isinstance(item, Mapping) or not isinstance(item.get("role"), str)
                   for item in realizations):
                failures.append(_failure("component_custody_binding_drift", component_id))
                continue
            roles = tuple(sorted(item["role"] for item in realizations))
            if roles != binding.roles:
                failures.append(_failure("component_custody_binding_drift", component_id))
                continue
            if any(not isinstance(item, Mapping) or item.get("part") not in {"stem", "answer"}
                    or not isinstance(item.get("quote"), str)
                    or item["quote"] not in (stem if item["part"] == "stem" else options[selected_index])
                    for item in realizations):
                failures.append(_failure("component_candidate_surface_drift", component_id))
                continue
            alternatives = [alternative.text for alternative in requirement.alternatives
                            if alternative.source_id == binding.source_id and alternative.text in passage[1]]
            if not alternatives:
                failures.append(_failure("component_source_or_requirement_drift", component_id))
                continue
            subject = {
                "policy": policy,
                "packet_identity": packet_identity,
                "question_id": question_id,
                "candidate_sha256": candidate_sha256,
                "selected_index": selected_index,
                "option_relations_sha256": option_relations_sha256,
                "target_id": binding.target_id,
                "component_id": component_id,
                "source_id": binding.source_id,
                "source_components_sha256": _digest(alternatives),
            }
            relation = fulfillment["relation"]
            subject_sha256 = _digest(subject)
            binding_sha256 = _digest({**subject, "role": role, "relation": relation,
                "source_ref": source_ref, "source_passage_sha256": _digest(passage[1]),
                "component_row_sha256": _digest(dict(component_row)), "option_vector_sha256": option_vector_sha256})
            evidence.append(BoundComponentFulfillment(
                role=cast(Literal["review", "counter"], role), target_id=binding.target_id, component_id=component_id,
                source_id=binding.source_id, source_ref=source_ref, relation=relation,
                reason=fulfillment["reason"].strip(), subject_sha256=subject_sha256,
                binding_sha256=binding_sha256,
            ))
    return ComponentFulfillmentResult(role, tuple(evidence), tuple(failures),
                                      tuple(cast(str, component_id) for component_id in negative_ids))


def compare_component_fulfillment_results(review: ComponentFulfillmentResult,
        counter: ComponentFulfillmentResult) -> ComponentFulfillmentAgreement:
    failures: list[ComponentFulfillmentFailure] = []
    if not isinstance(review, ComponentFulfillmentResult) or review.role != "review":
        failures.append(_failure("invalid_review_component_fulfillment"))
    if not isinstance(counter, ComponentFulfillmentResult) or counter.role != "counter":
        failures.append(_failure("invalid_counter_component_fulfillment"))
    if failures:
        return ComponentFulfillmentAgreement((), "", tuple(failures))
    if review.failures:
        failures.append(_failure("review_component_fulfillment_invalid"))
    if counter.failures:
        failures.append(_failure("counter_component_fulfillment_invalid"))
    review_by_id = {row.component_id: row for row in review.evidence}
    counter_by_id = {row.component_id: row for row in counter.evidence}
    if set(review_by_id) != set(counter_by_id) or not review_by_id:
        failures.append(_failure("critic_component_fulfillment_inventory_disagreement"))
    agreed: list[str] = []
    for component_id in sorted(set(review_by_id) | set(counter_by_id)):
        first, second = review_by_id.get(component_id), counter_by_id.get(component_id)
        if first is None or second is None or first.subject_sha256 != second.subject_sha256:
            failures.append(_failure("critic_component_fulfillment_subject_disagreement", component_id))
        elif first.relation != "preserved" or second.relation != "preserved":
            failures.append(_failure("component_semantic_fulfillment_not_proven", component_id))
        else:
            agreed.append(component_id)
    if review.negative_component_ids or counter.negative_component_ids:
        for component_id in sorted(set(review.negative_component_ids) | set(counter.negative_component_ids)):
            if not any(failure.component_id == component_id for failure in failures):
                failures.append(_failure("component_semantic_fulfillment_not_proven", component_id))
    if failures:
        return ComponentFulfillmentAgreement((), "", tuple(failures))
    binding = _digest({"policy": "dual-independent-component-fulfillment-v1",
        "review": [review_by_id[component_id].binding_sha256 for component_id in agreed],
        "counter": [counter_by_id[component_id].binding_sha256 for component_id in agreed]})
    return ComponentFulfillmentAgreement(tuple(agreed), binding, ())


def component_fulfillment_result_matches(stored: ComponentFulfillmentResult,
        recomputed: ComponentFulfillmentResult) -> bool:
    return isinstance(stored, ComponentFulfillmentResult) and stored == recomputed
