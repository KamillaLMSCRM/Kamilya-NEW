"""Unwired pure contract for a future owned V3 final-save transaction.

This module does not authenticate, lock, write, reconcile or prove persisted
artifacts. Only a trusted server transaction may supply these values and use
these transitions after checking the actual job, delivery and source rows.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from typing import Any
from uuid import UUID, uuid4

from app.modules.ai.v3.pending_stage_transactions import KEY as PENDING_KEY
from app.modules.ai.v3.qa_luna_pending_policy import OWNED_POLICIES

INTENT_KEY = "v3_final_save_intent"
RECEIPT_KEY = "v3_final_save_receipt"
INTENT_POLICY = "v3-final-save-intent-v1"
FENCE_POLICY = "v3-final-save-fence-v1"
RECEIPT_POLICY = "v3-final-save-receipt-v1"
SOURCE_FIRST_KEYS = ("source_first_commit_intent", "source_first_partitioned_commit_intent")


class FinalSaveContractError(ValueError):
    """A final-save identity or state is unresolved; caller must hold."""


def _canonical_uuid(value: str) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def _digest(value: Any) -> str:
    try:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise FinalSaveContractError("v3_final_payload_invalid") from exc
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sha(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None



def output_digest(*, structure: Any, content: Any, assessment: Any,
                  source_document_ids: list[str], source_strategy: str,
                  source_combination_goal: str, source_analysis: dict[str, Any],
                  source_review_required: bool, reuse_reason: str | None) -> str:
    """Hash the proposed save inputs; caller freezes them before intent.

    This digest does not prove the database wrote those inputs or that source
    and route ownership were checked. Noncanonical values fail closed.
    """
    from app.modules.ai.architect_schema import CourseStructure
    from app.modules.ai.assessment_schema import CourseAssessment
    from app.modules.ai.writer_schema import CourseContent

    if (not isinstance(structure, CourseStructure) or not isinstance(content, CourseContent)
            or not isinstance(assessment, CourseAssessment) or not isinstance(source_document_ids, list)
            or not source_document_ids or not all(_canonical_uuid(item) for item in source_document_ids)
            or len(set(source_document_ids)) != len(source_document_ids)
            or not isinstance(source_strategy, str) or not isinstance(source_combination_goal, str)
            or not isinstance(source_analysis, dict) or type(source_review_required) is not bool
            or not (reuse_reason is None or isinstance(reuse_reason, str))):
        raise FinalSaveContractError("v3_final_output_invalid")
    return _digest({"policy": "v3-final-output-v1", "structure": asdict(structure), "content": asdict(content),
                    "assessment": asdict(assessment), "source_document_ids": source_document_ids,
                    "source_strategy": source_strategy, "source_combination_goal": source_combination_goal,
                    "source_analysis": source_analysis, "source_review_required": source_review_required,
                    "reuse_reason": reuse_reason})

def make_intent(*, tenant_id: str, user_id: str, job_id: str, delivery_id: str,
                route_policy: str, route_fingerprint: str, documents: list[dict[str, str]],
                output_digest: str) -> dict[str, Any]:
    """Construct a content-free identity from independently authenticated inputs."""
    if (not all(_canonical_uuid(value) for value in (tenant_id, user_id, job_id))
            or not isinstance(delivery_id, str) or not delivery_id.strip()
            or route_policy not in OWNED_POLICIES or not _sha(route_fingerprint)
            or not _sha(output_digest) or not isinstance(documents, list) or not documents):
        raise FinalSaveContractError("v3_final_identity_invalid")
    ids: list[str] = []
    for doc in documents:
        if (not isinstance(doc, dict) or set(doc) != {"doc_id", "revision", "text_sha256"}
                or not _canonical_uuid(doc["doc_id"]) or not isinstance(doc["revision"], str)
                or not re.fullmatch(r"document:[0-9a-f]{64}", doc["revision"])
                or not _sha(doc["text_sha256"])):
            raise FinalSaveContractError("v3_final_source_invalid")
        ids.append(doc["doc_id"])
    if len(ids) != len(set(ids)):
        raise FinalSaveContractError("v3_final_source_invalid")
    body = {"policy": INTENT_POLICY, "tenant_id": tenant_id, "user_id": user_id, "job_id": job_id,
            "delivery_id": delivery_id, "route_policy": route_policy, "route_fingerprint": route_fingerprint,
            "documents": [dict(doc) for doc in documents], "output_digest": output_digest,
            "attempt_id": uuid4().hex}
    return {**body, "intent_digest": _digest(body)}


def _validated_intent(intent: Any) -> dict[str, Any]:
    keys = {"policy", "tenant_id", "user_id", "job_id", "delivery_id", "route_policy", "route_fingerprint",
            "documents", "output_digest", "attempt_id", "intent_digest"}
    if not isinstance(intent, dict) or set(intent) != keys:
        raise FinalSaveContractError("v3_final_intent_invalid")
    body = {key: value for key, value in intent.items() if key != "intent_digest"}
    if (body["policy"] != INTENT_POLICY or not isinstance(body["attempt_id"], str)
            or not re.fullmatch(r"[0-9a-f]{32}", body["attempt_id"])
            or not all(_canonical_uuid(body[name]) for name in ("tenant_id", "user_id", "job_id"))
            or not isinstance(body["delivery_id"], str) or not body["delivery_id"].strip()
            or body["route_policy"] not in OWNED_POLICIES
            or not _sha(body["route_fingerprint"]) or not _sha(body["output_digest"])
            or not isinstance(body["documents"], list) or not body["documents"]
            or not _sha(intent["intent_digest"]) or _digest(body) != intent["intent_digest"]):
        raise FinalSaveContractError("v3_final_intent_invalid")
    ids = []
    for doc in body["documents"]:
        if (not isinstance(doc, dict) or set(doc) != {"doc_id", "revision", "text_sha256"}
                or not _canonical_uuid(doc["doc_id"]) or not isinstance(doc["revision"], str)
                or not re.fullmatch(r"document:[0-9a-f]{64}", doc["revision"])
                or not _sha(doc["text_sha256"])):
            raise FinalSaveContractError("v3_final_intent_invalid")
        ids.append(doc["doc_id"])
    if len(ids) != len(set(ids)):
        raise FinalSaveContractError("v3_final_intent_invalid")
    return intent


def install_intent(result: Any, intent: dict[str, Any]) -> dict[str, Any]:
    """Produce the prospective locked-row value; presence blocks lifecycle paths."""
    _validated_intent(intent)
    if result is not None and not isinstance(result, dict):
        raise FinalSaveContractError("v3_final_existing_state_unresolved")
    original = dict(result or {})
    if any(key in original for key in (PENDING_KEY, INTENT_KEY, RECEIPT_KEY, *SOURCE_FIRST_KEYS)):
        raise FinalSaveContractError("v3_final_existing_state_unresolved")
    fence = {"policy": FENCE_POLICY, "intent_digest": intent["intent_digest"], "attempt_id": intent["attempt_id"]}
    return {**original, PENDING_KEY: fence, INTENT_KEY: json.loads(json.dumps(intent))}


def resolve_intent(result: Any, intent: dict[str, Any], *, course_id: str, output_digest: str) -> dict[str, Any]:
    """Build a prospective receipt; caller must atomically persist and verify artifacts."""
    _validated_intent(intent)
    if not _canonical_uuid(course_id) or output_digest != intent["output_digest"] or not isinstance(result, dict):
        raise FinalSaveContractError("v3_final_completion_unverified")
    expected = {"policy": FENCE_POLICY, "intent_digest": intent["intent_digest"], "attempt_id": intent["attempt_id"]}
    if (result.get(INTENT_KEY) != intent or result.get(PENDING_KEY) != expected or RECEIPT_KEY in result
            or any(key in result for key in SOURCE_FIRST_KEYS)):
        raise FinalSaveContractError("v3_final_intent_mismatch")
    completed = dict(result)
    del completed[PENDING_KEY]
    del completed[INTENT_KEY]
    completed[RECEIPT_KEY] = {"policy": RECEIPT_POLICY, "intent_digest": intent["intent_digest"],
                              "attempt_id": intent["attempt_id"], "course_id": course_id,
                              "output_digest": output_digest}
    return completed
