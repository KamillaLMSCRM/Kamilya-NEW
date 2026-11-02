"""Atomic-claim DEV gate candidate with explicit exact-input execution boundary.

The real journal and PostgreSQL transactions are used by the exercise body;
there is no provider invocation. Do not infer executed or production evidence.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXECUTION_ENABLED = False
DEV_REF_SHA256 = "5b535773cb7222384bbb54ad3f8c2e741fa6176bec4ce586abcd82d17ee0062e"


def source_digest() -> str:
    files = {p for root in (ROOT / "apps/api/app", ROOT / "apps/api/alembic", ROOT / "scripts/ops")
             for p in root.rglob("*.py") if "__pycache__" not in p.parts}
    manifest = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def _exercise_budget_period(owner: Any, runtime: Any, schema: str, tenant_a: Any, tenant_b: Any) -> None:
    if not EXECUTION_ENABLED:
        raise RuntimeError("pending_lifecycle_gate_unreviewed")
    from uuid import uuid4

    import ai_generation_checkpoint_dev_check as canonical
    from app.models.tenants import Tenant
    from app.modules.ai.job_service import release_generation_reservation_once
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    canonical.validate_schema(schema)
    job, missing = str(uuid4()), str(uuid4())
    async with owner.begin() as conn:
        # Canonical checkpoint fixture has only id/name/slug. Quota locking reads
        # the full ORM Tenant; add nullable fixture columns in this schema only.
        quote = owner.dialect.identifier_preparer.quote
        for column in Tenant.__table__.columns:
            if column.name not in {"id", "name", "slug"}:
                sql_type = column.type.compile(dialect=owner.dialect)
                await conn.execute(text(f'ALTER TABLE "{schema}".tenants ADD COLUMN {quote(column.name)} {sql_type}'))
        await conn.execute(text(f'''CREATE TABLE "{schema}".tenant_usage (
            tenant_id uuid PRIMARY KEY, ai_course_generations_used integer NOT NULL DEFAULT 0,
            jd_course_generations_used integer NOT NULL DEFAULT 0,
            active_students_count_snapshot integer NOT NULL DEFAULT 0,
            system_users_count_snapshot integer NOT NULL DEFAULT 0, updated_at timestamptz NOT NULL DEFAULT now())'''))
        await conn.execute(text(f'''CREATE TABLE "{schema}".tenant_llm_usage (
            id uuid PRIMARY KEY, tenant_id uuid NOT NULL, month_key varchar(7) NOT NULL,
            cost_cents integer NOT NULL, request_count integer NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE(tenant_id,month_key))'''))
        for name in ("tenant_usage", "tenant_llm_usage"):
            table = f'"{schema}".{name}'
            await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            await conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
            await conn.execute(text(f'''CREATE POLICY fixture_tenant ON {table} FOR ALL TO lms_app
                USING(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
                WITH CHECK(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)'''))
            await conn.execute(text(f"REVOKE ALL ON {table} FROM PUBLIC,lms_app"))
            await conn.execute(text(f"GRANT SELECT,UPDATE ON {table} TO lms_app"))
        await conn.execute(text(f'INSERT INTO "{schema}".tenant_usage(tenant_id,ai_course_generations_used) VALUES(:t,2)'), {"t": tenant_a})
        await conn.execute(text(f'''INSERT INTO "{schema}".tenant_llm_usage(id,tenant_id,month_key,cost_cents,request_count)
            VALUES(:one,:t,'2026-10',20,2),(:two,:t,'2026-11',70,7)'''),
            {"one": uuid4(), "two": uuid4(), "t": tenant_a})
        for identifier, period in ((job, None), (missing, "2026-09")):
            params: dict[str, Any] = {"documents": ["synthetic-budget"], "generation_reservation_required": True,
                                      "generation_reservation_released": False}
            if period:
                params["generation_budget_month"] = period
            await conn.execute(text(f'''INSERT INTO "{schema}".ai_jobs
                (id,tenant_id,user_id,status,params,created_at,started_at)
                VALUES(:j,:t,:u,'cancelled',CAST(:p AS json),'2026-10-29T12:00:00Z','2026-10-29T12:00:01Z')'''),
                {"j": identifier, "t": tenant_a, "u": uuid4(), "p": json.dumps(params)})
    sessions = async_sessionmaker(runtime, expire_on_commit=False)
    async with sessions() as session:
        await canonical.set_tenant(session, tenant_a)
        await session.execute(text("SELECT id FROM tenants WHERE id=:t FOR UPDATE"), {"t": tenant_a})
        if await release_generation_reservation_once(session, job_id=job, tenant_id=tenant_a) is not True:
            raise AssertionError("legacy_period_release_failed")
        await session.commit()
    async with sessions() as session:
        await canonical.set_tenant(session, tenant_a)
        await session.execute(text("SELECT id FROM tenants WHERE id=:t FOR UPDATE"), {"t": tenant_a})
        if await release_generation_reservation_once(session, job_id=job, tenant_id=tenant_a) is not False:
            raise AssertionError("period_refund_repeated")
        await session.commit()
    async with sessions() as session:
        await canonical.set_tenant(session, tenant_a)
        await session.execute(text("SELECT id FROM tenants WHERE id=:t FOR UPDATE"), {"t": tenant_a})
        try:
            await release_generation_reservation_once(session, job_id=missing, tenant_id=tenant_a)
        except ValueError as exc:
            if str(exc) != "llm_budget_refund_unverified":
                raise
            await session.rollback()
        else:
            raise AssertionError("missing_period_refund_accepted")
    async with sessions() as session:
        await canonical.set_tenant(session, tenant_a)
        rows = (await session.execute(text("SELECT month_key,cost_cents,request_count FROM tenant_llm_usage ORDER BY month_key"))).all()
        used = await session.scalar(text("SELECT ai_course_generations_used FROM tenant_usage WHERE tenant_id=:t"), {"t": tenant_a})
        params = await session.scalar(text("SELECT params FROM ai_jobs WHERE id=:j"), {"j": missing})
        if rows != [("2026-10", 10, 1), ("2026-11", 70, 7)] or used != 1 or params.get("generation_reservation_released") is not False:
            raise AssertionError("period_refund_or_rollback_invalid")
    async with sessions() as session:
        await canonical.set_tenant(session, tenant_b)
        if await release_generation_reservation_once(session, job_id=missing, tenant_id=tenant_b) is not False:
            raise AssertionError("foreign_period_refund_allowed")
        for name in ("tenant_usage", "tenant_llm_usage"):
            if await session.scalar(text(f"SELECT count(*) FROM {name}")) != 0:
                raise AssertionError("foreign_budget_rows_visible")


async def _exercise_revision_policy(owner: Any, runtime: Any, schema: str, tenant_a: Any, tenant_b: Any) -> None:
    if not EXECUTION_ENABLED:
        raise RuntimeError("pending_lifecycle_gate_unreviewed")
    from uuid import uuid4

    import ai_generation_checkpoint_dev_check as canonical
    from app.models.document import Document
    from app.modules.ai import delivery_ownership, pipeline
    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.v3.owned_source_context import OwnedSourceContext
    from app.modules.ai.v3.revision_policy import KEY, POLICY, stamp_policy
    from app.modules.ai.worker_lesson_cycle import WorkerCycleJournal
    from sqlalchemy import MetaData, text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    canonical.validate_schema(schema)
    job, actor, document = str(uuid4()), uuid4(), uuid4()
    content_hash, content = "a" * 64, "Synthetic source for revision-policy custody."
    analysis = stamp_policy({"generation_engine": "evidence_v3"})
    params = {"documents": [str(document)], "source_analysis": analysis}
    shadow = Document.__table__.to_metadata(MetaData(schema=schema))
    async with owner.begin() as conn:
        await conn.run_sync(lambda sync: shadow.create(sync, checkfirst=False))
        await conn.execute(text(f'ALTER TABLE "{schema}".documents ENABLE ROW LEVEL SECURITY'))
        await conn.execute(text(f'ALTER TABLE "{schema}".documents FORCE ROW LEVEL SECURITY'))
        await conn.execute(text(f'''CREATE POLICY fixture_tenant ON "{schema}".documents FOR ALL TO lms_app
            USING(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
            WITH CHECK(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)'''))
        await conn.execute(text(f'REVOKE ALL ON "{schema}".documents FROM PUBLIC,lms_app'))
        await conn.execute(text(f'GRANT SELECT,UPDATE ON "{schema}".documents TO lms_app'))
        await conn.execute(text(f'''INSERT INTO "{schema}".documents
            (id,tenant_id,uploaded_by,title,filename,content_type,file_size,category,content_sha256,lifecycle_status)
            VALUES(:d,:t,:u,'synthetic','synthetic.txt','text/plain',:size,'general',:sha,'active')'''),
            {"d": document, "t": tenant_a, "u": actor, "size": len(content), "sha": content_hash})
        await conn.execute(text(f'''INSERT INTO "{schema}".ai_jobs (id,tenant_id,user_id,status,params,result)
            VALUES(:j,:t,:u,'running',CAST(:p AS json),CAST(:r AS json))'''),
            {"j": job, "t": tenant_a, "u": actor, "p": json.dumps(params), "r": "{}"})
    sessions = async_sessionmaker(runtime, expire_on_commit=False)
    source_doc = DirectSourceDocument(str(document), "synthetic", "synthetic.txt", "general",
                                     "document:" + content_hash, (), source_text=content)
    corpus = DirectSourceCorpus(str(tenant_a), (source_doc,), len(content), 0)
    journal = WorkerCycleJournal(str(tenant_a), job, sessions)
    journal.expected_revision_policy, journal.expected_revision_actor = POLICY, actor
    journal.expected_revision_source = OwnedSourceContext(corpus, journal, tenant_a, actor, job, (str(document),))
    journal.expected_revision_plan = {"schema": "v3-stage-checkpoint-v1", "tenant_id": str(tenant_a),
        "job_id": job, "source_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}
    plan = {"fixture": "revision-policy"}
    delivery_token = delivery_ownership.delivery_id.set(job)
    previous_factory = pipeline.async_session_factory
    pipeline.async_session_factory = sessions
    try:
        if await pipeline._load_owned_revision_policy(job, tenant_a, actor, [str(document)]) != POLICY:
            raise AssertionError("revision_owned_loader_invalid")
        try:
            await pipeline._load_owned_revision_policy(job, tenant_a, uuid4(), [str(document)])
        except pipeline.GenerationJobOwnerMismatchError:
            pass
        else:
            raise AssertionError("revision_wrong_actor_allowed")
        from app.modules.ai.direct_source import DirectSourceError
        try:
            await pipeline._load_owned_revision_policy(job, tenant_a, actor, [str(uuid4())])
        except DirectSourceError:
            pass
        else:
            raise AssertionError("revision_wrong_selection_allowed")
        if await journal.prepare("revision-fixture", plan) is not None:
            raise AssertionError("revision_unexpected_checkpoint")
        await journal.save_value("revision-fixture", {"synthetic": True})
        if await journal.read_owned_value("revision-fixture", plan) != {"synthetic": True}:
            raise AssertionError("revision_checkpoint_read_invalid")
        for drift in ("policy", "selection", "content_hash"):
            async with owner.begin() as conn:
                altered = json.loads(json.dumps(params))
                if drift == "policy":
                    altered["source_analysis"][KEY] = "invalid"
                if drift == "selection":
                    altered["documents"] = [str(uuid4())]
                await conn.execute(text(f'UPDATE "{schema}".ai_jobs SET params=CAST(:p AS json) WHERE id=:j'),
                                   {"p": json.dumps(altered), "j": job})
                await conn.execute(text(f'UPDATE "{schema}".documents SET content_sha256=:sha WHERE id=:d'),
                                   {"sha": "b" * 64 if drift == "content_hash" else content_hash, "d": document})
            for operation in (lambda: journal.read_owned_value("revision-fixture", plan),
                              lambda: journal.save_value("revision-fixture", {"synthetic": False})):
                try:
                    await operation()
                except delivery_ownership.DeliveryOwnershipLostError:
                    pass
                else:
                    raise AssertionError("revision_drift_not_fenced")
            async with owner.connect() as conn:
                saved = (await conn.execute(text(f'''SELECT c.assessment_payload FROM "{schema}".ai_generation_lesson_checkpoints c
                    JOIN "{schema}".ai_generation_runs r ON c.generation_run_id=r.id AND c.tenant_id=r.tenant_id
                    WHERE r.tenant_id=:t AND r.source_job_id=:j AND r.generation_key=:k'''),
                    {"t": tenant_a, "j": job, "k": journal._owned_key("revision-fixture")})).scalar_one()
                if saved != {"synthetic": True}:
                    raise AssertionError("revision_checkpoint_changed")
        async with sessions() as session:
            await canonical.set_tenant(session, tenant_b)
            if await session.scalar(text(f'SELECT count(*) FROM "{schema}".documents WHERE id=:d'), {"d": document}) != 0:
                raise AssertionError("foreign_document_visible")
            if await session.scalar(text(f'SELECT count(*) FROM "{schema}".ai_jobs WHERE id=:j'), {"j": job}) != 0:
                raise AssertionError("foreign_revision_job_visible")
    finally:
        pipeline.async_session_factory = previous_factory
        delivery_ownership.delivery_id.reset(delivery_token)


async def _exercise_abandonment(owner: Any, runtime: Any, schema: str, tenant_a: Any, tenant_b: Any) -> None:
    """Exercise the owned pending-stage fence; this does not test a course-save race."""
    if not EXECUTION_ENABLED:
        raise RuntimeError("pending_lifecycle_gate_unreviewed")
    from uuid import uuid4

    import ai_generation_checkpoint_dev_check as canonical
    from app.models.ai_job import AIJob
    from app.modules.ai.delivery_ownership import DeliveryOwnershipLostError, delivery_id
    from app.modules.ai.job_service import (
        abandon_unknown_generation, claim_generation_execution, release_generation_reservation_once,
    )
    from app.modules.ai.v3.pending_stage_transactions import claim_with_pending, finalize_pending
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    from app.modules.ai.v3.stage_checkpoint import _digest
    from app.modules.ai.worker_lesson_cycle import WorkerCycleJournal
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    canonical.validate_schema(schema)
    job, course_job, actor = str(uuid4()), str(uuid4()), uuid4()
    params = {"source_analysis": {"generation_engine": "evidence_v3", "analysis_mode": "direct_source"},
              "documents": ["synthetic"], "generation_reservation_required": True,
              "generation_reservation_released": False}
    async with owner.begin() as conn:
        for identifier in (job, course_job):
            await conn.execute(text(f'''INSERT INTO "{schema}".ai_jobs (id,tenant_id,user_id,status,params,result)
                VALUES(:j,:t,:u,'running',CAST(:p AS json),CAST(:r AS json))'''),
                {"j": identifier, "t": tenant_a, "u": actor, "p": json.dumps(params),
                 "r": json.dumps({"resume_count": 0})})
    sessions = async_sessionmaker(runtime, expire_on_commit=False)
    journal = WorkerCycleJournal(str(tenant_a), job, sessions)
    plan = {"tenant_id": str(tenant_a), "job_id": job, "kind": "synthetic-abandon"}
    digest = _digest(plan)
    arguments = dict(journal=journal, user_id=actor, plan=plan, result_key="abandon-result",
                     claim_key="abandon-claim", marker={"identity": digest, "claim_token": "d" * 32},
                     validate=lambda value: value["response"])
    token = delivery_id.set(job)
    try:
        if await claim_with_pending(**arguments) is not None:
            raise AssertionError("abandon_claim_invalid")
        async def snapshot() -> tuple[Any, Any, Any]:
            async with sessions() as session:
                await canonical.set_tenant(session, tenant_a)
                row = (await session.execute(text("SELECT result,params FROM ai_jobs WHERE id=:j"), {"j": job})).one()
                checkpoints = (await session.execute(text('''SELECT r.generation_key,c.assessment_status,c.assessment_payload
                    FROM ai_generation_runs r JOIN ai_generation_lesson_checkpoints c ON c.generation_run_id=r.id
                    WHERE r.source_job_id=:j AND r.tenant_id=:t ORDER BY r.generation_key'''),
                    {"j": job, "t": tenant_a})).all()
                return row.result, row.params, checkpoints
        before_result, before_params, before_checkpoints = await snapshot()
        first_pid = second_pid = None
        async with sessions() as locked:
            await canonical.set_tenant(locked, tenant_a)
            first_pid = await locked.scalar(text("SELECT pg_backend_pid()"))
            await locked.scalar(select(AIJob.id).where(AIJob.id == job).with_for_update())
            started = asyncio.Event()
            async def abandon() -> str:
                nonlocal second_pid
                async with sessions() as session:
                    await canonical.set_tenant(session, tenant_a)
                    second_pid = await session.scalar(text("SELECT pg_backend_pid()"))
                    started.set()
                    return await abandon_unknown_generation(session, job_id=job, tenant_id=tenant_a, user_id=actor)
            task = asyncio.create_task(abandon())
            try:
                await asyncio.wait_for(started.wait(), timeout=10)
                async with runtime.connect() as observer:
                    for _ in range(50):
                        if task.done():
                            raise AssertionError("abandon_race_not_blocked")
                        if await observer.scalar(text("SELECT :first = ANY(pg_blocking_pids(:second))"),
                                                 {"first": first_pid, "second": second_pid}):
                            break
                        await asyncio.sleep(0.1)
                    else:
                        raise AssertionError("abandon_race_blocking_unverified")
                await locked.commit()
                if await asyncio.wait_for(task, timeout=10) != "abandoned":
                    raise AssertionError("abandon_race_transition_failed")
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        after_result, after_params, after_checkpoints = await snapshot()
        if (after_result != before_result or after_checkpoints != before_checkpoints
                or {k: v for k, v in after_params.items() if k != "generation_abandonment"} != before_params):
            raise AssertionError("abandon_preservation_invalid")
        async with sessions() as session:
            await canonical.set_tenant(session, tenant_a)
            if await abandon_unknown_generation(session, job_id=job, tenant_id=tenant_a, user_id=actor) != "abandoned":
                raise AssertionError("abandon_replay_invalid")
            if await abandon_unknown_generation(session, job_id=job, tenant_id=tenant_a, user_id=uuid4()) != "not_found":
                raise AssertionError("abandon_foreign_actor_allowed")
            if await release_generation_reservation_once(session, job_id=job, tenant_id=tenant_a):
                raise AssertionError("abandon_refunded")
            await session.rollback()
        async with sessions() as session:
            await canonical.set_tenant(session, tenant_b)
            if await abandon_unknown_generation(session, job_id=job, tenant_id=tenant_b, user_id=actor) != "not_found":
                raise AssertionError("abandon_foreign_tenant_allowed")
        async with sessions() as session:
            await canonical.set_tenant(session, tenant_a)
            if await claim_generation_execution(session, job, str(tenant_a), job):
                raise AssertionError("abandon_redelivery_allowed")
        for operation in (lambda: finalize_pending(**arguments, value={"identity": digest, "response": {"synthetic": True}}),
                          lambda: journal.save_value("abandon-claim", {"synthetic": True})):
            try:
                await operation()
            except (ExtractionOutcomeUnknownError, DeliveryOwnershipLostError):
                pass
            else:
                raise AssertionError("abandon_stale_owned_access_allowed")
        async with sessions() as session:
            try:
                await journal.lock_owned_session(session)
                await journal.read_owned_value_in_session(session, "abandon-claim", plan)
            except DeliveryOwnershipLostError:
                pass
            else:
                raise AssertionError("abandon_stale_owned_read_allowed")
        course_journal = WorkerCycleJournal(str(tenant_a), course_job, sessions)
        course_plan = {"tenant_id": str(tenant_a), "job_id": course_job, "kind": "synthetic-course-conflict"}
        course_args = arguments | {"journal": course_journal, "plan": course_plan,
            "marker": {"identity": _digest(course_plan), "claim_token": "e" * 32}}
        course_token = delivery_id.set(course_job)
        try:
            if await claim_with_pending(**course_args) is not None:
                raise AssertionError("abandon_course_claim_invalid")
        finally:
            delivery_id.reset(course_token)
        async with runtime.begin() as conn:
            await canonical.set_tenant(conn, tenant_a)
            await conn.execute(text("UPDATE ai_jobs SET course_id=:c WHERE id=:j"), {"c": uuid4(), "j": course_job})
        async with sessions() as session:
            await canonical.set_tenant(session, tenant_a)
            if await abandon_unknown_generation(session, job_id=course_job, tenant_id=tenant_a, user_id=actor) != "conflict":
                raise AssertionError("abandon_course_job_allowed")
        if (await snapshot())[0:1] != (before_result,) or (await snapshot())[2] != before_checkpoints:
            raise AssertionError("abandon_postcheck_changed")
    finally:
        delivery_id.reset(token)


async def _exercise_cooperative_resume(owner: Any, runtime: Any, schema: str, tenant_a: Any) -> None:
    """Real restricted transactions; provider and broker are deliberately offline."""
    if not EXECUTION_ENABLED:
        raise RuntimeError("pending_lifecycle_gate_unreviewed")
    from uuid import uuid4

    import ai_generation_checkpoint_dev_check as canonical
    from app.modules.ai.delivery_ownership import delivery_id
    from app.modules.ai.direct_luna_responses_client import DirectLunaResponsesClient
    from app.modules.ai.job_service import (
        InMemoryAIJobDispatcher, claim_generation_execution, get_ai_job,
        interrupt_claimed_generation_execution, resume_interrupted_ai_job,
    )
    from app.modules.ai.v3.cooperative_budget import CooperativeBudget, PreclaimYieldError, active_budget
    from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
    from app.modules.ai.v3.stage_checkpoint import stage_once
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    canonical.validate_schema(schema)
    job, actor, doc = str(uuid4()), uuid4(), str(uuid4())
    params = {"documents": [doc], "source_analysis": {
        "generation_engine": "evidence_v3", "analysis_mode": "direct_source"},
        "course_structure": {"generation_max_total_lessons": 3},
        "reference_decisions": [{"synthetic_bound_reference": "unchanged"}],
        "generation_reservation_required": True, "generation_reservation_released": False}
    async with owner.begin() as conn:
        await conn.execute(text(f'''INSERT INTO "{schema}".ai_jobs (id,tenant_id,user_id,status,params,result)
            VALUES(:j,:t,:u,'pending',CAST(:p AS json),CAST(:r AS json))'''),
            {"j": job, "t": tenant_a, "u": actor, "p": json.dumps(params), "r": '{"resume_count":0}'})
    sessions = async_sessionmaker(runtime, expire_on_commit=False)
    calls: list[str] = []
    async def verify(*_args: Any) -> bool:
        return True
    async def post(endpoint: str, _payload: dict[str, Any], **_kwargs: Any) -> str:
        calls.append(endpoint)
        if endpoint.endswith("input_tokens"):
            return json.dumps({"object": "response.input_tokens", "input_tokens": 12})
        return json.dumps({"model": "gpt-6-luna", "status": "completed", "output": [{"type": "message",
            "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": '{"ok":true}'}]}]})
    async def forbidden() -> dict[str, Any]:
        raise AssertionError("cooperative_legacy_invoker_called")
    async def snapshot() -> tuple[Any, Any]:
        async with sessions() as session:
            await canonical.set_tenant(session, tenant_a)
            p = await session.scalar(text("SELECT params FROM ai_jobs WHERE id=:j"), {"j": job})
            rows = (await session.execute(text('''SELECT r.generation_key,c.assessment_status,c.assessment_payload
                FROM ai_generation_runs r JOIN ai_generation_lesson_checkpoints c ON c.generation_run_id=r.id
                WHERE r.source_job_id=:j AND r.tenant_id=:t ORDER BY r.generation_key'''),
                {"j": job, "t": tenant_a})).all()
            return p, rows
    first_client = DirectLunaResponsesClient(api_key="synthetic", tenant_id=tenant_a, user_id=actor, job_id=job)
    first_client._post = post  # type: ignore[method-assign]
    arguments = {"stage": "lesson", "group_id": "complete", "source_sha256": "a"*64,
        "route_fingerprint": "b"*64, "messages": [{"role": "user", "content": "synthetic"}],
        "response_format": {"type": "json_object"}, "invoke": forbidden, "direct_max_output_tokens": 128}
    token = delivery_id.set(job)
    try:
        async with sessions() as session:
            if not await claim_generation_execution(session, job, str(tenant_a), job):
                raise AssertionError("cooperative_initial_claim_failed")
        journal = PendingStageJournal(str(tenant_a), actor, job, sessions, verify_source=verify)
        if await stage_once(journal, **arguments, direct_client=first_client) != {"ok": True}:
            raise AssertionError("cooperative_checkpoint_missing")
        before = await snapshot()
        async with sessions() as session:
            if await interrupt_claimed_generation_execution(session, job, str(tenant_a), "foreign"):
                raise AssertionError("cooperative_foreign_delivery_interrupted")
            if not await interrupt_claimed_generation_execution(session, job, str(tenant_a), job):
                raise AssertionError("cooperative_owned_interrupt_failed")
        if await snapshot() != before:
            raise AssertionError("cooperative_interruption_lost_state")
        dispatcher = InMemoryAIJobDispatcher()
        async with sessions() as session:
            await canonical.set_tenant(session, tenant_a)
            owned = await get_ai_job(session, job, tenant_id=str(tenant_a))
            if owned is None:
                raise AssertionError("cooperative_owned_job_missing")
            await resume_interrupted_ai_job(session, job=owned, tenant_id=tenant_a,
                task_kwargs={"job_id": job}, active_limit=8, worker_concurrency=1,
                historical_estimate_seconds=510, dispatcher=dispatcher)
        if len(dispatcher.submissions) != 1 or await snapshot() != before:
            raise AssertionError("cooperative_resume_changed_params_or_checkpoints")
        new_delivery = dispatcher.submissions[0][1]
        async with sessions() as session:
            if await claim_generation_execution(session, job, str(tenant_a), job):
                raise AssertionError("cooperative_old_delivery_reclaimed")
            if not await claim_generation_execution(session, job, str(tenant_a), new_delivery):
                raise AssertionError("cooperative_new_delivery_not_claimed")
        cold_token = delivery_id.set(new_delivery)
        budget_token = active_budget.set(CooperativeBudget(deadline=0))
        cold_client = DirectLunaResponsesClient(api_key="synthetic", tenant_id=tenant_a, user_id=actor, job_id=job)
        cold_client._post = post  # type: ignore[method-assign]
        try:
            cold = PendingStageJournal(str(tenant_a), actor, job, sessions, verify_source=verify)
            if await stage_once(cold, **arguments, direct_client=cold_client) != {"ok": True}:
                raise AssertionError("cooperative_cold_replay_failed")
            try:
                await stage_once(cold, **{**arguments, "group_id": "fresh"}, direct_client=cold_client)
            except PreclaimYieldError:
                pass
            else:
                raise AssertionError("cooperative_fresh_generation_not_yielded")
            if len(calls) != 2 or await snapshot() != before:
                raise AssertionError("cooperative_replay_or_yield_repeated_provider")
        finally:
            cold_client.close()
            active_budget.reset(budget_token)
            delivery_id.reset(cold_token)
    finally:
        first_client.close()
        delivery_id.reset(token)


async def exercise(owner: Any, runtime: Any, schema: str, tenant_a: Any, tenant_b: Any,
                   job_a: str, _resume_job: str, checks: list[str]) -> None:
    if not EXECUTION_ENABLED:
        raise RuntimeError("pending_lifecycle_gate_unreviewed")
    import ai_generation_checkpoint_dev_check as canonical
    from app.models.ai_job import AIJob
    from app.models.registry import load_all_models
    from app.modules.ai.delivery_ownership import delivery_id
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    from app.modules.ai.v3.pending_stage_transactions import (
        claim_with_pending,
        finalize_pending,
        pending_sql_predicate,
    )
    from app.modules.ai.v3.stage_checkpoint import _digest
    from app.modules.ai.worker_lesson_cycle import WorkerCycleJournal
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    canonical.validate_schema(schema)
    load_all_models()
    sessions = async_sessionmaker(runtime, expire_on_commit=False)
    async with runtime.begin() as conn:
        await canonical.set_tenant(conn, tenant_a)
        user_id = (await conn.execute(text(f'SELECT user_id FROM "{schema}".ai_jobs WHERE id=:id'),
                                      {"id": job_a})).scalar_one()
        await conn.execute(text(f'UPDATE "{schema}".ai_jobs SET params=CAST(:params AS json) WHERE id=:id'),
            {"id": job_a, "params": json.dumps({"source_analysis": {"generation_engine": "evidence_v3"}})})
    for payload, expected in (
        (None, False),
        ("null", False),
        ("{}", False),
        ('{"unrelated":true}', False),
        ('{"unrelated":{"v3_pending_stages":null}}', False),
        ('{"v3_pending_stages":null}', True),
        ('{"v3_pending_stages":{}}', True),
        ("[]", True),
        ('["v3_pending_stages"]', True),
        ('"synthetic"', True),
        ("42", True),
        ("true", True),
    ):
        async with sessions() as session:
            await canonical.set_tenant(session, tenant_a)
            await session.execute(text(f'UPDATE "{schema}".ai_jobs SET result=CAST(:value AS json) WHERE id=:id'),
                                  {"value": payload, "id": job_a})
            actual = await session.scalar(select(pending_sql_predicate()).where(AIJob.id == job_a))
            if actual is not expected:
                raise AssertionError("pending_presence_truth_invalid")
            await session.commit()
    checks.append("sql_null_absent_json_null_truth")
    async with runtime.begin() as conn:
        await canonical.set_tenant(conn, tenant_a)
        await conn.execute(text(f'UPDATE "{schema}".ai_jobs SET result=CAST(:value AS json) WHERE id=:id'),
                           {"value": json.dumps({"resume_count": 0}), "id": job_a})
    journal = WorkerCycleJournal(str(tenant_a), job_a, sessions)
    plan = {"tenant_id": str(tenant_a), "job_id": job_a, "kind": "synthetic-gate"}
    digest = _digest(plan)
    marker = {"identity": digest, "claim_token": "a" * 32}
    def validate(value: dict[str, Any]) -> dict[str, Any]:
        if value.get("identity") != digest or value.get("response") != {"synthetic": True}:
            raise ValueError("pending_gate_result_invalid")
        return value["response"]
    args = dict(journal=journal, user_id=user_id, plan=plan, result_key="pending-gate-result",
                claim_key="pending-gate-claim", marker=marker, validate=validate)
    token = delivery_id.set(job_a)
    try:
        if await claim_with_pending(**args) is not None:
            raise AssertionError("pending_initial_claim_invalid")
        try:
            await claim_with_pending(**args)
        except ExtractionOutcomeUnknownError as exc:
            if str(exc) != "v3_pending_existing":
                raise AssertionError("pending_duplicate_wrong_failure") from exc
        else:
            raise AssertionError("pending_duplicate_claim_accepted")
        async with sessions() as session:
            await canonical.set_tenant(session, tenant_b)
            if await session.scalar(select(AIJob.id).where(AIJob.id == job_a)) is not None:
                raise AssertionError("pending_foreign_tenant_visible")
        try:
            await finalize_pending(**(args | {"user_id": __import__("uuid").uuid4()}),
                                   value={"identity": digest, "response": {"synthetic": True}})
        except ExtractionOutcomeUnknownError as exc:
            if not isinstance(exc.__cause__, ValueError) or str(exc.__cause__) != "v3_pending_owner_invalid":
                raise AssertionError("pending_foreign_user_wrong_failure") from exc
        else:
            raise AssertionError("pending_foreign_user_accepted")
        async with sessions() as session:
            await canonical.set_tenant(session, tenant_a)
            if await session.scalar(select(pending_sql_predicate()).where(AIJob.id == job_a)) is not True:
                raise AssertionError("pending_foreign_user_marker_lost")
        result = await finalize_pending(**args, value={"identity": digest, "response": {"synthetic": True}})
        if result != {"synthetic": True}:
            raise AssertionError("pending_finalize_result_invalid")
        async with sessions() as session:
            await canonical.set_tenant(session, tenant_a)
            if await session.scalar(select(pending_sql_predicate()).where(AIJob.id == job_a)) is not False:
                raise AssertionError("pending_marker_not_cleared")
        # Hold the first transaction after its job lock, then start a distinct
        # claim in another session before permitting the first commit.
        from contextlib import asynccontextmanager

        locked, release, second_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
        pids: dict[str, int] = {}
        race_plan = {**plan, "kind": "synthetic-race-first"}
        race_digest = _digest(race_plan)
        race_args = args | {"plan": race_plan, "result_key": "pending-race-result-1",
                            "claim_key": "pending-race-claim-1",
                            "marker": {"identity": race_digest, "claim_token": "b" * 32}}
        second_plan = {**plan, "kind": "synthetic-race-second"}
        second_args = args | {"plan": second_plan, "result_key": "pending-race-result-2",
                              "claim_key": "pending-race-claim-2",
                              "marker": {"identity": _digest(second_plan), "claim_token": "c" * 32}}

        async def hold_first(_session: Any, _job: Any, _plan: Any) -> bool:
            pids["first"] = int(await _session.scalar(text("SELECT pg_backend_pid()")))
            locked.set()
            await release.wait()
            return True

        @asynccontextmanager
        async def second_session() -> Any:
            async with sessions() as session:
                pids["second"] = int(await session.scalar(text("SELECT pg_backend_pid()")))
                second_started.set()
                yield session

        second_journal = WorkerCycleJournal(str(tenant_a), job_a, second_session)
        second_args["journal"] = second_journal

        async def second_claim() -> Any:
            return await claim_with_pending(**second_args)

        async def run_race() -> None:
            first = asyncio.create_task(claim_with_pending(**race_args, verify_source=hold_first))
            second = None
            try:
                await locked.wait()
                second = asyncio.create_task(second_claim())
                await second_started.wait()
                async with runtime.connect() as observer:
                    blocked = False
                    for _ in range(50):
                        if second.done():
                            raise AssertionError("pending_race_second_not_blocked")
                        blocked = bool(await observer.scalar(text(
                            "SELECT :first = ANY(pg_blocking_pids(:second))"), pids))
                        if blocked:
                            break
                        await asyncio.sleep(0.1)
                    if not blocked:
                        raise AssertionError("pending_race_blocking_unverified")
                release.set()
                if await first is not None:
                    raise AssertionError("pending_race_first_not_claimed")
                try:
                    await second
                except ExtractionOutcomeUnknownError as exc:
                    if str(exc) != "v3_pending_existing":
                        raise AssertionError("pending_race_wrong_failure") from exc
                else:
                    raise AssertionError("pending_race_second_claimed")
            finally:
                release.set()
                for task in (first, second):
                    if task is not None and not task.done():
                        task.cancel()
                await asyncio.gather(*(task for task in (first, second) if task is not None), return_exceptions=True)

        await asyncio.wait_for(run_race(), timeout=20)
        def validate_race(value: dict[str, Any]) -> dict[str, Any]:
            if value.get("identity") != race_digest or value.get("response") != {"synthetic": True}:
                raise ValueError("pending_race_result_invalid")
            return value["response"]
        race_args["validate"] = validate_race
        race_value = {"identity": race_digest, "response": {"synthetic": True}}
        if await finalize_pending(**race_args, value=race_value) != {"synthetic": True}:
            raise AssertionError("pending_race_finalize_invalid")
        if await claim_with_pending(**race_args) != {"synthetic": True}:
            raise AssertionError("pending_race_replay_invalid")
        checks.append("concurrent_distinct_digest_claim_fenced")
        checks.extend(("owned_sequential_duplicate_finalize", "foreign_tenant_user_denied"))

        from app.modules.ai.direct_luna_responses_client import (
            DirectLunaResponsesClient,
            ResponsesClientError,
        )
        from app.modules.ai.direct_luna_responses_contract import (
            COUNT_ENDPOINT,
            GENERATION_ENDPOINT,
        )
        from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
        from app.modules.ai.v3.stage_checkpoint import stage_once, stage_plan

        async def verify_fixture(_session: Any, _job: Any, _plan: Any) -> bool:
            return True  # Synthetic fixture only; no source-fidelity claim.

        direct_journal = PendingStageJournal(str(tenant_a), user_id, job_a, sessions, verify_source=verify_fixture)
        client = DirectLunaResponsesClient(api_key="synthetic-only", tenant_id=tenant_a, user_id=user_id, job_id=job_a)
        calls: list[str] = []
        mode = "success"

        async def fake_post(endpoint: str, _payload: dict[str, Any], *, stage_id: str | None = None) -> str:
            if endpoint not in (COUNT_ENDPOINT, GENERATION_ENDPOINT):
                raise AssertionError("direct_gate_unexpected_endpoint")
            calls.append(endpoint)
            async with sessions() as check:
                await canonical.set_tenant(check, tenant_a)
                pending = await check.scalar(select(pending_sql_predicate()).where(AIJob.id == job_a))
            if endpoint == COUNT_ENDPOINT:
                if pending is not False:
                    raise AssertionError("direct_count_after_claim")
                if mode == "count_failure":
                    raise ResponsesClientError("synthetic_count_failure")
                return json.dumps({"object": "response.input_tokens", "input_tokens": 12})
            if pending is not True:
                raise AssertionError("direct_generation_without_claim")
            if mode == "unknown":
                raise ResponsesClientError("synthetic_unknown")
            return json.dumps({"model": "gpt-6-luna", "status": "completed", "output": [
                {"type": "message", "role": "assistant", "status": "completed",
                 "content": [{"type": "output_text", "text": '{"ok":true}'}]}]})

        # Replace the only transport method before stage invocation. No provider
        # endpoint can be reached by this exercise.
        client._post = fake_post

        async def forbidden_legacy() -> dict[str, Any]:
            raise AssertionError("direct_gate_legacy_invoke")

        async def direct_stage(group: str) -> dict[str, Any]:
            return await stage_once(direct_journal, stage="lesson", group_id=group,
                source_sha256="a" * 64, route_fingerprint="b" * 64,
                messages=[{"role": "user", "content": "synthetic"}], response_format={"type": "json_object"},
                invoke=forbidden_legacy, direct_client=client, direct_max_output_tokens=128)

        try:
            if await direct_stage("direct-success") != {"ok": True}:
                raise AssertionError("direct_result_invalid")
            if await direct_stage("direct-success") != {"ok": True} or calls != [COUNT_ENDPOINT, GENERATION_ENDPOINT]:
                raise AssertionError("direct_replay_called_transport")
            mode = "count_failure"
            try:
                await direct_stage("direct-count-failure")
            except ResponsesClientError:
                pass
            else:
                raise AssertionError("direct_count_failure_accepted")
            async with sessions() as check:
                await canonical.set_tenant(check, tenant_a)
                if await check.scalar(select(pending_sql_predicate()).where(AIJob.id == job_a)) is not False:
                    raise AssertionError("direct_count_failure_claimed")
                failed_plan = stage_plan(direct_journal, stage="lesson", group_id="direct-count-failure",
                    source_sha256="a" * 64, route_fingerprint="b" * 64,
                    messages=[{"role": "user", "content": "synthetic"}], response_format={"type": "json_object"})
                failed_digest = _digest(failed_plan)
                result_key = direct_journal._owned_key(f"v3-stage-result:{failed_digest}")
                claim_key = direct_journal._owned_key(f"v3-stage-claim:{failed_digest}")
                plans = await check.scalar(text("""SELECT count(*) FROM ai_generation_runs
                    WHERE tenant_id = CAST(:tenant AS uuid) AND source_job_id = :job
                    AND generation_key IN (:result_key, :claim_key)"""),
                    {"tenant": str(tenant_a), "job": job_a, "result_key": result_key, "claim_key": claim_key})
                if plans != 0:
                    raise AssertionError("direct_count_failure_plan_exists")
            mode = "unknown"
            try:
                await direct_stage("direct-unknown")
            except ExtractionOutcomeUnknownError:
                pass
            else:
                raise AssertionError("direct_unknown_not_held")
            before = list(calls)
            try:
                await direct_stage("direct-unknown")
            except ExtractionOutcomeUnknownError:
                pass
            else:
                raise AssertionError("direct_unknown_retried")
            if calls != before or calls != [COUNT_ENDPOINT, GENERATION_ENDPOINT, COUNT_ENDPOINT,
                                            COUNT_ENDPOINT, GENERATION_ENDPOINT]:
                raise AssertionError("direct_call_count_invalid")
            checks.append("direct_fake_count_claim_replay_unknown")
        finally:
            client.close()

        # Separate disposable-schema fixture: keep the unknown job above intact.
        async with sessions() as session:
            await canonical.set_tenant(session, tenant_a)
            rejected_job = await session.scalar(select(AIJob).where(AIJob.id == _resume_job))
            if rejected_job is None:
                raise AssertionError("rejection_fixture_missing")
            rejected_user = rejected_job.user_id
            rejected_job.status = "running"
            rejected_job.params = {"source_analysis": {"generation_engine": "evidence_v3"}}
            rejected_job.result = {"synthetic_rejection_fixture": True}
            await session.commit()
        rejection_calls: list[str] = []
        rejected_client = DirectLunaResponsesClient(api_key="synthetic-only", tenant_id=tenant_a,
                                                   user_id=rejected_user, job_id=_resume_job)
        async def fake_rejected_post(endpoint: str, _payload: dict[str, Any], *, stage_id: str | None = None) -> str:
            if endpoint not in (COUNT_ENDPOINT, GENERATION_ENDPOINT):
                raise AssertionError("rejection_unexpected_endpoint")
            rejection_calls.append(endpoint)
            if endpoint == COUNT_ENDPOINT:
                return json.dumps({"object": "response.input_tokens", "input_tokens": 12})
            return json.dumps({"model": "gpt-6-luna", "status": "incomplete",
                               "incomplete_details": {"reason": "max_output_tokens"},
                               "usage": {"input_tokens": 12, "output_tokens": 128}})
        rejected_client._post = fake_rejected_post
        rejection_journal = PendingStageJournal(str(tenant_a), rejected_user, _resume_job, sessions,
                                                verify_source=verify_fixture)
        rejection_args = dict(stage="lesson", group_id="direct-rejection",
            source_sha256="a" * 64, route_fingerprint="b" * 64,
            messages=[{"role": "user", "content": "synthetic"}], response_format={"type": "json_object"},
            invoke=forbidden_legacy, direct_max_output_tokens=128)
        rejection_plan = stage_plan(rejection_journal, **{key: rejection_args[key] for key in
            ("stage", "group_id", "source_sha256", "route_fingerprint", "messages", "response_format")})
        rejection_digest = _digest(rejection_plan)
        rejection_token = delivery_id.set(_resume_job)
        try:
            try:
                await stage_once(rejection_journal, **rejection_args, direct_client=rejected_client)
            except ExtractionOutcomeUnknownError:
                pass
            else:
                raise AssertionError("rejected_content_accepted")
            async with sessions() as check:
                await canonical.set_tenant(check, tenant_a)
                saved = await check.scalar(select(AIJob.result).where(AIJob.id == _resume_job))
                receipt = saved.get("v3_response_rejections", {}).get("entries", {}).get(rejection_digest)
                if (not isinstance(receipt, dict) or receipt.get("status") != "incomplete"
                        or receipt.get("reason") != "max_output_tokens"
                        or receipt.get("usage", {}).get("output_tokens") != 128
                        or not saved.get("synthetic_rejection_fixture")
                        or await check.scalar(select(pending_sql_predicate()).where(AIJob.id == _resume_job)) is not True):
                    raise AssertionError("rejection_receipt_not_durable")
            rejected_client.close()
            cold_client = DirectLunaResponsesClient(api_key="synthetic-only", tenant_id=tenant_a,
                                                    user_id=rejected_user, job_id=_resume_job)
            async def never_post(*_args: Any, **_kwargs: Any) -> str:
                raise AssertionError("rejection_cold_replay_called_provider")
            cold_client._post = never_post
            cold_journal = PendingStageJournal(str(tenant_a), rejected_user, _resume_job, sessions,
                                               verify_source=verify_fixture)
            try:
                await stage_once(cold_journal, **rejection_args, direct_client=cold_client)
            except ExtractionOutcomeUnknownError:
                pass
            else:
                raise AssertionError("rejection_cold_replay_accepted")
            finally:
                cold_client.close()
            if rejection_calls != [COUNT_ENDPOINT, GENERATION_ENDPOINT]:
                raise AssertionError("rejection_call_count_invalid")
            checks.append("direct_rejection_receipt_durable_cold_hold")
        finally:
            rejected_client.close()
            delivery_id.reset(rejection_token)
        await _exercise_budget_period(owner, runtime, schema, tenant_a, tenant_b)
        checks.append("historical_budget_period_refund_idempotent_rollback_rls")
        await _exercise_revision_policy(owner, runtime, schema, tenant_a, tenant_b)
        checks.append("fresh_revision_policy_source_drift_fenced")
        await _exercise_abandonment(owner, runtime, schema, tenant_a, tenant_b)
        checks.append("abandon_owned_pending_race_fenced")
        await _exercise_cooperative_resume(owner, runtime, schema, tenant_a)
        checks.append("cooperative_interrupt_resume_cold_replay_fenced")
    finally:
        delivery_id.reset(token)


async def execute_candidate(*, expected_source: str, expected_base_source: str, custody_path: Path) -> dict[str, Any]:
    """Canonical custody candidate; blocked outside exact-input CLI execution."""
    if not EXECUTION_ENABLED:
        raise RuntimeError("pending_lifecycle_gate_unreviewed")
    import ai_generation_realization_dev_check as base
    from dotenv import dotenv_values
    from kb_rag_isolated_dev_gate import (
        normalize_database_url,
        same_supabase_project,
        supabase_project_ref,
    )
    from sqlalchemy.engine import make_url

    if source_digest() != expected_source:
        raise ValueError("pending_lifecycle_source_mismatch")
    evidence_root = (ROOT / ".release-evidence" / "dev").resolve(strict=True)
    if custody_path.exists() or custody_path.is_symlink() or custody_path.parent.resolve(strict=True) != evidence_root:
        raise ValueError("pending_lifecycle_custody_path_invalid")
    cursor = custody_path.parent
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise ValueError("pending_lifecycle_custody_path_invalid")
        cursor = cursor.parent
    env_file = base.canonical_env_file()
    if env_file.is_symlink():
        raise ValueError("pending_lifecycle_environment_invalid")
    config = dotenv_values(env_file)
    url = config.get("SUPABASE_URL") or ""
    ref = supabase_project_ref(url)
    owner = normalize_database_url(config.get("MIGRATION_DATABASE_URL") or "")
    runtime = normalize_database_url(config.get("DATABASE_URL") or "")
    def exact_role(value: str, role: str) -> bool:
        parsed = make_url(value)
        return parsed.database == "postgres" and (
            (parsed.host == f"db.{ref}.supabase.co" and parsed.username == role)
            or ((parsed.host or "").endswith(".pooler.supabase.com") and parsed.username == f"{role}.{ref}"))
    if (hashlib.sha256(ref.encode("ascii")).hexdigest() != DEV_REF_SHA256
            or not all(same_supabase_project(item, url) for item in (owner, runtime))
            or not exact_role(owner, "postgres") or not exact_role(runtime, "lms_app")):
        raise ValueError("pending_lifecycle_environment_invalid")
    original = base.exercise
    try:
        base.exercise = exercise
        result = await base.execute(env_file=env_file, revision="0184", expected_source=expected_base_source,
                                    custody_path=custody_path)
    finally:
        base.exercise = original
    with custody_path.with_suffix(".result.json").open("x", encoding="utf-8") as handle:
        json.dump(result, handle, sort_keys=True)
    expected = {"runtime_role_restricted", "migration_upgrade_downgrade_reupgrade", "rls_force_and_acl",
                "sql_null_absent_json_null_truth", "owned_sequential_duplicate_finalize", "foreign_tenant_user_denied",
                "concurrent_distinct_digest_claim_fenced", "direct_fake_count_claim_replay_unknown",
                "direct_rejection_receipt_durable_cold_hold", "historical_budget_period_refund_idempotent_rollback_rls",
                "fresh_revision_policy_source_drift_fenced", "abandon_owned_pending_race_fenced",
                "cooperative_interrupt_resume_cold_replay_fenced"}
    checks = result.get("checks")
    if (source_digest() != expected_source or result.get("source_unchanged") is not True
            or result.get("passed") is not True or result.get("cleanup") is not True
            or result.get("shared_migration_head_unchanged") is not True or not isinstance(checks, list)
            or len(checks) != len(expected) or set(checks) != expected):
        raise ValueError("pending_lifecycle_gate_incomplete")
    return result


def main(argv: list[str] | None = None) -> int:
    global EXECUTION_ENABLED
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--expected-public-revision", default="")
    parser.add_argument("--expected-source-sha256", default="")
    parser.add_argument("--expected-base-sha256", default="")
    parser.add_argument("--custody-path", type=Path)
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({"status": "OFFLINE_ONLY", "source_sha256": source_digest(),
                          "project_sha256": DEV_REF_SHA256, "required_public_revision": "0184",
                          "custody": "canonical exclusive disposable-schema record and verified cleanup required",
                          "limitations": ["no database execution", "synthetic provider", "fixture RLS only",
                              "public cancellation endpoint and provider billing refund are not tested",
                              "race proves one synthetic two-session lock wait, not production worker fencing",
                              "legacy-plan migration and completed-job reconstruction untested",
                              "custody parent must be controlled; pathname replacement race remains"]}, sort_keys=True))
        return 0
    if (args.confirm != "RUN_SYNTHETIC_PENDING_LIFECYCLE_DEV" or args.expected_public_revision != "0184"
            or args.custody_path is None or not re.fullmatch(r"[0-9a-f]{64}", args.expected_source_sha256)
            or not re.fullmatch(r"[0-9a-f]{64}", args.expected_base_sha256)):
        print(json.dumps({"status": "BLOCKED", "reason": "exact_execution_arguments_required"}))
        return 2
    try:
        EXECUTION_ENABLED = True
        result = asyncio.run(execute_candidate(expected_source=args.expected_source_sha256,
            expected_base_source=args.expected_base_sha256, custody_path=args.custody_path))
        print(json.dumps({"status": "PASS", "source_sha256": args.expected_source_sha256,
                          "checks": sorted(result["checks"]), "cleanup": True,
                          "public_revision_unchanged": True}, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({"status": "BLOCKED", "reason": "gate_failed_or_identity_unverified"}))
        return 1
    finally:
        EXECUTION_ENABLED = False


if __name__ == "__main__":
    raise SystemExit(main())
