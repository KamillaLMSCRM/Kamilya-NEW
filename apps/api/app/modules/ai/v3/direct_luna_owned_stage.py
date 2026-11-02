"""Unselected owned V3 count-before-claim building block for direct Luna."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from app.modules.ai.direct_luna_responses_client import DirectLunaResponsesClient
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.owned_stage_inspection import inspect_owned_stage
from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
from app.modules.ai.v3.pending_stage_transactions import _locked_job, verify_repair_slot, verify_source_safely


async def run_direct_owned_stage(*, journal: PendingStageJournal, client: DirectLunaResponsesClient,
                                 plan: dict[str, Any], result_key: str, claim_key: str,
                                 validate_value: Callable[[dict[str, Any]], dict[str, Any]],
                                 validate_response: Callable[[Any], dict[str, Any]],
                                 messages: list[dict[str, str]], max_output_tokens: int,
                                 _owned_claim_guard: Callable[[Any, Any, dict[str, Any]], Awaitable[bool]] | None = None,
                                 ) -> dict[str, Any]:
    """Inspect and count before claim; trusted caller owns route and source construction."""
    if type(journal) is not PendingStageJournal or type(client) is not DirectLunaResponsesClient:
        raise ValueError('direct_owned_stage_type_invalid')
    if not callable(journal.verify_source):
        raise ValueError('direct_owned_source_verifier_required')
    verify_source = journal.verify_source
    if _owned_claim_guard is not None:
        if not callable(_owned_claim_guard):
            raise ValueError('direct_owned_guard_invalid')
        base_verify = verify_source
        async def guarded(session: Any, job: Any, checked_plan: dict[str, Any]) -> bool:
            return (await base_verify(session, job, checked_plan) is True
                    and await _owned_claim_guard(session, job, checked_plan) is True)
        verify_source = guarded
    inspection = await inspect_owned_stage(journal=journal, user_id=journal.user_id, plan=plan,
        result_key=result_key, claim_key=claim_key, validate=validate_value, verify_source=verify_source)
    if inspection.decision == 'replay':
        if inspection.result is None:
            raise ValueError('direct_owned_replay_invalid')
        return inspection.result

    claimed = False
    async def checkpoint() -> bool:
        async with journal.sessions() as session:
            job = await _locked_job(session, journal, journal.user_id)
            slot_exists = verify_repair_slot(job, plan, required=claimed)
            if slot_exists and not claimed:
                raise ExtractionOutcomeUnknownError("v3_repair_slot_already_claimed")
            await verify_source_safely(verify_source, session, job, plan)
        return True

    capability = await client.prepare(messages, max_output_tokens=max_output_tokens, ownership_checkpoint=checkpoint)
    try:
        async def invoke() -> dict[str, Any]:
            nonlocal claimed
            claimed = True
            result = await client.invoke(capability, tenant_id=UUID(journal.tenant_id), user_id=journal.user_id,
                                         job_id=journal.job_id, ownership_checkpoint=checkpoint)
            return result.content
        return await journal.run_pending(plan=plan, result_key=result_key, claim_key=claim_key,
            validate_value=validate_value, validate_response=validate_response, invoke=invoke,
            _owned_claim_guard=_owned_claim_guard)
    finally:
        client.discard(capability)
