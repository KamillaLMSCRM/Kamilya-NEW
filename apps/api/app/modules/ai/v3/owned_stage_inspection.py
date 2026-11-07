"""Unwired read-only inspection before a V3 count request."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from app.modules.ai.generation_checkpoint import AIGenerationCheckpointError, PlannedLesson
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.pending_stage_transactions import (
    _locked_job,
    _owner,
    checked_entries,
    has_pending,
    verify_repair_slot,
)
from app.modules.ai.v3.stage_checkpoint import _digest


@dataclass(frozen=True, repr=False)
class StageInspection:
    decision: Literal["replay", "replay_completed", "needs_count"]
    result: dict[str, Any] | None = None

    def __repr__(self) -> str:
        return f"StageInspection(decision={self.decision!r}, result=<redacted>)"


async def inspect_owned_stage(*, journal: Any, user_id: Any, plan: dict[str, Any], result_key: str, claim_key: str,
                              validate: Callable[[dict[str, Any]], dict[str, Any]],
                              verify_source: Callable[[Any, Any, dict[str, Any]], Awaitable[bool]]) -> StageInspection:
    """Inspect exact owned stage under lock. Never create, write, count or claim."""
    from app.modules.ai.lesson_cycle import POLICY_VERSION
    from app.modules.ai.source_assessment_plan import PLAN_POLICY

    try:
        _owner(plan, journal)
        digest = _digest(plan)
        async with journal.sessions() as session:
            job = await _locked_job(session, journal, user_id)
            repair_slot_exists = verify_repair_slot(job, plan)
            if not callable(verify_source) or await verify_source(session, job, plan) is not True:
                raise ValueError("v3_inspection_source_unverified")
            entries = checked_entries(job.result if isinstance(job.result, dict) else {})
            if entries:
                from app.modules.ai.delivery_ownership import delivery_id
                from app.modules.ai.v3.retained_author_replay import (
                    AUTHORIZATION_KEY,
                    AUTHORIZATION_POLICY,
                    owned_candidate,
                )
                candidate = await owned_candidate(session, job)
                params = job.params if isinstance(job.params, dict) else {}
                marker = params.get(AUTHORIZATION_KEY)
                if (candidate is None or marker != {"policy": AUTHORIZATION_POLICY, "stage": candidate["stage"],
                        "body_sha256": candidate["body_sha256"], "pending_sha256": candidate["pending_sha256"],
                        "delivery_id": delivery_id.get()}):
                    raise ExtractionOutcomeUnknownError("v3_inspection_pending")
                if digest == candidate["stage"]:
                    if plan != candidate["plan"] or entries[digest] != {"claim_key": claim_key, "result_key": result_key,
                                                                        "token": candidate["marker"]["claim_token"]}:
                        raise ValueError("v3_replay_plan_mismatch")
                    return StageInspection("replay_completed", candidate)
            repo = journal.repository
            async def exists(key: str) -> bool:
                try:
                    saved_plan = await repo.load_plan(session, tenant_id=journal.tenant_id, generation_key=journal._owned_key(key))
                    if (saved_plan.source_job_id != journal.job_id
                            or saved_plan.plan_revision != f"{PLAN_POLICY}/{POLICY_VERSION}"
                            or _digest(dict(saved_plan.plan_payload)) != digest
                            or saved_plan.lessons != (PlannedLesson("cycle", "lesson", 0, 0),)):
                        raise ValueError("v3_inspection_plan_mismatch")
                    return True
                except AIGenerationCheckpointError as exc:
                    if str(exc) != "generation_plan_not_found":
                        raise
                    return False
            result_exists, claim_exists = await exists(result_key), await exists(claim_key)
            if result_exists:
                saved = await journal.read_owned_value_in_session(session, result_key, plan)
                if saved is not None:
                    verify_repair_slot(job, plan, required=True)
                    return StageInspection("replay", validate(saved))
            if entries:
                raise ExtractionOutcomeUnknownError("v3_inspection_pending")
            if claim_exists:
                raise ExtractionOutcomeUnknownError("v3_inspection_legacy_claim")
            if repair_slot_exists:
                raise ExtractionOutcomeUnknownError("v3_inspection_slot_without_result")
            if has_pending(job.result):
                # Other valid in-flight stages do not make this request complete.
                checked_entries(job.result)
            return StageInspection("needs_count")
    except BaseException:
        pass
    raise ExtractionOutcomeUnknownError("v3_inspection_unverified")
