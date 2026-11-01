"""Unwired V3 pending-stage transactions. No endpoint or worker uses this module."""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import Boolean, case, cast, false, func, literal, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement

from app.models.ai_job import AIJob
from app.modules.ai.generation_checkpoint import AIGenerationCheckpointError, PlannedLesson
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.stage_checkpoint import _digest

KEY = "v3_pending_stages"
POLICY = "v3-pending-stages-v1"


def has_pending(result: Any) -> bool:
    return result is not None and (not isinstance(result, dict) or KEY in result)


class _PendingKeyExists(FunctionElement[bool]):
    type = Boolean()
    inherit_cache = True


@compiles(_PendingKeyExists, "postgresql")
def _compile_pending_postgresql(element: Any, compiler: Any, **kwargs: Any) -> str:
    column = list(element.clauses)[0]
    json_value = cast(column, JSONB)
    expression = case(
        (column.is_(None), false()),
        (func.jsonb_typeof(json_value) == "null", false()),
        (func.jsonb_typeof(json_value) != "object", true()),
        else_=func.coalesce(json_value.has_key(KEY), false()),
    )
    return str(compiler.process(expression, **kwargs))


@compiles(_PendingKeyExists, "sqlite")
def _compile_pending_sqlite(element: Any, compiler: Any, **kwargs: Any) -> str:
    column = list(element.clauses)[0]
    expression = case(
        (column.is_(None), false()),
        (func.json_valid(column) == 0, true()),
        (func.json_type(column) == "null", false()),
        (func.json_type(column) != "object", true()),
        else_=func.json_type(column, literal("$.v3_pending_stages")).is_not(None),
    )
    return str(compiler.process(expression, **kwargs))


def pending_sql_predicate() -> Any:
    """Hold non-object values or present key; top-level null/SQL NULL are absent."""
    return _PendingKeyExists(AIJob.result)


def checked_entries(result: Any) -> dict[str, dict[str, str]]:
    if not isinstance(result, dict):
        raise ValueError("v3_pending_result_invalid")
    if KEY not in result:
        return {}
    value = result[KEY]
    if not isinstance(value, dict) or set(value) != {"policy", "entries"} or value["policy"] != POLICY:
        raise ValueError("v3_pending_invalid")
    entries = value["entries"]
    if not isinstance(entries, dict) or not entries:
        raise ValueError("v3_pending_invalid")
    for digest, entry in entries.items():
        if (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or not isinstance(entry, dict) or set(entry) != {"claim_key", "result_key", "token"}
                or any(not isinstance(item, str) or not item for item in entry.values())
                or not re.fullmatch(r"[0-9a-f]{32}", entry["token"])):
            raise ValueError("v3_pending_invalid")
    return {key: dict(value) for key, value in entries.items()}


def _owner(plan: dict[str, Any], journal: Any) -> None:
    identity = plan.get("identity")
    owner = identity if isinstance(identity, dict) else plan
    if owner.get("tenant_id") != journal.tenant_id or owner.get("job_id") != journal.job_id:
        raise ValueError("v3_pending_owner_invalid")


async def _locked_job(session: Any, journal: Any, user_id: Any) -> Any:
    await journal._lock_delivery(session)
    job = await session.scalar(select(AIJob).where(AIJob.id == journal.job_id,
        AIJob.tenant_id == journal.tenant_id).with_for_update().execution_options(populate_existing=True))
    if job is None or job.user_id != user_id or job.status != "running":
        raise ValueError("v3_pending_owner_invalid")
    if job.result is not None and not isinstance(job.result, dict):
        raise ExtractionOutcomeUnknownError("v3_pending_result_invalid")
    result = job.result if isinstance(job.result, dict) else {}
    if any(key in result for key in ("source_first_commit_intent", "source_first_partitioned_commit_intent")):
        raise ExtractionOutcomeUnknownError("v3_pending_source_first_intent")
    params = job.params if isinstance(job.params, dict) else {}
    analysis = params.get("source_analysis")
    if not isinstance(analysis, dict) or analysis.get("generation_engine") not in {"evidence_v3", "v3_cogen"}:
        raise ExtractionOutcomeUnknownError("v3_pending_engine_invalid")
    return job


async def verify_source_safely(verify_source: Callable[[Any, Any, dict[str, Any]], Awaitable[bool]],
                               session: Any, job: Any, plan: dict[str, Any]) -> None:
    """Fail held without exposing callback errors, including cancellation."""
    valid = False
    try:
        valid = await verify_source(session, job, plan) is True
    except BaseException:
        pass
    if not valid:
        raise ExtractionOutcomeUnknownError("v3_pending_source_unverified")


