"""Read-only, explicit parent extraction reuse; never resolve a pending stage."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select

from app.models.ai_job import AIJob
from app.modules.ai.generation_checkpoint import AIGenerationCheckpointError
from app.modules.ai.job_service import is_abandoned_unknown
from app.modules.ai.json_evidence_equivalence import equivalent
from app.modules.ai.qa_luna_dev_route import QA_TENANT
from app.modules.ai.v3.direct_usage_metadata import checked_metadata
from app.modules.ai.v3.extraction_checkpoint import (
    _DIGEST_KEYS,
    _IDENTITY_KEYS,
    ExtractionOutcomeUnknownError,
    _digest,
    _validate_response,
)
from app.modules.ai.v3.owned_route_binding import KEY as ROUTE_KEY
from app.modules.ai.v3.owned_route_binding import POLICY as ROUTE_POLICY
from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
from app.modules.ai.v3.pending_stage_transactions import _locked_job, checked_entries, has_pending
from app.modules.ai.v3.qa_luna_pending_policy import KEY as QA_KEY
from app.modules.ai.v3.qa_luna_pending_policy import MANAGED_POLICY
from app.modules.ai.v3.revision_policy import POLICY as REVISION_POLICY
from app.modules.ai.v3.revision_policy import is_scoped_policy, read_policy
from app.modules.ai.v3.stage_checkpoint import _digest as stage_digest
from app.modules.ai.worker_lesson_cycle import WorkerCycleJournal

PARENT_KEY = "completed_extraction_parent_job_id"
REUSE_KEY = "v3_completed_extraction_reuse"
REUSE_POLICY = "completed-extraction-parent-v1"


@dataclass(frozen=True)
class CompletedExtractionCandidate:
    source_job_id: str
    source_plan_sha256: str
    response_sha256: str
    response_json: bytes = field(repr=False)
    metadata_json: bytes = field(repr=False)

    def response(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.response_json))

    def original_metadata(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.metadata_json))


async def _candidate_in_session(
    journal: PendingStageJournal, plan: dict[str, Any], parent_job_id: str, session: Any
) -> CompletedExtractionCandidate:
    """Read a candidate before claim; reject any child pending, never import it.

    A future importer must independently revalidate source, identity and pending
    state under its write lock. This candidate grants no provider/save permission.
    """
    try:
        if (
            type(journal) is not PendingStageJournal
            or journal.tenant_id != str(QA_TENANT)
            or not isinstance(journal.user_id, UUID)
            or not callable(journal.verify_source)
            or not isinstance(parent_job_id, str)
            or str(UUID(parent_job_id)) != parent_job_id
            or parent_job_id == journal.job_id
            or not isinstance(plan, dict)
            or set(plan) != {"schema", "identity"}
            or plan["schema"] != "v3-rule-extraction-checkpoint-v1"
        ):
            raise ValueError("reuse_scope_invalid")
        identity = plan["identity"]
        if (
            not isinstance(identity, dict)
            or set(identity) != _IDENTITY_KEYS
            or any(not isinstance(v, str) or not v.strip() for v in identity.values())
            or identity["tenant_id"] != journal.tenant_id
            or identity["job_id"] != journal.job_id
            or any(not re.fullmatch(r"[0-9a-f]{64}", identity[k]) for k in _DIGEST_KEYS)
            or any(not re.fullmatch(r"0|[1-9][0-9]*", identity[k]) for k in ("unit_start", "unit_end"))
            or int(identity["unit_start"]) >= int(identity["unit_end"])
        ):
            raise ValueError("reuse_identity_invalid")
        parent_plan = {"schema": plan["schema"], "identity": {**identity, "job_id": parent_job_id}}
        parent_digest = _digest(parent_plan)
        result_key = "v3-result:" + parent_digest
        child = await _locked_job(session, journal, journal.user_id)
        child_params = child.params if isinstance(child.params, dict) else {}
        child_analysis = child_params.get("source_analysis")
        if (
            child.course_id is not None
            or str(child.id) != journal.job_id
            or child.tenant_id != QA_TENANT
            or child.user_id != journal.user_id
            or child.status != "running"
            or child_params.get(PARENT_KEY) != parent_job_id
            or has_pending(child.result)
            or not isinstance(child_analysis, dict)
            or child_analysis.get("generation_engine") != "evidence_v3"
            or child_analysis.get(QA_KEY) != MANAGED_POLICY
            or not is_scoped_policy(read_policy(child_analysis))
        ):
            raise ValueError("reuse_child_invalid")
        if await journal.verify_source(session, child, plan) is not True:
            raise ValueError("reuse_source_unverified")
        parent = await session.scalar(
            select(AIJob)
            .where(AIJob.id == parent_job_id, AIJob.tenant_id == journal.tenant_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if (
            parent is None
            or parent.tenant_id != QA_TENANT
            or str(parent.id) != parent_job_id
            or parent.user_id != journal.user_id
            or not is_abandoned_unknown(parent)
        ):
            raise ValueError("reuse_parent_invalid")
        if (
            not isinstance(parent.created_at, datetime)
            or not isinstance(child.created_at, datetime)
            or parent.created_at.tzinfo is None
            or child.created_at.tzinfo is None
            or parent.created_at >= child.created_at
        ):
            raise ValueError("reuse_parent_order_invalid")
        parent_params = parent.params if isinstance(parent.params, dict) else {}
        parent_analysis = parent_params.get("source_analysis")
        if (
            not isinstance(parent_analysis, dict)
            or parent_analysis.get("generation_engine") != "evidence_v3"
            or parent_analysis.get(QA_KEY) != MANAGED_POLICY
            or read_policy(parent_analysis) != read_policy(child_analysis)
            or not isinstance(child_params.get("documents"), list)
            or not child_params["documents"]
            or not equivalent(parent_params.get("documents"), child_params["documents"])
            or identity["document_id"] not in child_params["documents"]
            or not isinstance(child_params.get("reference_decisions"), list)
            or not equivalent(parent_params.get("reference_decisions"), child_params["reference_decisions"])
        ):
            raise ValueError("reuse_parent_source_invalid")
        route = {"policy": ROUTE_POLICY, "fingerprint": identity["route_fingerprint"]}
        if (
            not isinstance(child.result, dict)
            or child.result.get(ROUTE_KEY) != route
            or not isinstance(parent.result, dict)
            or parent.result.get(ROUTE_KEY) != route
        ):
            raise ValueError("reuse_route_invalid")
        if any(entry["result_key"] == result_key for entry in checked_entries(parent.result).values()):
            raise ValueError("reuse_pending_result")
        parent_journal = WorkerCycleJournal(journal.tenant_id, parent_job_id, journal.sessions)
        saved = await parent_journal.read_owned_value_in_session(session, result_key, parent_plan)
        if saved is None:
            raise ValueError("reuse_result_missing_or_ambiguous")
        if (
            saved.get("identity") != parent_digest
            or not isinstance(saved.get("response_sha256"), str)
            or not isinstance(saved.get("direct_metadata_sha256"), str)
        ):
            raise ValueError("reuse_result_invalid")
        rows = await parent_journal.repository.load_checkpoints(
            session, tenant_id=journal.tenant_id, generation_key=parent_journal._owned_key(result_key)
        )
        if (len(rows) != 1 or (rows[0].module_key, rows[0].lesson_key) != ("cycle", "lesson")
                or (rows[0].content_status, rows[0].review_status, rows[0].assessment_status)
                   != ("completed", "completed", "completed")):
            raise ValueError("reuse_checkpoint_incomplete")
        response = _validate_response(saved.get("response"))
        metadata = checked_metadata(saved.get("direct_metadata"))
        if (
            _digest(response) != saved["response_sha256"]
            or metadata != saved.get("direct_metadata")
            or metadata.get("model") != "gpt-5.6-luna"
            or stage_digest(metadata) != saved["direct_metadata_sha256"]
        ):
            raise ValueError("reuse_result_digest_invalid")
        return CompletedExtractionCandidate(
            parent_job_id,
            parent_digest,
            saved["response_sha256"],
            json.dumps(response, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8"),
            json.dumps(metadata, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8"),
        )
    except Exception:
        raise ExtractionOutcomeUnknownError("v3_extraction_reuse_unverified") from None


async def lookup_completed_extraction(
    journal: PendingStageJournal, plan: dict[str, Any], parent_job_id: str
) -> CompletedExtractionCandidate | None:
    """Read-only preclaim inspection; return no provider or write capability."""
    async with journal.sessions() as session:
        return await _candidate_in_session(journal, plan, parent_job_id, session)


async def reuse_completed_extraction(
    journal: PendingStageJournal, plan: dict[str, Any], parent_job_id: str
) -> dict[str, Any]:
    """Revalidate under the child lock and record provenance, without an inference.

    Historical provider metadata stays on the parent checkpoint. The child gets
    neither a fake provider checkpoint nor new token usage. Cold restoration reads
    and verifies that exact parent again before using its response.
    """
    try:
        async with journal.sessions() as session:
            candidate = await _candidate_in_session(journal, plan, parent_job_id, session)
            child = await _locked_job(session, journal, journal.user_id)
            digest = _digest(plan)
            for key in ("v3-result:" + digest, "v3-claim:" + digest):
                try:
                    await journal.repository.load_plan(session, tenant_id=journal.tenant_id,
                                                       generation_key=journal._owned_key(key))
                except AIGenerationCheckpointError as exc:
                    if str(exc) == "generation_plan_not_found":
                        continue
                    raise
                raise ValueError("reuse_child_stage_exists")
            result = dict(child.result)
            prior = result.get(REUSE_KEY, {"policy": REUSE_POLICY, "entries": {}})
            if (not isinstance(prior, dict) or set(prior) != {"policy", "entries"}
                    or prior["policy"] != REUSE_POLICY or not isinstance(prior["entries"], dict)):
                raise ValueError("reuse_provenance_invalid")
            entries = dict(prior["entries"])
            fields = {"source_job_id", "source_plan_sha256", "response_sha256", "original_metadata_sha256"}
            if any(not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key)
                   or not isinstance(value, dict) or set(value) != fields
                   or value["source_job_id"] != parent_job_id
                   or any(not isinstance(value[k], str) or not re.fullmatch(r"[0-9a-f]{64}", value[k])
                          for k in fields - {"source_job_id"}) for key, value in entries.items()):
                raise ValueError("reuse_provenance_invalid")
            expected = {"source_job_id": candidate.source_job_id,
                        "source_plan_sha256": candidate.source_plan_sha256,
                        "response_sha256": candidate.response_sha256,
                        "original_metadata_sha256": stage_digest(candidate.original_metadata())}
            if digest in entries and entries[digest] != expected:
                raise ValueError("reuse_provenance_changed")
            entries[digest] = expected
            result[REUSE_KEY] = {"policy": REUSE_POLICY, "entries": entries}
            child.result = result
            await session.commit()
            return candidate.response()
    except Exception:
        raise ExtractionOutcomeUnknownError("v3_extraction_reuse_unverified") from None


async def validate_parent_admission(
    session: Any, *, tenant_id: UUID, user_id: UUID, parent_job_id: UUID,
    policy: str | None, documents: list[str], references: list[dict[str, Any]], course_id: UUID | None,
) -> None:
    """Preflight only; the running worker revalidates the parent under its locks."""
    if tenant_id != QA_TENANT or policy != MANAGED_POLICY or course_id is not None:
        raise ValueError("reuse_admission_scope_invalid")
    parent = await session.scalar(select(AIJob).where(AIJob.id == str(parent_job_id),
        AIJob.tenant_id == tenant_id, AIJob.user_id == user_id).execution_options(populate_existing=True))
    params = parent.params if parent is not None and isinstance(parent.params, dict) else {}
    analysis = params.get("source_analysis")
    if (parent is None or parent.user_id != user_id or parent.tenant_id != QA_TENANT
            or not is_abandoned_unknown(parent) or not isinstance(analysis, dict)
            or analysis.get("generation_engine") != "evidence_v3" or analysis.get(QA_KEY) != MANAGED_POLICY
            or read_policy(analysis) != REVISION_POLICY or not equivalent(params.get("documents"), documents)
            or not equivalent(params.get("reference_decisions"), references)):
        raise ValueError("reuse_admission_parent_invalid")


def read_parent_marker(params: Any, policy: str | None) -> str | None:
    """Persisted presence is intent; malformed presence must never become a miss."""
    if not isinstance(params, dict) or PARENT_KEY not in params:
        return None
    value = params[PARENT_KEY]
    try:
        if policy == MANAGED_POLICY and isinstance(value, str) and str(UUID(value)) == value:
            return value
    except (ValueError, TypeError, AttributeError):
        pass
    raise ExtractionOutcomeUnknownError("v3_extraction_reuse_scope_invalid")
