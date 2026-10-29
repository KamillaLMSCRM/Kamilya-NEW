"""Test-only builders for explicit source-plan audit transport.

These helpers provide canned critic signals for tests whose subject is a
different source-plan contract.  They are not source evidence and do not prove
that a model can detect or preserve target applicability context.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

_TARGET_CONTEXT_AXES = (
    "participants",
    "temporal_setting",
    "condition",
    "exception",
    "prerequisite",
    "antecedent",
)


def with_canned_complete_target_context_audit(response: Any, request: Any) -> Any:
    """Add explicit positive six-axis rows to one canned AUDIT response.

    Explicit context transport is never changed, including deliberately
    malformed transport.  A response without a complete request-side target
    inventory is also left untouched so the helper cannot repair bad fixtures.
    """
    if not isinstance(response, dict) or "target_context_verdicts" in response:
        return response
    if not isinstance(request, dict) or not isinstance(request.get("plan"), dict):
        return response
    targets = request["plan"].get("targets")
    if not isinstance(targets, list) or not targets:
        return response
    target_ids = []
    targets_by_id = {}
    for target in targets:
        if not isinstance(target, dict) or not isinstance(target.get("id"), str):
            return response
        target_ids.append(target["id"])
        targets_by_id[target["id"]] = target
    if len(set(target_ids)) != len(target_ids):
        return response

    completed = deepcopy(response)
    votes = completed.get("target_verdicts")
    if votes is None:
        admitted_value = completed.get("admit")
        legacy_target_ids = completed.get("target_ids")
        source_refs = completed.get("source_refs")
        omissions = completed.get("omissions")
        errors = completed.get("errors")
        if (
            type(admitted_value) is not bool
            or not isinstance(legacy_target_ids, list)
            or legacy_target_ids != target_ids
            or not isinstance(source_refs, list)
            or any(not isinstance(ref, str) for ref in source_refs)
            or not isinstance(omissions, list)
            or any(not isinstance(item, str) for item in omissions)
            or not isinstance(errors, list)
            or any(not isinstance(item, str) for item in errors)
            or (admitted_value and (omissions or errors))
        ):
            return response
        admitted = admitted_value
        reasons = completed.get("errors", []) or completed.get("omissions", [])
        if not admitted and not reasons:
            reasons = ["Canned whole-plan audit rejected the target."]
        completed["target_verdicts"] = [
            {
                "target_id": target_id,
                "admit": admitted,
                "errors": [] if admitted else list(reasons),
                "repair_fields": [] if admitted else [
                    "governing_bindings"
                    if "governing_bindings" in targets_by_id[target_id]
                    else "answer_components"
                ],
            }
            for target_id in target_ids
        ]
        completed.setdefault("source_gaps", [])
    elif isinstance(votes, list):
        for vote in votes:
            if not isinstance(vote, dict) or "repair_fields" in vote:
                continue
            target_id = vote.get("target_id")
            target = targets_by_id.get(target_id)
            if target is None or type(vote.get("admit")) is not bool:
                continue
            vote["repair_fields"] = [] if vote["admit"] else [
                "governing_bindings" if "governing_bindings" in target else "answer_components"
            ]
    completed["target_context_verdicts"] = [
        {
            "target_id": target_id,
            "axes": {axis: "covered" for axis in _TARGET_CONTEXT_AXES},
            "candidates": {"applies": [], "ambiguous": [], "not_applicable":
                list(request.get("target_context_candidates", {}).get(target_id, []))},
        }
        for target_id in target_ids
    ]
    return completed


def parse_canned_source_plan_response(
    parser: Any, serialized_response: str, messages: Any,
) -> Any:
    """Parse one fake response, adapting only the exact current AUDIT request.

    This is intentionally a call-site helper rather than a parser monkeypatch.
    Malformed JSON, malformed legacy audits, and responses with explicit context
    transport are delegated unchanged to the supplied parser.
    """
    from app.modules.ai.source_assessment_plan import AUDIT

    # Legacy scripted course tests also pass critic replies through this
    # call-site adapter. Supply only the new synthetic contract metadata;
    # explicit semantic negatives/missing-field lifecycle tests stay untouched.
    if isinstance(messages, list) and messages and isinstance(messages[-1], dict):
        try:
            request = json.loads(messages[-1].get("content", ""))
            response = json.loads(serialized_response)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        else:
            if isinstance(request, dict) and request.get("task") in {
                "lesson_assessment_review", "lesson_assessment_counterexample",
            }:
                from tests.unit.component_contract_fixture import complete_mock_component_fulfillments

                return parser(json.dumps(complete_mock_component_fulfillments(request, response), ensure_ascii=False))

    if (
        not isinstance(messages, list)
        or len(messages) < 2
        or not isinstance(messages[0], dict)
        or messages[0].get("content") != AUDIT
        or not isinstance(messages[-1], dict)
    ):
        return parser(serialized_response)
    try:
        response = json.loads(serialized_response)
        request = json.loads(messages[-1].get("content", ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return parser(serialized_response)
    adapted = with_canned_complete_target_context_audit(response, request)
    if adapted is response:
        return parser(serialized_response)
    return parser(json.dumps(adapted, ensure_ascii=False))
