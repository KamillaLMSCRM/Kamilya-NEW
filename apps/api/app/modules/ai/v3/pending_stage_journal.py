"""Explicit server-owned V3 pending mode; no route or credential selection."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.pending_stage_transactions import (
    _locked_job,
    checked_entries,
    claim_with_pending,
    finalize_pending,
    verify_repair_slot,
    verify_source_safely,
)
from app.modules.ai.v3.stage_checkpoint import _digest
from app.modules.ai.worker_lesson_cycle import WorkerCycleJournal


class PendingStageJournal(WorkerCycleJournal):
    def __init__(self, tenant_id: str, user_id: UUID, job_id: str, session_factory: Any, *,
                 verify_source: Callable[[Any, Any, dict[str, Any]], Awaitable[bool]] | None = None):
        if not isinstance(user_id, UUID) or not job_id:
            raise ValueError("v3_pending_identity_invalid")
        super().__init__(tenant_id, job_id, session_factory)
        self.user_id = user_id
        self.verify_source = verify_source

    async def run_pending(self, *, plan: dict[str, Any], result_key: str, claim_key: str,
                          validate_value: Callable[[dict[str, Any]], dict[str, Any]],
                          validate_response: Callable[[Any], dict[str, Any]],
                          invoke: Callable[[], Awaitable[dict[str, Any]]],
                          _owned_claim_guard: Callable[[Any, Any, dict[str, Any]], Awaitable[bool]] | None = None,
                          _direct_metadata: Callable[[], dict[str, Any]] | None = None,
                          ) -> dict[str, Any]:
        verify_source = self.verify_source
        if _owned_claim_guard is not None:
            if not callable(verify_source) or not callable(_owned_claim_guard):
                raise ExtractionOutcomeUnknownError("v3_pending_guard_unverified")
            base_verify = verify_source
            async def guarded(session: Any, job: Any, checked_plan: dict[str, Any]) -> bool:
                return (await base_verify(session, job, checked_plan) is True
                        and await _owned_claim_guard(session, job, checked_plan) is True)
            verify_source = guarded
        digest = _digest(plan)
        marker = {"identity": digest, "claim_token": uuid4().hex}
        restored = await claim_with_pending(journal=self, user_id=self.user_id, plan=plan, result_key=result_key,
                                            claim_key=claim_key, marker=marker, validate=validate_value,
                                            verify_source=verify_source)
        if restored is not None:
            return restored
        try:
            async with self.sessions() as session:
                job = await _locked_job(session, self, self.user_id)
                verify_repair_slot(job, plan, required=True)
                if verify_source is not None:
                    await verify_source_safely(verify_source, session, job, plan)
                entries = checked_entries(job.result if isinstance(job.result, dict) else {})
                if entries.get(digest) != {"claim_key": claim_key, "result_key": result_key,
                                            "token": marker["claim_token"]}:
                    raise ValueError("v3_pending_marker_mismatch")
            response = validate_response(await invoke())
            value = {"identity": digest, "response": response, "response_sha256": _digest(response)}
            if _direct_metadata is not None:
                from app.modules.ai.v3.direct_usage_metadata import checked_metadata
                metadata = checked_metadata(_direct_metadata())
                value["direct_metadata"] = metadata
                value["direct_metadata_sha256"] = _digest(metadata)
            return await finalize_pending(journal=self, user_id=self.user_id, plan=plan, result_key=result_key,
                                          claim_key=claim_key, marker=marker, value=value, validate=validate_value,
                                          verify_source=verify_source)
        except ExtractionOutcomeUnknownError:
            raise
        except BaseException as exc:
            raise ExtractionOutcomeUnknownError("v3_pending_provider_outcome_unknown") from exc
