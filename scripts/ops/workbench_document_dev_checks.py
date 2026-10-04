"""Bounded real document-plan/RLS/admission checks; no generator/provider/task."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kb_rag_isolated_dev_gate import GateBlocked


async def verify_service(owner_engine, runtime_engine, schema, context, migration):
    from app.models.document import Document
    from app.models.registry import load_all_models
    from app.models.tenants import Tenant
    from app.models.users import User
    from app.modules.ai import router as ai
    from app.modules.ai.job_service import AIJobSubmissionUnavailableError, submit_ai_job
    from app.modules.ai.schemas import AIJobResponse
    from app.modules.methodologist_workbench import document_service as service
    from app.modules.methodologist_workbench.document_schemas import DocumentGenerationRequest, DocumentPreviewRequest
    from app.modules.methodologist_workbench.plan_contract import ActorContext, ConfirmationRequest

    load_all_models()
    tenant, foreign, actor_id, sibling_id, foreign_actor, doc_id = (uuid4() for _ in range(6))
    actor = ActorContext(tenant_id=tenant, actor_id=actor_id, active_role="methodologist")
    user = SimpleNamespace(id=actor_id, tenant_id=tenant, role="methodologist")
    async with AsyncSession(owner_engine, expire_on_commit=False) as db:
        await context(db, schema, tenant, actor_id)
        db.add_all([Tenant(id=tenant, name="Document gate", slug=f"gate-{tenant.hex}"),
                    Tenant(id=foreign, name="Foreign gate", slug=f"gate-{foreign.hex}")])
        await db.flush()
        db.add_all([User(id=actor_id, tenant_id=tenant, first_name="Owner", last_name="Synthetic", role="methodologist"),
                    User(id=sibling_id, tenant_id=tenant, first_name="Sibling", last_name="Synthetic", role="methodologist"),
                    User(id=foreign_actor, tenant_id=foreign, first_name="Foreign", last_name="Synthetic", role="methodologist"),
                    Document(id=doc_id, tenant_id=tenant, uploaded_by=actor_id, title="Synthetic rules",
                             content_type="text/plain", content_sha256="a" * 64, index_status="ready")])
        await db.commit()
    body = DocumentPreviewRequest(instruction="Create a synthetic course", generation=DocumentGenerationRequest(
        documents=[doc_id], course_intent="Explain the synthetic rules", language="ru"))
    async def preview(at=None):
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await context(db, schema, tenant, actor_id)
            result = await service.create_document_preview(db, actor, body, now=at)
            await db.commit()
            return result
    async def counts():
        async with runtime_engine.begin() as db:
            await context(db, schema, tenant, actor_id)
            return tuple((await db.execute(text("SELECT (SELECT count(*) FROM ai_jobs),"
                "(SELECT count(*) FROM workbench_document_plans WHERE status='submitted')"))).one())
    plan = await preview()
    if await counts() != (0, 0):
        raise GateBlocked("preview_admitted_job")
    checks = ["preview_no_job"]
    for caller in (ActorContext(tenant_id=foreign, actor_id=foreign_actor, active_role="methodologist"),
                   ActorContext(tenant_id=tenant, actor_id=sibling_id, active_role="methodologist")):
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await context(db, schema, caller.tenant_id, caller.actor_id)
            for operation in ("read", "confirm"):
                try:
                    if operation == "read":
                        await service.get_document_plan(db, caller, plan.plan_id)
                    else:
                        await service.confirm_document_plan(db, caller, ConfirmationRequest(
                            plan_id=plan.plan_id, revision=plan.revision, fingerprint=plan.fingerprint), user)
                except service.WorkbenchNotFound:
                    pass
                else:
                    raise GateBlocked("foreign_plan_visible")
    checks += ["foreign_tenant_denied", "foreign_actor_denied"]
    dispatch_ids = []
    fail_dispatch = False
    fail_binding = False
    class Dispatcher:
        def dispatch(self, _task_name, *, task_id, kwargs):
            if task_id != kwargs["job_id"]:
                raise GateBlocked("dispatch_identity_mismatch")
            dispatch_ids.append(kwargs["job_id"])
            if fail_dispatch:
                raise AIJobSubmissionUnavailableError("Synthetic queue unavailable")
    async def admission(generation, db, caller, *, before_commit):
        async def bind(job):
            await before_commit(job)
            if fail_binding:
                raise RuntimeError("synthetic_binding_failure")
        job, _ = await submit_ai_job(db, tenant_id=caller.tenant_id, user_id=caller.id, course_id=None,
            params={"documents": [str(i) for i in generation.documents], "source_analysis": {"generation_engine": "evidence_v2"}},
            task_name="generate_course", task_kwargs=lambda job: {"job_id": str(job.id)}, active_limit=20,
            worker_concurrency=1, historical_estimate_seconds=510, generation=False,
            dispatcher=Dispatcher(), before_commit=bind)
        return AIJobResponse(id=job.id, status=job.status, course_id=job.course_id,
                             created_at=job.created_at, updated_at=job.updated_at, job_type="generation")
    async def confirm(p, **wrong):
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await context(db, schema, tenant, actor_id)
            try:
                result = await service.confirm_document_plan(db, actor, ConfirmationRequest(
                    plan_id=p.plan_id, revision=wrong.get("revision", p.revision),
                    fingerprint=wrong.get("fingerprint", p.fingerprint)), user)
                await db.commit()
                return result
            except BaseException:
                await db.rollback()
                raise
    with patch.object(ai, "submit_course_generation", admission):
        for wrong in ({"revision": 2}, {"fingerprint": "b" * 64}):
            try:
                await confirm(plan, **wrong)
            except service.WorkbenchConflict:
                pass
            else:
                raise GateBlocked("confirmation_mismatch_accepted")
        expired = await preview(datetime.now(UTC) - timedelta(hours=1))
        try:
            await confirm(expired)
        except service.WorkbenchConflict:
            pass
        else:
            raise GateBlocked("expired_accepted")
        async with owner_engine.begin() as db:
            await db.execute(text(f'UPDATE "{schema}".documents SET content_sha256=:hash WHERE id=:id'), {"hash": "b" * 64, "id": doc_id})
        try:
            await confirm(plan)
        except service.WorkbenchConflict:
            pass
        else:
            raise GateBlocked("stale_source_accepted")
        async with owner_engine.begin() as db:
            await db.execute(text(f'UPDATE "{schema}".documents SET content_sha256=:hash WHERE id=:id'), {"hash": "a" * 64, "id": doc_id})
        checks += ["revision_fingerprint_denied", "expiry_denied", "stale_source_denied"]
        fail_binding = True
        try:
            await confirm(plan)
        except RuntimeError:
            pass
        else:
            raise GateBlocked("binding_failure_accepted")
        fail_binding = False
        if await counts() != (0, 0) or dispatch_ids:
            raise GateBlocked("binding_failure_persisted")
        checks.append("binding_failure_rolls_back_job_and_plan")
        async def fail_commit(_db):
            raise RuntimeError("synthetic_commit_failure")
        with patch.object(AsyncSession, "commit", fail_commit):
            try:
                await confirm(plan)
            except RuntimeError:
                pass
            else:
                raise GateBlocked("commit_failure_accepted")
        if await counts() != (0, 0) or dispatch_ids:
            raise GateBlocked("commit_failure_persisted")
        checks.append("commit_failure_rolls_back_job_and_plan")
        first, second = await asyncio.gather(confirm(plan), confirm(plan))
        if first.job.id != second.job.id or await counts() != (1, 1) or dispatch_ids != [first.job.id]:
            raise GateBlocked("concurrent_confirmation_duplicated")
        checks.append("concurrent_one_job_one_dispatch")
        async with runtime_engine.begin() as db:
            await context(db, schema, tenant, actor_id)
            if not await db.scalar(text("SELECT admitted_at IS NOT NULL FROM workbench_document_plans WHERE id=:id"), {"id": plan.plan_id}):
                raise GateBlocked("admission_timestamp_missing")
            for sql in ("UPDATE workbench_document_plans SET status='ready',job_id=NULL WHERE id=:id",
                        "UPDATE workbench_document_plans SET snapshot='{}'::jsonb WHERE id=:id",
                        "UPDATE workbench_document_plans SET admitted_at=now() WHERE id=:id"):
                try:
                    async with db.begin_nested():
                        await db.execute(text(sql), {"id": plan.plan_id})
                except DBAPIError as exc:
                    if getattr(exc.orig, "sqlstate", None) not in {"42501", "P0001"}:
                        raise GateBlocked("immutable_plan_unexpected_sqlstate") from None
                else:
                    raise GateBlocked("immutable_plan_mutation_accepted")
        checks += ["database_owned_timestamp", "immutable_plan_grants_and_trigger"]
        async with owner_engine.begin() as db:
            await db.execute(text(f'UPDATE "{schema}".ai_jobs SET status=\'failed\' WHERE id=:id'), {"id": first.job.id})
        replay = await confirm(plan)
        if replay.job.id != first.job.id or replay.job.status != "failed" or len(dispatch_ids) != 1:
            raise GateBlocked("failed_replay_redispatched")
        checks.append("failed_job_replay_no_dispatch")
        queue_failure = await preview()
        fail_dispatch = True
        try:
            await confirm(queue_failure)
        except AIJobSubmissionUnavailableError:
            pass
        else:
            raise GateBlocked("queue_failure_not_reported")
        fail_dispatch = False
        saved_failure = await confirm(queue_failure)
        if saved_failure.job.status != "failed" or saved_failure.job.id != dispatch_ids[-1] or await counts() != (2, 2):
            raise GateBlocked("queue_failure_not_durable")
        if len(dispatch_ids) != 2:
            raise GateBlocked("queue_failure_replay_dispatch")
        checks.append("broker_failure_failed_job_retained_without_redispatch")
    async with owner_engine.begin() as db:
        try:
            async with db.begin_nested():
                await migration(db, schema, "downgrade")
        except RuntimeError:
            pass
        else:
            raise GateBlocked("populated_downgrade_accepted")
    return checks + ["populated_downgrade_denied"]
