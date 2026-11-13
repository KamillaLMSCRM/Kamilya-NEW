"""Unselected owned V3 count-before-claim building block for direct Luna."""

from __future__ import annotations

import re
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
from app.modules.ai.v3.practical_author_transport import PracticalAuthorArtifact


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
    author_custody: Callable[[Any], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Replay before preparation/claim; only the direct API performs a trusted token count."""
    if type(journal) is not PendingStageJournal or type(client) not in (DirectLunaResponsesClient, ManagedLunaClient):
        raise ValueError("direct_owned_stage_type_invalid")
    if not callable(journal.verify_source):
        raise ValueError("direct_owned_source_verifier_required")
    original_validate = validate_value
    expected_model = client.model if type(client) is ManagedLunaClient else "gpt-6-luna"
    from app.modules.ai.v3.stage_checkpoint import _digest

    focused_group = str(plan.get('group_id', '')).startswith('practical:focused:')
    simple_group = str(plan.get('group_id', '')).startswith('practical:simple:')
    if (focused_group or simple_group) and response_format is None:
        raise ValueError('managed_structured_plan_invalid')
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
            (kind == "practical_option_predicates" and plan.get("stage") == "review"
             and str(plan.get("group_id", "")).startswith("practical:review:option-predicates:v33:"))
            or (kind == "practical_compact_editorial_review" and plan.get("stage") == "review"
             and str(plan.get("group_id", "")).startswith(("practical:editorial:review:v33:", "practical:editorial:review:v34:")))
            or (kind == "practical_compact_editorial_verification" and plan.get("stage") == "review"
             and str(plan.get("group_id", "")).startswith(("practical:editorial:verify:v33:", "practical:editorial:verify:v34:")))
            or
            (kind == "practical_source_completeness" and plan.get("stage") == "review"
             and str(plan.get("group_id", "")).startswith("practical:source-semantics:complete:v33:"))
            or
            (kind == "practical_source_semantics" and plan.get("stage") == "review"
             and str(plan.get("group_id", "")).startswith("practical:source-semantics:read:v33:"))
            or (kind == "practical_source_semantics_verification" and plan.get("stage") == "review"
             and str(plan.get("group_id", "")).startswith("practical:source-semantics:verify:v33:"))
            or (kind == "practical_rule_editorial_review" and plan.get("stage") == "review"
             and str(plan.get("group_id", "")).startswith(("practical:editorial:review:v33:", "practical:editorial:review:v34:")))
            or (kind == "practical_rule_editorial_verification" and plan.get("stage") == "review"
             and str(plan.get("group_id", "")).startswith(("practical:editorial:verify:v33:", "practical:editorial:verify:v34:")))
            or (kind == "practical_source_read" and plan.get("stage") == "review"
             and str(plan.get("group_id", "")).startswith("practical:source-read:"))
            or
            (kind == "practical_source_audit" and plan.get("stage") == "review"
             and str(plan.get("group_id", "")).startswith("practical:source-audit:"))
            or             (kind == "practical_course" and plan.get("stage") == "lesson"
             and str(plan.get("group_id", "")).startswith("practical:author:"))
            or (kind == "practical_review" and plan.get("stage") == "review"
                and str(plan.get("group_id", "")).startswith("practical:review:"))
            or (kind == "practical_curriculum" and plan.get("stage") == "review"
                and str(plan.get("group_id", "")).startswith("practical:source-curriculum:"))
            or (kind == "practical_curriculum_bank" and plan.get("stage") == "review"
                and str(plan.get("group_id", "")).startswith("practical:review:bank:"))
            or (kind == "practical_source_core" and plan.get("stage") == "lesson"
                and str(plan.get("group_id", "")).startswith("practical:source-core:author:"))
            or (kind == "practical_source_core_editor" and plan.get("stage") == "review"
                and str(plan.get("group_id", "")).startswith("practical:source-core:editor:"))
            or (kind == "practical_editorial_review" and plan.get("stage") == "review"
                and str(plan.get("group_id", "")).startswith(("practical:editorial:review:v31:", "practical:editorial:review:v33:", "practical:editorial:review:v34:")))
            or (kind == "practical_editorial_verification" and plan.get("stage") == "review"
                and str(plan.get("group_id", "")).startswith(("practical:editorial:verify:v33:", "practical:editorial:verify:v34:")))
            or (kind == "practical_editorial_revision" and plan.get("stage") == "repair"
                and str(plan.get("group_id", "")).startswith(("practical:editorial:revision:v31:", "practical:editorial:revision:v33:")))
            or (kind == "practical_arbitration" and plan.get("stage") == "review"
                and str(plan.get("group_id", "")).startswith("practical:arbitrate:"))
            or (kind == "practical_question_context" and plan.get("stage") == "review"
                and str(plan.get("group_id", "")).startswith("practical:context:"))
            or (kind == "practical_patch" and plan.get("stage") == "repair"
                and str(plan.get("group_id", "")).startswith("practical:repair:"))
        ) and plan.get("request_sha256") == _digest([messages, response_format])
        if focused_group or simple_group:
            if simple_group:
                from app.modules.ai.v3.simple_course_service import simple_stage_allowed as stage_allowed
            else:
                from app.modules.ai.v3.focused_stage_guard import focused_stage_allowed as stage_allowed

            allowed = (getattr(journal, 'review_policy_bound', False) is True
                and stage_allowed(plan.get('stage'), plan.get('group_id'), response_format,
                    policy=getattr(journal, 'expected_review_policy', None), validator=validate_response)
                and plan.get('schema') == 'v3-stage-checkpoint-v1'
                and plan.get('tenant_id') == journal.tenant_id and plan.get('job_id') == journal.job_id
                and all(type(plan.get(key)) is str and re.fullmatch(r'[0-9a-f]{64}', plan[key])
                        for key in ('source_sha256', 'route_fingerprint'))
                and plan.get('request_sha256') == _digest([messages, response_format]))
            if not allowed:
                raise ValueError("managed_structured_plan_invalid")
            practical = True
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

    if inspection.decision == "replay_completed":
        from app.modules.ai.delivery_ownership import delivery_id
        from app.modules.ai.v3.direct_usage_metadata import checked_metadata
        from app.modules.ai.v3.pending_stage_transactions import finalize_pending
        from app.modules.ai.v3.retained_author_replay import AUTHORIZATION_KEY, AUTHORIZATION_POLICY, owned_candidate

        candidate = inspection.result
        if type(client) is not ManagedLunaClient or not isinstance(candidate, dict):
            raise ExtractionOutcomeUnknownError("v3_retained_replay_unverified")

        async def replay_checkpoint() -> bool:
            async with journal.sessions() as session:
                job = await _locked_job(session, journal, journal.user_id)
                current = await owned_candidate(session, job)
                params = job.params if isinstance(job.params, dict) else {}
                marker = params.get(AUTHORIZATION_KEY)
                if (current is None or current != candidate or marker != {
                        "policy": AUTHORIZATION_POLICY, "stage": candidate["stage"],
                        "body_sha256": candidate["body_sha256"], "pending_sha256": candidate["pending_sha256"],
                        "delivery_id": delivery_id.get()}):
                    raise ExtractionOutcomeUnknownError("v3_retained_replay_unverified")
                await verify_source_safely(verify_source, session, job, plan)
            return True

        capability: object | None = None
        try:
            capability = await client.prepare(messages, max_output_tokens=max_output_tokens,
                                              ownership_checkpoint=replay_checkpoint, response_format=response_format)
            result = await client.replay_completed(capability, receipt=candidate["receipt"],
                tenant_id=UUID(journal.tenant_id), user_id=journal.user_id, job_id=journal.job_id,
                stage_id=_digest(plan), ownership_checkpoint=replay_checkpoint, stage_plan=plan)
            response = validate_response(result.content)
            replay_metadata = checked_metadata({"model": result.model, "usage": {
                "input_tokens": result.usage.input_tokens, "output_tokens": result.usage.output_tokens,
                "cached_input_tokens": result.usage.cached_input_tokens, "reasoning_tokens": result.usage.reasoning_tokens}})
            value = {"identity": _digest(plan), "response": response, "response_sha256": _digest(response),
                     "direct_metadata": replay_metadata, "direct_metadata_sha256": _digest(replay_metadata)}
            custody_value = author_custody(result.content) if author_custody is not None else None
            if custody_value is not None:
                value['author_custody'] = custody_value
            else:
                from app.modules.ai.v3.stage_checkpoint import ordered_response_fields
                value.update(ordered_response_fields(response))
            audit = {"policy": AUTHORIZATION_POLICY, "stage_sha256": _digest(plan),
                     "body_sha256": candidate["body_sha256"],
                     "wire_request_sha256": candidate["receipt"]["wire_request_sha256"], "model": result.model}
            return await finalize_pending(journal=journal, user_id=journal.user_id, plan=plan,
                result_key=result_key, claim_key=claim_key, marker=candidate["marker"], value=value,
                validate=validate_with_metadata, verify_source=verify_source, replay_audit=audit)
        except Exception:
            raise ExtractionOutcomeUnknownError("v3_retained_replay_unverified") from None
        finally:
            if capability is not None:
                client.discard(capability)

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

        async def invoke() -> dict[str, Any] | PracticalAuthorArtifact:
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
            author_custody=author_custody,
        )
    finally:
        client.discard(capability)
