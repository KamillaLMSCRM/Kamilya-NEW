"""Test-only migration aid for legacy scripted lesson critics.

The helper derives component meaning rows only from the critic request that the
runtime actually emitted.  It deliberately does not inspect production state,
infer source truth, or replace explicit meaning rows supplied by a fixture.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy

_POSITIVE_RELATIONS = frozenset({"supported", "fulfilled"})
_NEGATIVE_RELATIONS = frozenset({"contradicted", "not_fulfilled"})


def _strict_rows(value: object) -> list[Mapping[str, object]] | None:
    if not isinstance(value, list | tuple):
        return None
    if not all(isinstance(row, Mapping) for row in value):
        return None
    return list(value)


def _positive_option_vector(row: Mapping[str, object]) -> bool:
    options = _strict_rows(row.get("options"))
    if not options:
        return False
    relations = [option.get("relation") for option in options]
    if not all(isinstance(relation, str) for relation in relations):
        return False
    return (
        sum(relation in _POSITIVE_RELATIONS for relation in relations) == 1
        and all(relation in _POSITIVE_RELATIONS or relation in _NEGATIVE_RELATIONS for relation in relations)
    )


def _legacy_positive(task: str, row: Mapping[str, object]) -> bool:
    if not _positive_option_vector(row):
        return False
    if task == "lesson_assessment_review":
        return all(
            row.get(field) is True
            for field in ("educational", "lesson_answerable", "unambiguous", "explanation_supported")
        )
    return row.get("admit") is True


def _claimed_targets(task: str, row: Mapping[str, object]) -> tuple[str, ...]:
    if task == "lesson_assessment_review":
        values = row.get("target_ids")
        if not isinstance(values, list | tuple):
            return ()
        return tuple(value for value in values if isinstance(value, str) and value)
    proofs = _strict_rows(row.get("target_proofs"))
    if proofs is None:
        return ()
    return tuple(
        target_id
        for proof in proofs
        if isinstance((target_id := proof.get("target_id")), str) and target_id
    )


def _request_inventory(request: Mapping[str, object]) -> tuple[
    dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]
]:
    components: dict[str, tuple[str, ...]] = {}
    for target in _strict_rows(request.get("targets")) or []:
        target_id = target.get("target_id")
        if not isinstance(target_id, str) or not target_id:
            continue
        ids: list[str] = []
        for component in _strict_rows(target.get("components")) or []:
            component_id = component.get("component_id")
            if isinstance(component_id, str) and component_id and component_id not in ids:
                ids.append(component_id)
        components[target_id] = tuple(ids)

    questions: dict[str, tuple[str, ...]] = {}
    for question in _strict_rows(request.get("questions")) or []:
        question_id = question.get("question_id")
        target_ids = question.get("target_ids")
        if not isinstance(question_id, str) or not isinstance(target_ids, list | tuple):
            continue
        questions[question_id] = tuple(
            target_id for target_id in target_ids
            if isinstance(target_id, str) and target_id in components
        )
    return components, questions


def complete_mock_component_fulfillments(
    request: Mapping[str, object], response: object
) -> object:
    """Add explicit component meaning to legacy synthetic critic responses.

    Existing meaning rows are immutable.  A positive legacy mock gets
    ``preserved`` only for components declared by the request and claimed by
    that returned row.  A negative legacy mock gets ``unknown`` so enriching
    its wire shape cannot turn the original veto into approval.
    """

    result = deepcopy(response)
    task = request.get("task")
    if task not in {"lesson_assessment_review", "lesson_assessment_counterexample"}:
        return result
    if not isinstance(result, dict):
        return result
    collection = "reviews" if task == "lesson_assessment_review" else "audits"
    rows = _strict_rows(result.get(collection))
    if rows is None:
        return result

    target_components, question_targets = _request_inventory(request)
    enriched: list[object] = []
    for original in result[collection]:
        if not isinstance(original, dict) or "component_fulfillments" in original:
            enriched.append(original)
            continue
        row = dict(original)
        question_id = row.get("question_id")
        allowed_targets = question_targets.get(question_id, ()) if isinstance(question_id, str) else ()
        claimed = set(_claimed_targets(task, row))
        component_ids = tuple(
            component_id
            for target_id in allowed_targets
            if target_id in claimed
            for component_id in target_components.get(target_id, ())
        )
        relation = "preserved" if _legacy_positive(task, row) else "unknown"
        row["component_fulfillments"] = [
            {
                "component_id": component_id,
                "relation": relation,
                "reason": (
                    "Synthetic legacy critic preserves the declared toy component."
                    if relation == "preserved"
                    else "Synthetic legacy critic retains the fixture's negative or unknown verdict."
                ),
            }
            for component_id in component_ids
        ]
        enriched.append(row)
    result[collection] = enriched
    return result


def parse_mock_component_response(parser, serialized_response: str, messages):
    """Adapt explicit legacy scripted replies at their test-only call site."""
    try:
        request = json.loads(messages[-1]["content"])
        response = json.loads(serialized_response)
    except (KeyError, IndexError, TypeError, ValueError):
        return parser(serialized_response)
    if not isinstance(request, Mapping):
        return parser(serialized_response)
    response = complete_mock_component_fulfillments(request, response)
    return parser(json.dumps(response, ensure_ascii=False))
