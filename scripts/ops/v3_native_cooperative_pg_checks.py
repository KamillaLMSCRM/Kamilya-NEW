"""Disposable PostgreSQL native cooperative-claim exercise; no provider transport."""
from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4


async def exercise(owner: Any, runtime: Any, schema: str, tenant: Any, *, enabled: bool = False) -> None:
    if not enabled:
        raise RuntimeError("native_cooperative_gate_disabled")
    import ai_generation_checkpoint_dev_check as canonical
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.modules.ai.delivery_ownership import delivery_id
    from app.modules.admin.runtime_configuration.catalog import RuntimeSnapshot
    from app.modules.ai.llm_client import LLMProviderConfig, ResilientLLMClient
    from app.modules.ai.v3.cooperative_budget import CooperativeBudget, PreclaimYieldError, active_budget
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    from app.modules.ai.v3.native_profile_binding import bind_native_profile
    from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
    from app.modules.ai.v3.pending_stage_transactions import has_pending
    from app.modules.ai.v3.provider_profile import V3ProfiledClient
    from app.modules.ai.v3.revision_policy import POLICY, REVIEW_POLICY, stamp_policy
    from app.modules.ai.v3.stage_checkpoint import stage_once

    canonical.validate_schema(schema)
    job, actor = str(uuid4()), uuid4()
    params = {"source_analysis": stamp_policy({"generation_engine": "evidence_v3"})}
    async with owner.begin() as conn:
        await conn.execute(text(f'''INSERT INTO "{schema}".ai_jobs (id,tenant_id,user_id,status,params,result)
            VALUES(:j,:t,:u,'running',CAST(:p AS json),CAST(:r AS json))'''),
            {"j": job, "t": tenant, "u": actor, "p": json.dumps(params), "r": "{}"})
    sessions = async_sessionmaker(runtime, expire_on_commit=False)

    async def verify(_session: Any, locked: Any, plan: dict[str, Any]) -> bool:
        return (locked.user_id == actor and str(locked.tenant_id) == str(tenant)
                and plan.get("source_sha256") == "a" * 64)

    class SyntheticSource:
        async def verify_locked(self, _session: Any, locked: Any, _plan: Any) -> bool:
            return locked.user_id == actor and str(locked.tenant_id) == str(tenant)

    def make_journal() -> Any:
        result = PendingStageJournal(str(tenant), actor, job, sessions, verify_source=verify)
        result.expected_revision_policy, result.expected_revision_actor = POLICY, actor
        result.review_policy_bound, result.expected_review_policy = True, REVIEW_POLICY
        result.expected_revision_source, result.expected_revision_plan = SyntheticSource(), {"synthetic": True}
        result.native_generation_seconds = client.generation_deadline_seconds
        return result

    async def snapshot() -> tuple[Any, Any, Any]:
        async with sessions() as session:
            await canonical.set_tenant(session, tenant)
            row = (await session.execute(text('SELECT result,params FROM ai_jobs WHERE id=:j'), {"j": job})).one()
            records = (await session.execute(text('''SELECT r.generation_key, r.plan_payload,
                c.content_status,c.content_payload,c.review_status,c.review_payload,
                c.assessment_status,c.assessment_payload FROM ai_generation_runs r
                LEFT JOIN ai_generation_lesson_checkpoints c ON c.generation_run_id=r.id
                WHERE r.source_job_id=:j AND r.tenant_id=:t ORDER BY r.generation_key'''),
                {"j": job, "t": tenant})).all()
            return row.result, row.params, records

    client = V3ProfiledClient(
        ResilientLLMClient([LLMProviderConfig("synthetic", "https://example.invalid", "synthetic", "model")]),
        RuntimeSnapshot(1, {"provider.deepseek.timeout_seconds": 120}), job_id=job, cooperative_deadline=True,
    )
    journal = make_journal()
    delivery_token = delivery_id.set(job)
    try:
        await bind_native_profile(journal=journal, user_id=actor, client=client)
        calls: list[str] = []
        async def invoke() -> dict[str, Any]:
            calls.append("completed")
            return {"ok": True}
        arguments = dict(stage="lesson", group_id="synthetic-native-cooperative", source_sha256="a" * 64,
            route_fingerprint=client.cache_fingerprint(), messages=[{"role": "user", "content": "synthetic"}],
            response_format={"type": "json_object"}, invoke=invoke)
        before = await snapshot()
        token = active_budget.set(CooperativeBudget(deadline=0))
        try:
            try:
                await stage_once(journal, **arguments)
            except PreclaimYieldError:
                pass
            else:
                raise AssertionError("native_cooperative_preclaim_not_yielded")
            if await snapshot() != before or calls:
                raise AssertionError("native_cooperative_preclaim_changed_state")
        finally:
            active_budget.reset(token)

        token = active_budget.set(CooperativeBudget(deadline=time.monotonic() + 1200))
        try:
            if await stage_once(journal, **arguments) != {"ok": True}:
                raise AssertionError("native_cooperative_result_invalid")
        finally:
            active_budget.reset(token)
        completed = await snapshot()
        cold = make_journal()
        cold.expected_native_profile = journal.expected_native_profile
        token = active_budget.set(CooperativeBudget(deadline=0))
        try:
            if await stage_once(cold, **arguments) != {"ok": True} or await snapshot() != completed:
                raise AssertionError("native_cooperative_cold_replay_invalid")
        finally:
            active_budget.reset(token)
        if calls != ["completed"]:
            raise AssertionError("native_cooperative_replay_invoked")

        async def unknown() -> dict[str, Any]:
            calls.append("unknown")
            raise TimeoutError("synthetic")
        pending_args = arguments | {"group_id": "synthetic-native-unknown", "invoke": unknown}
        try:
            await stage_once(journal, **pending_args)
        except ExtractionOutcomeUnknownError:
            pass
        else:
            raise AssertionError("native_cooperative_unknown_not_held")
        held = await snapshot()
        if not has_pending(held[0]):
            raise AssertionError("native_cooperative_pending_missing")
        token = active_budget.set(CooperativeBudget(deadline=0))
        try:
            try:
                await stage_once(cold, **pending_args)
            except ExtractionOutcomeUnknownError:
                pass
            else:
                raise AssertionError("native_cooperative_pending_not_held")
            if await snapshot() != held or calls != ["completed", "unknown"]:
                raise AssertionError("native_cooperative_pending_reinvoked")
        finally:
            active_budget.reset(token)
    finally:
        delivery_id.reset(delivery_token)
