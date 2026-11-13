"""Retain one private rejected HTTP response without accepting or unlocking it.

Inherits owned checkpoint storage/RLS/retention. Only a receipt reference enters
AIJob.result; raw bytes never enter job DTOs, course content or usage accounting.
"""
from __future__ import annotations

import re
from typing import Any

from app.modules.ai.generation_checkpoint import PlannedLesson
from app.modules.ai.lesson_cycle import POLICY_VERSION
from app.modules.ai.managed_response_rejection import _PHASES as MANAGED_RESPONSE_PHASES
from app.modules.ai.managed_response_rejection import ManagedResponseRejectedError
from app.modules.ai.source_assessment_plan import PLAN_POLICY
from app.modules.ai.v3.pending_stage_transactions import (
    _locked_job,
    _owner,
    checked_entries,
    verify_repair_slot,
    verify_source_safely,
)
from app.modules.ai.v3.rejected_artifact import _PHASES as NATIVE_ARTIFACT_PHASES
from app.modules.ai.v3.stage_checkpoint import _digest

KEY = "v3_managed_response_quarantine"
POLICY = "managed-response-quarantine-v1"


def _valid_reference(digest: str, value: Any) -> bool:
    if (not isinstance(value, dict) or value.get("stage_sha256") != digest
            or value.get("checkpoint_key") != private_key(digest)
            or value.get("accepted") is not False
            or not isinstance(value.get("phase"), str)
            or value.get("phase") not in MANAGED_RESPONSE_PHASES | NATIVE_ARTIFACT_PHASES
            or type(value.get("byte_count")) is not int or value["byte_count"] < 0
            or not isinstance(value.get("body_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", value["body_sha256"]) is None
            or not isinstance(value.get("route_fingerprint"), str)
            or re.fullmatch(r"[0-9a-f]{64}", value["route_fingerprint"]) is None):
        return False
    if value.get("complete_http_response") is True:
        wire = value.get("wire_request_sha256")
        return (value["phase"] in MANAGED_RESPONSE_PHASES
                and type(value.get("status")) is int and value["status"] == 200 and isinstance(wire, str)
                and re.fullmatch(r"[0-9a-f]{64}", wire) is not None)
    request = value.get("request_sha256")
    return (value.get("complete_http_response") is False
            and value["phase"] in NATIVE_ARTIFACT_PHASES
            and value.get("capture_kind") == "model_content_text" and value.get("status") is None
            and isinstance(request, str) and re.fullmatch(r"[0-9a-f]{64}", request) is not None)


def private_key(stage: str) -> str:
    return "v3-managed-quarantine:" + stage


def private_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {"policy": POLICY, "accepted": False, "stage_plan": plan}


async def retain_managed_rejection(*, journal: Any, plan: dict[str, Any], result_key: str, claim_key: str,
                                   marker: dict[str, str], rejection: ManagedResponseRejectedError,
                                   verify_source: Any) -> None:
    _owner(plan, journal)
    if type(rejection) is not ManagedResponseRejectedError or not callable(verify_source):
        raise ValueError("managed_quarantine_unverified")
    digest = _digest(plan)
    identity = plan.get("identity")
    route = plan.get("route_fingerprint") or (identity.get("route_fingerprint") if isinstance(identity, dict) else None)
    if not isinstance(route, str):
        raise ValueError("managed_quarantine_route_invalid")
    receipt = {**rejection.checked_receipt(tenant_id=journal.tenant_id, user_id=journal.user_id,
        job_id=journal.job_id, stage=digest, route_fingerprint=route),
        "stage_sha256": digest, "route_fingerprint": route}
    await _retain(journal=journal, plan=plan, result_key=result_key, claim_key=claim_key,
                  marker=marker, verify_source=verify_source, receipt=receipt, native=False)


async def retain_native_rejection(*, journal: Any, plan: dict[str, Any], result_key: str, claim_key: str,
                                  marker: dict[str, str], rejection: Any, verify_source: Any) -> None:
    from app.modules.ai.v3.rejected_artifact import ModelArtifactRejectedError
    _owner(plan, journal)
    if type(rejection) is not ModelArtifactRejectedError or not callable(verify_source):
        raise ValueError("native_quarantine_unverified")
    identity = plan.get("identity")
    route = plan.get("route_fingerprint") or (identity.get("route_fingerprint") if isinstance(identity, dict) else None)
    request = plan.get("request_sha256") or (identity.get("prompt_sha256") if isinstance(identity, dict) else None)
    expected = journal.expected_native_profile
    if not isinstance(expected, dict) or not isinstance(route, str) or route != expected.get("fingerprint") or not isinstance(request, str):
        raise ValueError("native_quarantine_profile_invalid")
    receipt = {**rejection.checked_receipt(job_id=journal.job_id, route=route, request=request),
               "stage_sha256": _digest(plan), "route_fingerprint": route}
    await _retain(journal=journal, plan=plan, result_key=result_key, claim_key=claim_key,
                  marker=marker, verify_source=verify_source, receipt=receipt, native=True)


async def _retain(*, journal: Any, plan: dict[str, Any], result_key: str, claim_key: str,
                  marker: dict[str, str], verify_source: Any, receipt: dict[str, Any], native: bool) -> None:
    digest = _digest(plan)
    async with journal.sessions() as session:
        job = await _locked_job(session, journal, journal.user_id)
        if native:
            from app.modules.ai.v3.native_profile_binding import KEY as PROFILE_KEY
            from app.modules.ai.v3.revision_policy import POLICY as REVISION_POLICY
            from app.modules.ai.v3.revision_policy import read_policy
            if (journal.expected_revision_policy != REVISION_POLICY
                    or read_policy(job.params.get("source_analysis")) != REVISION_POLICY
                    or job.result.get(PROFILE_KEY) != journal.expected_native_profile):
                raise ValueError("native_quarantine_profile_changed")
        expected = {"claim_key": claim_key, "result_key": result_key, "token": marker.get("claim_token")}
        if marker.get("identity") != digest or checked_entries(job.result).get(digest) != expected:
            raise ValueError("managed_quarantine_marker_unverified")
        verify_repair_slot(job, plan, required=True)
        if await journal.read_owned_value_in_session(session, claim_key, plan) != marker:
            raise ValueError("managed_quarantine_claim_unverified")
        await verify_source_safely(verify_source, session, job, plan)
        previous = job.result.get(KEY, {"policy": POLICY, "entries": {}})
        if (not isinstance(previous, dict) or set(previous) != {"policy", "entries"}
                or previous.get("policy") != POLICY or not isinstance(previous.get("entries"), dict)
            or not all(isinstance(key, str) and re.fullmatch(r"[0-9a-f]{64}", key) is not None
                           and _valid_reference(key, value)
                           for key, value in previous["entries"].items())):
            raise ValueError("managed_quarantine_existing_invalid")
        entries = dict(previous["entries"])
        key = private_key(digest)
        reference = {name: value for name, value in receipt.items() if name != "raw_base64"}
        reference["checkpoint_key"] = key
        if digest in entries and entries[digest] != reference:
            raise ValueError("managed_quarantine_receipt_conflict")
        quarantine_plan = private_plan(plan)
        repo = journal.repository
        await repo.create_plan(session, tenant_id=journal.tenant_id, generation_key=journal._owned_key(key),
            plan_revision=f"{PLAN_POLICY}/{POLICY_VERSION}", source_job_id=journal.job_id,
            plan_payload=quarantine_plan, lessons=(PlannedLesson("cycle", "lesson", 0, 0),))
        fields = dict(tenant_id=journal.tenant_id, generation_key=journal._owned_key(key),
                      module_key="cycle", lesson_key="lesson")
        existing = await journal.read_owned_value_in_session(session, key, quarantine_plan)
        if existing is not None and existing != receipt:
            raise ValueError("managed_quarantine_checkpoint_conflict")
        if existing is None:
            await repo.checkpoint_content(session, **fields, content_payload={"accepted": False})
            await repo.checkpoint_review(session, **fields, review_payload={"policy": POLICY, "accepted": False})
            await repo.checkpoint_assessment(session, **fields, assessment_payload=receipt)
        if await journal.read_owned_value_in_session(session, key, quarantine_plan) != receipt:
            raise ValueError("managed_quarantine_checkpoint_unverified")
        entries[digest] = reference
        job.result = {**job.result, KEY: {"policy": POLICY, "entries": entries}}
        # The unresolved pending claim and all completed work are preserved.
        await session.commit()
