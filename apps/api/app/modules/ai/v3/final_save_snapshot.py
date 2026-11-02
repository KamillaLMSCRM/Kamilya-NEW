"""Unwired final-output snapshot contract; caller must establish durable custody.

This pure codec neither authenticates a job nor writes a checkpoint. A future
owned transaction must atomically persist this payload with the lifecycle fence.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, cast

from app.modules.ai.v3.final_save_contract import (
    FinalSaveContractError,
    _digest,
    _validated_intent,
    output_digest,
)

POLICY = "v3-final-output-snapshot-v1"


def make_snapshot(state: Any, intent: dict[str, Any]) -> dict[str, Any]:
    """Freeze validated output and full intent; no caller-provided digest is trusted."""
    _validated_intent(intent)
    if state.job_id != intent["job_id"] or state.source_document_ids != [d["doc_id"] for d in intent["documents"]]:
        raise FinalSaveContractError("v3_final_snapshot_scope_invalid")
    digest = output_digest(structure=state.structure, content=state.content, assessment=state.assessment,
        source_document_ids=state.source_document_ids, source_strategy=state.source_strategy,
        source_combination_goal=state.source_combination_goal, source_analysis=state.source_analysis,
        source_review_required=state.server_source_review_required, reuse_reason=state.reuse_reason)
    if digest != intent["output_digest"]:
        raise FinalSaveContractError("v3_final_snapshot_output_invalid")
    output = {"policy": "v3-final-output-v1", "structure": asdict(state.structure),
        "content": asdict(state.content), "assessment": asdict(state.assessment),
        "source_document_ids": state.source_document_ids, "source_strategy": state.source_strategy,
        "source_combination_goal": state.source_combination_goal, "source_analysis": state.source_analysis,
        "source_review_required": state.server_source_review_required, "reuse_reason": state.reuse_reason}
    return cast(dict[str, Any], json.loads(json.dumps({"policy": POLICY, "intent": intent, "output": output},
                                                       ensure_ascii=False, allow_nan=False)))


def validate_snapshot(snapshot: Any, *, expected_intent_digest: str) -> bool:
    """Validate bytes' identities, never their ownership or source freshness."""
    try:
        if not isinstance(snapshot, dict) or set(snapshot) != {"policy", "intent", "output"}:
            return False
        intent = _validated_intent(snapshot["intent"])
        output = snapshot["output"]
        return (snapshot["policy"] == POLICY and intent["intent_digest"] == expected_intent_digest
            and isinstance(output, dict) and set(output) == {"policy", "structure", "content", "assessment",
                "source_document_ids", "source_strategy", "source_combination_goal", "source_analysis",
                "source_review_required", "reuse_reason"}
            and output["policy"] == "v3-final-output-v1"
            and output["source_document_ids"] == [d["doc_id"] for d in intent["documents"]]
            and _digest(output) == intent["output_digest"])
    except (FinalSaveContractError, KeyError, TypeError, ValueError):
        return False
