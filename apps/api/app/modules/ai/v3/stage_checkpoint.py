"""Durable request replay for lesson and critic responses; not quality approval."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any, cast
from uuid import uuid4

from app.modules.ai.v3.extraction_checkpoint import ExtractionJournal, ExtractionOutcomeUnknownError


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    ).hexdigest()


def _validate_direct_metadata(value: dict[str, Any]) -> None:
    if "direct_metadata" in value or "direct_metadata_sha256" in value:
        from app.modules.ai.v3.direct_usage_metadata import checked_metadata

        metadata = checked_metadata(value.get("direct_metadata"))
        if value.get("direct_metadata") != metadata or value.get("direct_metadata_sha256") != _digest(metadata):
            raise ValueError("direct_usage_metadata_invalid")


def stage_plan(
    journal: ExtractionJournal,
    *,
    stage: str,
    group_id: str,
    source_sha256: str,
    route_fingerprint: str,
    messages: list[dict[str, str]],
    response_format: dict[str, Any] | None,
) -> dict[str, Any]:
    if stage not in {"lesson", "review", "repair"} or not group_id.strip():
        raise ValueError("v3_stage_identity_invalid")
    if not all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in (source_sha256, route_fingerprint)):
        raise ValueError("v3_stage_identity_invalid")
    return {
        "schema": "v3-stage-checkpoint-v1",
        "tenant_id": journal.tenant_id,
        "job_id": journal.job_id,
        "stage": stage,
        "group_id": group_id,
        "source_sha256": source_sha256,
        "route_fingerprint": route_fingerprint,
        "request_sha256": _digest([messages, response_format]),
    }


async def read_verified_stage_result(journal: ExtractionJournal, plan: dict[str, Any]) -> dict[str, Any]:
    """Read the owned completed stage; a caller-provided response is never evidence."""
    if plan.get("tenant_id") != journal.tenant_id or plan.get("job_id") != journal.job_id:
        raise ValueError("v3_stage_owner_mismatch")
    signature = _digest(plan)
    value = await journal.read_owned_value(f"v3-stage-result:{signature}", plan)
    if not isinstance(value, dict) or value.get("identity") != signature:
        raise ValueError("v3_stage_checkpoint_invalid")
    _validate_direct_metadata(value)
    response = value.get("response")
    if not isinstance(response, dict) or not response or value.get("response_sha256") != _digest(response):
        raise ValueError("v3_stage_checkpoint_invalid")
    if 'author_custody' in value:
        from app.modules.ai.v3.practical_author_transport import validate_author_custody
        # This helper has no request format; it checks internal custody only.
        if not validate_author_custody(value['author_custody'], response):
            raise ValueError("v3_stage_checkpoint_invalid")
    return cast(dict[str, Any], json.loads(json.dumps(response, ensure_ascii=False, allow_nan=False)))


async def stage_once(
    journal: ExtractionJournal,
    *,
    stage: str,
    group_id: str,
    source_sha256: str,
    route_fingerprint: str,
    messages: list[dict[str, str]],
    response_format: dict[str, Any] | None,
    invoke: Callable[[], Awaitable[Any]],
    direct_client: Any = None,
    direct_max_output_tokens: int = 8192,
    response_validator: Callable[[dict[str, Any]], None] | None = None,
    _owned_claim_guard: Callable[[Any, Any, dict[str, Any]], Awaitable[bool]] | None = None,
) -> dict[str, Any]:
    plan = stage_plan(
        journal,
        stage=stage,
        group_id=group_id,
        source_sha256=source_sha256,
        route_fingerprint=route_fingerprint,
        messages=messages,
        response_format=response_format,
    )
    from app.modules.ai.v3.diversity_owned_selection_guard import REPAIR_GROUP_PREFIX, OwnedSelectionGuard

    if group_id.startswith(REPAIR_GROUP_PREFIX):
        if type(_owned_claim_guard) is not OwnedSelectionGuard or not re.fullmatch(
            r"[0-9a-f]{64}", _owned_claim_guard.identity
        ):
            raise ExtractionOutcomeUnknownError("v3_owned_repair_guard_required")
        if (
            stage != "repair"
            or direct_client is None
            or not _owned_claim_guard.review_group_id
            or group_id != REPAIR_GROUP_PREFIX + _owned_claim_guard.review_group_id
        ):
            raise ExtractionOutcomeUnknownError("v3_owned_repair_group_unverified")
        plan["owned_guard_sha256"] = _owned_claim_guard.identity
        plan["repair_attempt_slot"] = _digest(
            {
                "policy": "v3-diversity-repair-slot-v1",
                "tenant_id": journal.tenant_id,
                "job_id": journal.job_id,
                "review_group_id": _owned_claim_guard.review_group_id,
            }
        )
    focused = group_id.startswith("practical:focused:")
    simple = group_id.startswith("practical:simple:")
    if simple:
        from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
        from app.modules.ai.v3.simple_course_service import simple_stage_allowed

        if (type(journal) is not PendingStageJournal or getattr(journal, "review_policy_bound", False) is not True
                or not callable(journal.verify_source)
                or not simple_stage_allowed(stage, group_id, response_format,
                    policy=getattr(journal, "expected_review_policy", None), validator=response_validator)):
            raise ValueError("simple_stage_scope_invalid")
    if focused:
        from app.modules.ai.v3.focused_stage_guard import focused_stage_allowed
        from app.modules.ai.v3.pending_stage_journal import PendingStageJournal

        if (type(journal) is not PendingStageJournal or getattr(journal, "review_policy_bound", False) is not True
                or not callable(journal.verify_source)
                or not focused_stage_allowed(stage, group_id, response_format,
                    policy=getattr(journal, "expected_review_policy", None), validator=response_validator)):
            raise ValueError("focused_stage_scope_invalid")
    if simple:
        from app.modules.ai.v3.explicit_stage_retry import guard_recovery_stage, retry_plan
        await guard_recovery_stage(journal, plan)
        plan = retry_plan(plan, getattr(journal, 'explicit_stage_retries', None))
    signature = _digest(plan)
    result_key, claim_key = f"v3-stage-result:{signature}", f"v3-stage-claim:{signature}"
    from app.modules.ai.v3.practical_author_transport import is_practical_author_stage

    def custody(value: Any) -> dict[str, Any] | None:
        from app.modules.ai.v3.practical_author_transport import (
            PracticalAuthorArtifact,
            author_custody,
        )
        if type(value) is not PracticalAuthorArtifact:
            return None
        if not is_practical_author_stage(stage, group_id):
            raise ValueError('practical_author_stage_invalid')
        return author_custody(value, response_format)

    def validate(value: Any) -> dict[str, Any]:
        from app.modules.ai.v3.practical_author_transport import PracticalAuthorArtifact
        if type(value) is PracticalAuthorArtifact:
            custody(value)
            value = value.normalized_value
        if not isinstance(value, dict) or not value:
            raise ValueError("v3_stage_response_invalid")
        from app.modules.ai.v3.response_contracts import (
            matches_response_contract,
            matches_transport_contract,
            response_contract,
        )

        kind = response_contract(response_format) if response_format is not None else None
        if (response_format is not None and (focused or simple or kind in {"practical_option_predicates", "batch_review_buckets", "diversity_author", "practical_course", "practical_review", "practical_patch", "practical_source_audit", "practical_source_read", "practical_arbitration", "practical_question_context", "practical_curriculum", "practical_curriculum_bank", "practical_source_core", "practical_source_core_editor", "practical_editorial_review", "practical_editorial_revision", "practical_editorial_verification", "practical_source_semantics", "practical_source_semantics_verification", "practical_source_completeness", "practical_compact_editorial_review", "practical_compact_editorial_verification", "practical_rule_editorial_review", "practical_rule_editorial_verification"}
                or kind is not None and kind.startswith("aux:"))):
            valid = matches_response_contract(value, response_format)
            if not valid and response_validator is not None and stage == 'review':
                from app.modules.ai.v3.practical_resolution_completion import is_joint_verification_group
                owned_group = group_id.rsplit(':output=', 1)[0]
                valid = (is_joint_verification_group(owned_group)
                         and matches_transport_contract(value, response_format))
            if not valid:
                raise ValueError("v3_stage_response_shape_invalid")
        try:
            checked = cast(dict[str, Any], json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False)))
        except (TypeError, ValueError) as exc:
            raise ValueError("v3_stage_response_invalid") from exc
        if response_validator is not None:
            response_validator(checked)
        return checked

    async def load_result() -> dict[str, Any] | None:
        value = await journal.read_owned_value(result_key, plan)
        if value is None:
            return None
        if value.get("identity") != signature:
            raise ValueError("v3_stage_checkpoint_invalid")
        response = validate(value.get("response"))
        if 'author_custody' in value:
            from app.modules.ai.v3.practical_author_transport import validate_author_custody
            if not is_practical_author_stage(stage, group_id) or not validate_author_custody(value['author_custody'], response, response_format):
                raise ValueError("v3_stage_checkpoint_invalid")
        if value.get("response_sha256") != _digest(response):
            raise ValueError("v3_stage_checkpoint_invalid")
        return response

    from app.modules.ai.v3.pending_stage_journal import PendingStageJournal

    if isinstance(journal, PendingStageJournal) and type(journal) is not PendingStageJournal:
        raise ValueError("pending_journal_type_invalid")
    if type(journal) is PendingStageJournal:

        def validate_value(value: dict[str, Any]) -> dict[str, Any]:
            _validate_direct_metadata(value)
            if value.get("identity") != signature:
                raise ValueError("v3_stage_checkpoint_invalid")
            response = validate(value.get("response"))
            if 'author_custody' in value:
                from app.modules.ai.v3.practical_author_transport import validate_author_custody
                if not is_practical_author_stage(stage, group_id) or not validate_author_custody(value['author_custody'], response, response_format):
                    raise ValueError("v3_stage_checkpoint_invalid")
            if value.get("response_sha256") != _digest(response):
                raise ValueError("v3_stage_checkpoint_invalid")
            return response

        if direct_client is not None:
            from app.modules.ai.direct_luna_responses_client import DirectLunaResponsesClient
            from app.modules.ai.managed_luna_client import ManagedLunaClient
            from app.modules.ai.v3.author_response_schema import is_lesson_author_response_format
            from app.modules.ai.v3.auxiliary_response_contracts import is_auxiliary_format
            from app.modules.ai.v3.batch_review_response_schema import is_batch_review_response_format
            from app.modules.ai.v3.typed_review_buckets import is_typed_review_format

            structured = type(direct_client) is ManagedLunaClient and (
                (stage == "lesson" and is_lesson_author_response_format(response_format))
                or (
                    stage == "review"
                    and group_id.startswith("batched-review:")
                    and (is_batch_review_response_format(response_format) or is_typed_review_format(response_format))
                )
            )
            direct_buckets = (
                type(direct_client) is DirectLunaResponsesClient
                and stage == "review"
                and group_id.startswith("batched-review:")
                and is_typed_review_format(response_format)
            )
            auxiliary = is_auxiliary_format(response_format)
            from app.modules.ai.v3.diversity_response_schema import is_diversity_author_format
            auxiliary = auxiliary or is_diversity_author_format(response_format)
            from app.modules.ai.v3.practical_arbitration import is_arbitration_format
            from app.modules.ai.v3.practical_atomic_audit import is_atomic_audit_format
            from app.modules.ai.v3.practical_compact_editorial_contract import (
                is_compact_editorial_review_format,
                is_compact_editorial_verification_format,
            )
            from app.modules.ai.v3.practical_contract import is_practical_course_format
            from app.modules.ai.v3.practical_curriculum import is_curriculum_bank_format, is_curriculum_format
            from app.modules.ai.v3.practical_editorial_contract import (
                is_editorial_review_format,
                is_editorial_revision_format,
            )
            from app.modules.ai.v3.practical_editorial_verification import is_editorial_verification_format
            from app.modules.ai.v3.practical_option_predicates import is_option_predicates_format
            from app.modules.ai.v3.practical_patch import is_practical_patch_format
            from app.modules.ai.v3.practical_question_context import is_context_format
            from app.modules.ai.v3.practical_review import is_practical_review_format
            from app.modules.ai.v3.practical_rule_editorial_contract import (
                is_rule_editorial_review_format,
                is_rule_editorial_verification_format,
            )
            from app.modules.ai.v3.practical_source_audit import is_source_audit_format
            from app.modules.ai.v3.practical_source_core import is_source_core_format
            from app.modules.ai.v3.practical_source_core_editor import is_source_core_editor_format
            from app.modules.ai.v3.practical_source_reader import is_source_read_format
            from app.modules.ai.v3.practical_source_semantics import (
                is_source_completeness_format,
                is_source_semantics_format,
                is_source_semantics_verification_format,
            )
            practical = focused or simple or (
                stage == "review" and group_id.startswith("practical:review:option-predicates:v33:") and is_option_predicates_format(response_format)
                or stage == "review" and group_id.startswith(("practical:editorial:review:v33:", "practical:editorial:review:v34:")) and is_compact_editorial_review_format(response_format)
                or stage == "review" and group_id.startswith(("practical:editorial:verify:v33:", "practical:editorial:verify:v34:")) and is_compact_editorial_verification_format(response_format)
                or
                stage == "lesson" and group_id.startswith("practical:author:") and is_practical_course_format(response_format)
                or stage == "review" and group_id.startswith("practical:source-semantics:complete:v33:") and is_source_completeness_format(response_format)
                or stage == "review" and group_id.startswith("practical:source-semantics:read:v33:") and is_source_semantics_format(response_format)
                or stage == "review" and group_id.startswith("practical:source-semantics:verify:v33:") and is_source_semantics_verification_format(response_format)
                or stage == "review" and group_id.startswith(("practical:editorial:review:v33:", "practical:editorial:review:v34:")) and is_rule_editorial_review_format(response_format)
                or stage == "review" and group_id.startswith(("practical:editorial:verify:v33:", "practical:editorial:verify:v34:")) and is_rule_editorial_verification_format(response_format)
                or stage == "review" and group_id.startswith(("practical:editorial:review:v31:", "practical:editorial:review:v33:", "practical:editorial:review:v34:")) and is_editorial_review_format(response_format)
                or stage == "review" and group_id.startswith(("practical:editorial:verify:v33:", "practical:editorial:verify:v34:")) and is_editorial_verification_format(response_format)
                or stage == "repair" and group_id.startswith(("practical:editorial:revision:v31:", "practical:editorial:revision:v33:")) and is_editorial_revision_format(response_format)
                or stage == "lesson" and group_id.startswith("practical:source-core:author:") and is_source_core_format(response_format)
                or stage == "review" and group_id.startswith("practical:source-core:editor:") and is_source_core_editor_format(response_format)
                or stage == "review" and group_id.startswith("practical:review:") and is_practical_review_format(response_format)
                or stage == "review" and group_id.startswith("practical:review:bank:") and is_curriculum_bank_format(response_format)
                or stage == "review" and group_id.startswith("practical:source-curriculum:") and is_curriculum_format(response_format)
                or stage == "review" and group_id.startswith("practical:source-audit:") and (is_source_audit_format(response_format) or is_atomic_audit_format(response_format))
                or stage == "review" and group_id.startswith("practical:source-read:") and is_source_read_format(response_format)
                or stage == "review" and group_id.startswith("practical:arbitrate:") and is_arbitration_format(response_format)
                or stage == "review" and group_id.startswith("practical:context:") and is_context_format(response_format)
                or stage == "repair" and group_id.startswith("practical:repair:") and is_practical_patch_format(response_format)
            )
            if response_format not in (None, {"type": "json_object"}) and not (
                structured or direct_buckets or auxiliary or practical
            ):
                raise ValueError("direct_owned_format_invalid")
            from app.modules.ai.v3.direct_luna_owned_stage import run_direct_owned_stage

            return await run_direct_owned_stage(
                journal=journal,
                client=direct_client,
                plan=plan,
                result_key=result_key,
                claim_key=claim_key,
                validate_value=validate_value,
                validate_response=validate,
                author_custody=custody,
                messages=messages,
                max_output_tokens=direct_max_output_tokens,
                _owned_claim_guard=_owned_claim_guard,
                **({"response_format": response_format} if structured or direct_buckets or auxiliary or practical else {}),
            )
        return await journal.run_pending(
            plan=plan,
            result_key=result_key,
            claim_key=claim_key,
            validate_value=validate_value,
            validate_response=validate,
            author_custody=custody,
            invoke=invoke,
            _owned_claim_guard=_owned_claim_guard,
        )

    if _owned_claim_guard is not None:
        raise ValueError("v3_owned_guard_requires_pending_journal")
    if direct_client is not None:
        raise ValueError("direct_owned_journal_required")
    prepared = await journal.prepare(result_key, plan)
    restored = await load_result()
    if restored is not None:
        return restored
    if prepared is not None:
        raise ValueError("v3_stage_result_unverified")
    claim = await journal.prepare(claim_key, plan)
    if claim is not None:
        restored = await load_result()
        if restored is not None:
            return restored
        raise ExtractionOutcomeUnknownError("v3_stage_previous_outcome_unknown")
    marker = {"identity": signature, "claim_token": uuid4().hex}
    await journal.save_value(claim_key, marker)
    if await journal.read_owned_value(claim_key, plan) != marker:
        raise ValueError("v3_stage_claim_unverified")
    received = await invoke()
    response = validate(received)
    custody_value = custody(received)
    await journal.save_value(
        result_key, {"identity": signature, "response": response, "response_sha256": _digest(response),
                     **({'author_custody': custody_value} if custody_value is not None else {})}
    )
    saved = await load_result()
    if saved is None:
        raise ValueError("v3_stage_result_unverified")
    return saved
