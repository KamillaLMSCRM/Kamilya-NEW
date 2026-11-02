"""Persist bounded rejected-response evidence; never unlock a pending provider call."""
from __future__ import annotations

from typing import Any

from app.modules.ai.direct_luna_responses_client import ResponsesRejectedError
from app.modules.ai.v3.pending_stage_transactions import (
    _locked_job,
    _owner,
    checked_entries,
    verify_repair_slot,
    verify_source_safely,
)
from app.modules.ai.v3.stage_checkpoint import _digest

KEY = "v3_response_rejections"
POLICY = "v3-response-rejection-receipt-v1"


async def retain_rejection(*, journal: Any, plan: dict[str, Any], result_key: str, claim_key: str,
                           marker: dict[str, str], rejection: ResponsesRejectedError,
                           verify_source: Any) -> None:
    _owner(plan, journal)
    if type(rejection) is not ResponsesRejectedError or not callable(verify_source):
        raise ValueError("v3_rejection_unverified")
    digest = _digest(plan)
    receipt = rejection.checked_receipt(tenant_id=journal.tenant_id, user_id=journal.user_id,
                                       job_id=journal.job_id, stage=digest)
    async with journal.sessions() as session:
        job = await _locked_job(session, journal, journal.user_id)
        expected = {"claim_key": claim_key, "result_key": result_key, "token": marker.get("claim_token")}
        if marker.get("identity") != digest or checked_entries(job.result).get(digest) != expected:
            raise ValueError("v3_rejection_marker_unverified")
        verify_repair_slot(job, plan, required=True)
        if await journal.read_owned_value_in_session(session, claim_key, plan) != marker:
            raise ValueError("v3_rejection_claim_unverified")
        await verify_source_safely(verify_source, session, job, plan)
        previous = job.result.get(KEY, {"policy": POLICY, "entries": {}})
        if (not isinstance(previous, dict) or set(previous) != {"policy", "entries"}
                or previous.get("policy") != POLICY or not isinstance(previous.get("entries"), dict)):
            raise ValueError("v3_rejection_receipts_invalid")
        entries = dict(previous["entries"])
        if digest in entries and entries[digest] != receipt:
            raise ValueError("v3_rejection_receipt_conflict")
        entries[digest] = receipt
        job.result = {**job.result, KEY: {"policy": POLICY, "entries": entries}}
        # Pending marker, claim, result checkpoint and job status deliberately unchanged.
        await session.commit()
