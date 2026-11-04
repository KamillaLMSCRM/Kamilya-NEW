"""Unselected owned V3 count-before-claim building block for direct Luna."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from app.modules.ai.direct_luna_responses_client import DirectLunaResponsesClient, ResponsesCountTimeoutError
from app.modules.ai.managed_luna_client import ManagedLunaClient
from app.modules.ai.v3.cooperative_budget import PreclaimYieldError, active_budget
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.owned_stage_inspection import inspect_owned_stage
from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
from app.modules.ai.v3.pending_stage_transactions import _locked_job, verify_repair_slot, verify_source_safely


async def run_direct_owned_stage(
    *,
    journal: PendingStageJournal,
    client: DirectLunaResponsesClient | ManagedLunaClient,
    plan: dict[str, Any],
    result_key: str,
    claim_key: str,
    validate_value: Callable[[dict[str, Any]], dict[str, Any]],
    validate_response: Callable[[Any], dict[str, Any]],
    messages: list[dict[str, str]],
    max_output_tokens: int,
    _owned_claim_guard: Callable[[Any, Any, dict[str, Any]], Awaitable[bool]] | None = None,
    response_format: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replay before preparation/claim; only the direct API performs a trusted token count."""
    if type(journal) is not PendingStageJournal or type(client) not in (DirectLunaResponsesClient, ManagedLunaClient):
        raise ValueError("direct_owned_stage_type_invalid")
    if not callable(journal.verify_source):
        raise ValueError("direct_owned_source_verifier_required")
    original_validate = validate_value
    expected_model = client.model if type(client) is ManagedLunaClient else "gpt-6-luna"
    from app.modules.ai.v3.stage_checkpoint import _digest

    if response_format is not None:
        from app.modules.ai.v3.response_contracts import response_contract

        kind = response_contract(response_format)
        auxiliary = kind is not None and kind.startswith("aux:")
        diversity_author = (kind == "diversity_author" and plan.get("stage") == "repair"
                            and _owned_claim_guard is not None)
        identity = plan.get("identity")
        lesson = (
            kind == "lesson"
            and plan.get("stage") == "lesson"
            and plan.get("request_sha256") == _digest([messages, response_format])
        )
        extraction = (
            kind == "extraction"
            and plan.get("schema") == "v3-rule-extraction-checkpoint-v1"
            and isinstance(identity, dict)
            and identity.get("prompt_sha256") == _digest([messages, response_format])
        )
        batch_review = (
            kind in {"batch_review", "batch_review_buckets"}
            and plan.get("stage") == "review"
            and str(plan.get("group_id", "")).startswith("batched-review:")
            and plan.get("request_sha256") == _digest([messages, response_format])
        )
        practical = (
            (kind == "practical_source_read" and plan.get("stage") == "review"
             and str(plan.get("group_id", "")).startswith("practical:source-read:"))
            or
            (kind == "practical_source_audit" and plan.get("stage") == "review"
             and str(plan.get("group_id", "")).startswith("practical:source-audit:"))
            or             (kind == "practical_course" and plan.get("stage") == "lesson"
             and str(plan.get("group_id", "")).startswith("practical:author:"))
            or (kind == "practical_review" and plan.get("stage") == "review"
                and str(plan.get("group_id", "")).startswith("practical:review:"))
            or (kind == "practical_arbitration" and plan.get("stage") == "review"
                and str(plan.get("group_id", "")).startswith("practical:arbitrate:"))
            or (kind == "practical_patch" and plan.get("stage") == "repair"
                and str(plan.get("group_id", "")).startswith("practical:repair:"))
        ) and plan.get("request_sha256") == _digest([messages, response_format])
        supported_client = type(client) is ManagedLunaClient or (
            type(client) is DirectLunaResponsesClient and (
                kind == "batch_review_buckets" and batch_review or auxiliary or diversity_author or practical)
        )
        auxiliary_stage = "review" if kind in {"aux:citation_review", "aux:diversity_review"} else "repair"
        auxiliary_plan = ((auxiliary and plan.get("stage") == auxiliary_stage or diversity_author)
                          and plan.get("request_sha256") == _digest([messages, response_format]))
        if not supported_client or not (lesson or extraction or batch_review or auxiliary_plan or practical):
            raise ValueError("managed_structured_plan_invalid")

    def validate_with_metadata(value: dict[str, Any]) -> dict[str, Any]:
        from app.modules.ai.v3.stage_checkpoint import _validate_direct_metadata

        _validate_direct_metadata(value)
        metadata = value.get("direct_metadata")
        if (
            isinstance(metadata, dict)
            and metadata.get("model") != expected_model
            or type(client) is ManagedLunaClient
            and metadata is None
        ):
            raise ValueError("owned_luna_metadata_route_mismatch")
        return original_validate(value)

    verify_source = journal.verify_source
    if _owned_claim_guard is not None:
        if not callable(_owned_claim_guard):
            raise ValueError("direct_owned_guard_invalid")
        base_verify = verify_source

        async def guarded(session: Any, job: Any, checked_plan: dict[str, Any]) -> bool:
            return (
                await base_verify(session, job, checked_plan) is True
                and await _owned_claim_guard(session, job, checked_plan) is True
            )

        verify_source = guarded
    inspection = await inspect_owned_stage(
        journal=journal,
        user_id=journal.user_id,
        plan=plan,
        result_key=result_key,
        claim_key=claim_key,
        validate=validate_with_metadata,
        verify_source=verify_source,
    )
    if (
        journal.completed_extraction_parent_job_id is not None
        and plan.get("schema") == "v3-rule-extraction-checkpoint-v1"
    ):
        if type(client) is not ManagedLunaClient:
            raise ExtractionOutcomeUnknownError("v3_extraction_reuse_route_invalid")
        from app.modules.ai.v3.completed_extraction_reuse import reuse_completed_extraction

        return await reuse_completed_extraction(journal, plan, journal.completed_extraction_parent_job_id)

    if inspection.decision == "replay":
        if inspection.result is None:
            raise ValueError("direct_owned_replay_invalid")
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

    budget = active_budget.get()
    if budget is not None:
        budget.before_count(generation_seconds=client.generation_deadline_seconds)
    try:
        capability = await client.prepare(
            messages,
            max_output_tokens=max_output_tokens,
            ownership_checkpoint=checkpoint,
            **(
                {"response_format": response_format}
                if response_format is not None and type(client) is ManagedLunaClient
                else {}
            ),
        )
    except ResponsesCountTimeoutError as exc:
        # Counting cannot generate a lesson. There is still no pending claim.
        raise PreclaimYieldError("generation_count_deadline_exhausted") from exc
    metadata: dict[str, Any] = {}
    completed_response: Any = None

    def completed_rejection(phase: str, cause: Exception) -> Any:
        from app.modules.ai.managed_response_rejection import ManagedResponsesResult

        return (
            completed_response.rejection_for(phase, cause)
            if type(completed_response) is ManagedResponsesResult
            else None
        )

    try:
        if budget is not None:
            budget.before_claim(generation_seconds=client.generation_deadline_seconds)

        async def invoke() -> dict[str, Any]:
            nonlocal claimed, completed_response
            claimed = True
            result = await client.invoke(
                capability,
                tenant_id=UUID(journal.tenant_id),
                user_id=journal.user_id,
                job_id=journal.job_id,
                ownership_checkpoint=checkpoint,
                stage_id=_digest(plan),
            )
            completed_response = result
            if result.model != expected_model:
                raise ValueError("owned_luna_metadata_route_mismatch")
            metadata.update(
                {
                    "model": result.model,
                    "usage": {
                        "input_tokens": result.usage.input_tokens,
                        "output_tokens": result.usage.output_tokens,
                        "cached_input_tokens": result.usage.cached_input_tokens,
                        "reasoning_tokens": result.usage.reasoning_tokens,
                    },
                }
            )
            return result.content

        return await journal.run_pending(
            plan=plan,
            result_key=result_key,
            claim_key=claim_key,
            validate_value=validate_with_metadata,
            validate_response=validate_response,
            invoke=invoke,
            _owned_claim_guard=_owned_claim_guard,
            _direct_metadata=lambda: metadata,
            _completed_response=completed_rejection,
        )
    finally:
        client.discard(capability)