async def claim_with_pending(*, journal: Any, user_id: Any, plan: dict[str, Any], result_key: str,
                             claim_key: str, marker: dict[str, str],
                             validate: Callable[[dict[str, Any]], dict[str, Any]],
                             verify_source: Callable[[Any, Any, dict[str, Any]], Awaitable[bool]] | None = None) -> dict[str, Any] | None:
    from app.modules.ai.lesson_cycle import POLICY_VERSION
    from app.modules.ai.source_assessment_plan import PLAN_POLICY

    _owner(plan, journal)
    digest = _digest(plan)
    token = marker.get("claim_token")
    if marker.get("identity") != digest or not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
        raise ValueError("v3_pending_claim_invalid")
    uncertain = False
    try:
        async with journal.sessions() as session:
            job = await _locked_job(session, journal, user_id)
            uncertain = has_pending(job.result)
            entries = checked_entries(job.result if isinstance(job.result, dict) else {})
            if entries:
                raise ExtractionOutcomeUnknownError("v3_pending_existing")
            if verify_source is not None:
                await verify_source_safely(verify_source, session, job, plan)
            repo = journal.repository
            async def exists(key: str) -> bool:
                try:
                    await repo.load_plan(session, tenant_id=journal.tenant_id, generation_key=journal._owned_key(key))
                    return True
                except AIGenerationCheckpointError as exc:
                    if str(exc) != "generation_plan_not_found":
                        raise
                    return False
            result_exists, claim_exists = await exists(result_key), await exists(claim_key)
            uncertain = uncertain or result_exists or claim_exists or digest in entries
            if digest in entries:
                raise ExtractionOutcomeUnknownError("v3_pending_existing")
            if result_exists:
                saved = await journal.read_owned_value_in_session(session, result_key, plan)
                if saved is not None:
                    restored = validate(saved)
                    await session.commit()
                    return restored
            if claim_exists:
                raise ExtractionOutcomeUnknownError("v3_pending_legacy_claim")
            for key in (result_key, claim_key):
                await repo.create_plan(session, tenant_id=journal.tenant_id, generation_key=journal._owned_key(key),
                    plan_revision=f"{PLAN_POLICY}/{POLICY_VERSION}", source_job_id=journal.job_id, plan_payload=plan,
                    lessons=(PlannedLesson("cycle", "lesson", 0, 0),))
            fields = dict(tenant_id=journal.tenant_id, generation_key=journal._owned_key(claim_key),
                          module_key="cycle", lesson_key="lesson")
            await repo.checkpoint_content(session, **fields, content_payload={"owned": True})
            await repo.checkpoint_review(session, **fields, review_payload={"policy": PLAN_POLICY})
            await repo.checkpoint_assessment(session, **fields, assessment_payload=marker)
            entries[digest] = {"claim_key": claim_key, "result_key": result_key, "token": token}
            job.result = {**(job.result if isinstance(job.result, dict) else {}), KEY: {"policy": POLICY, "entries": entries}}
            uncertain = True
            await session.commit()
            return None
    except ExtractionOutcomeUnknownError:
        raise
    except BaseException as exc:
        if uncertain:
            raise ExtractionOutcomeUnknownError("v3_pending_claim_unknown") from exc
        raise


async def finalize_pending(*, journal: Any, user_id: Any, plan: dict[str, Any], result_key: str,
                           claim_key: str, marker: dict[str, str], value: dict[str, Any],
                           validate: Callable[[dict[str, Any]], dict[str, Any]],
                           verify_source: Callable[[Any, Any, dict[str, Any]], Awaitable[bool]] | None = None) -> dict[str, Any]:
    from app.modules.ai.source_assessment_plan import PLAN_POLICY

    _owner(plan, journal)
    digest = _digest(plan)
    try:
        async with journal.sessions() as session:
            job = await _locked_job(session, journal, user_id)
            entries = checked_entries(job.result if isinstance(job.result, dict) else {})
            expected = {"claim_key": claim_key, "result_key": result_key, "token": marker.get("claim_token")}
            if entries.get(digest) != expected or marker.get("identity") != digest:
                raise ValueError("v3_pending_marker_mismatch")
            stored_claim = await journal.read_owned_value_in_session(session, claim_key, plan)
            if stored_claim != marker:
                raise ValueError("v3_pending_claim_mismatch")
            if verify_source is not None:
                await verify_source_safely(verify_source, session, job, plan)
            restored = validate(value)
            fields = dict(tenant_id=journal.tenant_id, generation_key=journal._owned_key(result_key),
                          module_key="cycle", lesson_key="lesson")
            await journal.repository.checkpoint_content(session, **fields, content_payload={"owned": True})
            await journal.repository.checkpoint_review(session, **fields, review_payload={"policy": PLAN_POLICY})
            await journal.repository.checkpoint_assessment(session, **fields, assessment_payload=value)
            saved = await journal.read_owned_value_in_session(session, result_key, plan)
            if saved != value or validate(saved) != restored:
                raise ValueError("v3_pending_result_unverified")
            del entries[digest]
            updated = dict(job.result)
            if entries:
                updated[KEY] = {"policy": POLICY, "entries": entries}
            else:
                del updated[KEY]
            job.result = updated
            await session.commit()
            return restored
    except BaseException as exc:
        raise ExtractionOutcomeUnknownError("v3_pending_finalize_unknown") from exc
