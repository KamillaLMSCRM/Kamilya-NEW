"""Explicit server-owned V3 pending mode; no route or credential selection."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

from app.modules.ai.direct_luna_responses_client import ResponsesRejectedError
from app.modules.ai.managed_response_rejection import ManagedResponseRejectedError
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.pending_stage_transactions import (
    _locked_job,
    checked_entries,
    claim_with_pending,
    finalize_pending,
    verify_repair_slot,
    verify_source_safely,
)
from app.modules.ai.v3.rejected_artifact import ModelArtifactRejectedError
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
        self.completed_extraction_parent_job_id: str | None = None
        self.native_generation_seconds: float | None = None
        self.explicit_stage_retries: dict[str, Any] | None = None

    async def run_pending(self, *, plan: dict[str, Any], result_key: str, claim_key: str,
                          validate_value: Callable[[dict[str, Any]], dict[str, Any]],
                          validate_response: Callable[[Any], dict[str, Any]],
                          invoke: Callable[[], Awaitable[Any]],
                          _owned_claim_guard: Callable[[Any, Any, dict[str, Any]], Awaitable[bool]] | None = None,
                          _direct_metadata: Callable[[], dict[str, Any]] | None = None,
                          _completed_response: Callable[[str, Exception], ManagedResponseRejectedError | None] | None = None,
                          author_custody: Callable[[Any], dict[str, Any] | None] | None = None,
                          ) -> dict[str, Any]:
        from app.modules.ai.managed_luna_client import ManagedLunaHttpRejectedError
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
        phase = "stage_validation"
        received: Any = None
        async def retain_native(rejection: ModelArtifactRejectedError) -> None:
            from app.modules.ai.v3.managed_rejection_quarantine import retain_native_rejection
            try:
                await retain_native_rejection(journal=self, plan=plan, result_key=result_key, claim_key=claim_key,
                    marker=marker, rejection=rejection, verify_source=verify_source)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

        async def retain_completed(cause: Exception) -> None:
            if isinstance(received, dict) and self.expected_native_profile is not None:
                identity = plan.get("identity")
                route = plan.get("route_fingerprint") or (identity.get("route_fingerprint") if isinstance(identity, dict) else None)
                request = plan.get("request_sha256") or (identity.get("prompt_sha256") if isinstance(identity, dict) else None)
                try:
                    if not isinstance(route, str) or not isinstance(request, str):
                        raise ValueError("v3_native_artifact_scope_invalid")
                    native_rejection = ModelArtifactRejectedError.from_value(received, job_id=self.job_id, route=route,
                                                                      request=request, phase=phase)
                except (ValueError, TypeError):
                    pass
                else:
                    await retain_native(native_rejection)
            if _completed_response is None:
                return
            from app.modules.ai.v3.managed_rejection_quarantine import retain_managed_rejection
            try:
                rejection = _completed_response(phase, cause)
                if rejection is not None:
                    await retain_managed_rejection(journal=self, plan=plan, result_key=result_key, claim_key=claim_key,
                        marker=marker, rejection=rejection, verify_source=verify_source)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
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
            received = await invoke()
            response = validate_response(received)
            phase = "stage_metadata"
            value = {"identity": digest, "response": response, "response_sha256": _digest(response)}
            custody_value = author_custody(received) if author_custody is not None else None
            if custody_value is not None:
                value['author_custody'] = custody_value
            else:
                from app.modules.ai.v3.stage_checkpoint import ordered_response_fields
                value.update(ordered_response_fields(response))
            if _direct_metadata is not None:
                from app.modules.ai.v3.direct_usage_metadata import checked_metadata
                metadata = checked_metadata(_direct_metadata())
                value["direct_metadata"] = metadata
                value["direct_metadata_sha256"] = _digest(metadata)
            phase = "stage_finalize"
            return await finalize_pending(journal=self, user_id=self.user_id, plan=plan, result_key=result_key,
                                          claim_key=claim_key, marker=marker, value=value, validate=validate_value,
                                          verify_source=verify_source)
        except ExtractionOutcomeUnknownError as exc:
            await retain_completed(exc)
            raise
        except ModelArtifactRejectedError as exc:
            await retain_native(exc)
            raise ExtractionOutcomeUnknownError("v3_pending_provider_outcome_unknown") from None
        except ManagedResponseRejectedError as exc:
            from app.modules.ai.v3.managed_rejection_quarantine import retain_managed_rejection

            try:
                await retain_managed_rejection(journal=self, plan=plan, result_key=result_key, claim_key=claim_key,
                                               marker=marker, rejection=exc, verify_source=verify_source)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A failed or unknown evidence write never permits acceptance or another call.
                pass
            raise ExtractionOutcomeUnknownError("v3_pending_provider_outcome_unknown") from None
        except (ResponsesRejectedError, ManagedLunaHttpRejectedError) as exc:
            from app.modules.ai.v3.pending_rejection_receipt import retain_rejection

            try:
                await retain_rejection(journal=self, plan=plan, result_key=result_key, claim_key=claim_key,
                                       marker=marker, rejection=exc, verify_source=verify_source)
            except BaseException:
                # Lost commit acknowledgment or changed ownership/source cannot authorize another call.
                pass
            raise ExtractionOutcomeUnknownError("v3_pending_provider_outcome_unknown") from exc
        except BaseException as exc:
            if isinstance(exc, Exception):
                await retain_completed(exc)
            raise ExtractionOutcomeUnknownError("v3_pending_provider_outcome_unknown") from exc
