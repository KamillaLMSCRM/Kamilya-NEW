"""Real SQL/service proof in one owned schema; no external model or dispatch."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from workbench_document_dev_gate import GateBlocked, safe_schema, set_context


def require(condition, code):
    if not condition:
        raise GateBlocked(code)


def synthetic_generation_params(documents):
    # Exact existing0175 bind guard; a fake dispatcher is not a fake job owner.
    return {"documents": [str(item) for item in documents],
            "source_analysis": {"generation_engine": "evidence_v2"}}


async def verify_dialogue(owner, runtime, schema, checks, *, runtime_connections, migration):
    from app.models.document import Document
    from app.models.registry import load_all_models
    from app.models.tenants import Tenant
    from app.models.users import User
    from app.modules.ai import router as ai_router
    from app.modules.ai.schemas import AIJobResponse
    from app.modules.admin.superadmin.service import TENANT_DELETE_SQL
    from app.modules.methodologist_workbench import document_dialogue as service
    from app.modules.methodologist_workbench import document_intent as intent
    from app.modules.methodologist_workbench import document_service as plans
    from app.modules.methodologist_workbench.assignment_service import WorkbenchConflict, WorkbenchNotFound
    from app.modules.methodologist_workbench.document_dialogue_models import DocumentDialogueExchange as Exchange
    from app.modules.methodologist_workbench.document_dialogue_models import DocumentDialogueTask as Task
    from app.modules.methodologist_workbench.document_dialogue_schemas import (
        CreateDialogue, DialogueDraft, PreviewDialogue, SaveDialogue, SendDocumentMessage,
    )
    from app.modules.methodologist_workbench.document_intent import DocumentCandidate
    from app.modules.methodologist_workbench.plan_contract import ActorContext, ConfirmationRequest

    load_all_models()
    q = safe_schema(schema)
    tenant, foreign, actor_id, sibling, foreign_actor, student, doc_id = (uuid4() for _ in range(7))
    actor = ActorContext(tenant_id=tenant, actor_id=actor_id, active_role="methodologist")
    user = SimpleNamespace(id=actor_id, tenant_id=tenant, role="methodologist")
    draft = DialogueDraft(candidate=DocumentCandidate(language="ru", course_intent="Explain synthetic acceptance rules"))

    async with AsyncSession(owner, expire_on_commit=False) as db:
        await set_context(db, schema, tenant, actor_id)
        db.add_all([Tenant(id=tenant, name="Document dialogue synthetic", slug=f"dd-{tenant.hex}"),
                    Tenant(id=foreign, name="Foreign synthetic", slug=f"dd-{foreign.hex}")])
        await db.flush()
        db.add_all([User(id=identifier, tenant_id=tid, first_name="Synthetic", last_name="QA", role=role,
                        is_active=True, status="active") for identifier, tid, role in (
            (actor_id, tenant, "methodologist"), (sibling, tenant, "methodologist"),
            (foreign_actor, foreign, "methodologist"), (student, tenant, "student"))])
        db.add(Document(id=doc_id, tenant_id=tenant, uploaded_by=actor_id, title="Synthetic acceptance rules",
            content_type="text/plain", content_sha256="a" * 64, index_status="ready", lifecycle_status="active",
            version=1, index_revision=1))
        await db.commit()

    async def call(operation, caller=actor):
        async with AsyncSession(runtime, expire_on_commit=False) as db:
            try:
                await set_context(db, schema, caller.tenant_id, caller.actor_id)
                result = await operation(db, caller)
                await db.commit()
                return result
            except BaseException:
                await db.rollback()
                raise

    async def create(task_id=None):
        body = CreateDialogue(task_id=task_id or uuid4(), document_ids=[doc_id], language="ru", draft=draft)
        return await call(lambda db, a: service.create_task(db, a, body))

    async def read(task_id, caller=actor):
        return await call(lambda db, a: service.read_task(db, a, task_id), caller)

    async def send(task, instruction, request_id=None):
        body = SendDocumentMessage(request_id=request_id or uuid4(), expected_revision=task.revision, instruction=instruction)
        return await call(lambda db, a: service.send_message(db, a, task.id, body)), body

    async def reject(operation, kind=WorkbenchConflict, status=None):
        try:
            await operation
        except kind as error:
            if status is not None:
                require(error.status_code == status, "unexpected_http_status")
            return
        raise GateBlocked("expected_rejection_missing")

    async def sql(statement, params=None, *, runtime_actor=None, superadmin=False):
        engine = runtime if runtime_actor else owner
        async with engine.begin() as connection:
            await set_context(connection, schema,
                runtime_actor.tenant_id if runtime_actor else tenant,
                runtime_actor.actor_id if runtime_actor else actor_id)
            if superadmin:
                await connection.execute(text("SELECT set_config('app.is_superadmin','true',true)"))
            result = await connection.execute(text(statement), params or {})
            return result

    async def reject_sql(statement, params=None):
        try:
            await sql(statement, params, runtime_actor=actor)
        except DBAPIError as error:
            require(getattr(error.orig, "sqlstate", None) in {"23514", "42501"}, "unexpected_guard_sqlstate")
            return
        raise GateBlocked("sql_guard_missing")

    # Catalog proof, not just source markers.
    async with owner.connect() as connection:
        rows = (await connection.execute(text("SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:s AND c.relname=ANY(:tables)"),
            {"s": schema, "tables": [Task.__tablename__, Exchange.__tablename__]})).all()
        require(len(rows) == 2 and all(row[1] and row[2] for row in rows), "force_rls_missing")
        for table in (Task.__tablename__, Exchange.__tablename__):
            privileges = await connection.scalar(text("SELECT has_table_privilege('lms_app',:t,'SELECT,INSERT,UPDATE,DELETE')"), {"t": f"{schema}.{table}"})
            require(privileges, "runtime_acl_missing")
            unexpected = await connection.scalar(text("SELECT count(*) FROM information_schema.role_table_grants WHERE table_schema=:s AND table_name=:t AND grantee IN ('PUBLIC','anon','authenticated','service_role','lms_recovery')"), {"s": schema, "t": table})
            require(unexpected == 0, "unexpected_table_acl")
    checks.append("table_acl_force_rls")
    current = await create()
    body = CreateDialogue(task_id=current.id, document_ids=[doc_id], language="ru", draft=draft)
    replay = await call(lambda db, a: service.create_task(db, a, body))
    require(current == replay, "create_replay_changed")
    checks.append("exact_create_replay")
    concurrent_id = uuid4()
    pair = await asyncio.gather(create(concurrent_id), create(concurrent_id))
    require(pair[0] == pair[1], "concurrent_create_did_not_replay")
    checks.append("concurrent_create_replay")

    for identifier, tid, label in ((sibling, tenant, "sibling_actor_denied"), (foreign_actor, foreign, "foreign_tenant_denied")):
        caller = ActorContext(tenant_id=tid, actor_id=identifier, active_role="methodologist")
        await reject(read(current.id, caller), WorkbenchNotFound)
        result = await sql("SELECT id FROM workbench_document_dialogues WHERE id=:id", {"id": current.id}, runtime_actor=caller)
        require(result.first() is None, "rls_owner_leaked")
        checks.append(label)
    async with runtime.begin() as connection:
        await set_context(connection, schema)
        count = await connection.scalar(text("SELECT count(*) FROM workbench_document_dialogues"))
        require(count == 0, "no_context_visible")
    checks.append("no_context_denied")
    await sql("UPDATE users SET role='student' WHERE id=:id", {"id": actor_id})
    await reject(read(current.id), WorkbenchNotFound)
    await sql("UPDATE users SET role='methodologist' WHERE id=:id", {"id": actor_id})
    checks.append("role_denied")
    for identifier, tid in ((sibling, tenant), (foreign_actor, foreign)):
        caller = ActorContext(tenant_id=tid, actor_id=identifier, active_role="methodologist")
        update = await sql("UPDATE workbench_document_dialogues SET revision=revision+1 WHERE id=:id", {"id": current.id}, runtime_actor=caller)
        require(update.rowcount == 0, "foreign_task_update_allowed")
        try:
            await sql("INSERT INTO workbench_document_dialogues(id,tenant_id,actor_id,language,sources,creation_fingerprint,draft,revision) VALUES(:id,:tenant,:actor,'ru',CAST(:sources AS jsonb),:fingerprint,CAST(:draft AS jsonb),1)",
                {"id": uuid4(), "tenant": tenant, "actor": actor_id, "sources": json.dumps([source.model_dump(mode="json") for source in current.sources]),
                 "fingerprint": "d" * 64, "draft": draft.model_dump_json()}, runtime_actor=caller)
        except DBAPIError as error:
            require(getattr(error.orig, "sqlstate", None) == "42501", "foreign_insert_wrong_rejection")
        else:
            raise GateBlocked("foreign_task_insert_allowed")
    checks.append("cross_owner_writes_denied")

    provider_calls = []
    charge = AsyncMock(wraps=intent.check_and_charge_llm_budget)
    refund = AsyncMock(wraps=intent.refund_llm_budget)
    entered, release = asyncio.Event(), asyncio.Event()
    hold_instruction = None
    future_clock = None

    async def invoke(messages, *, provider_deadline_seconds):
        require(provider_deadline_seconds == 8, "provider_deadline_missing")
        require(runtime_connections() == 0, "provider_holds_database_connection")
        payload = json.loads(messages[1]["content"])
        provider_calls.append(payload)
        instruction = payload["instruction"]
        if future_clock and instruction == "New explicit request after interruption":
            future_clock.future = False
        if instruction == "Cancel synthetic request":
            raise asyncio.CancelledError()
        if instruction == "Unavailable synthetic provider":
            raise RuntimeError("Synthetic provider unavailable")
        if instruction == hold_instruction:
            entered.set()
            await release.wait()
        candidate = payload["untrusted_preparation_context"]["current_candidate"]
        return SimpleNamespace(content=json.dumps({"action": "document_draft", **candidate,
            "course_format": "brief" if "simpler" in instruction else candidate["course_format"]}))

    async def model(db, a, body, **kwargs):
        return await intent.interpret_document(db, a, body,
            provider_resolver=AsyncMock(return_value=SimpleNamespace(ainvoke=invoke)), **kwargs)

    with patch.object(service, "interpret_document", model), patch.object(intent, "check_and_charge_llm_budget", charge), patch.object(intent, "refund_llm_budget", refund):
        current, message = await send(current, "Make this variant simpler")
        require(len(provider_calls) == 1 and current.draft.candidate.course_format == "brief", "model_result_not_persisted")
        reread = await read(current.id)
        require(reread == current and len(provider_calls) == 1, "reload_reinferred_or_changed")
        checks += ["owner_reload_no_inference", "provider_connection_released"]
        replay = await call(lambda db, a: service.send_message(db, a, current.id, message))
        require(replay == current and len(provider_calls) == 1, "message_replay_reinferred")
        checks.append("exact_message_replay_one_fake_call")
        await reject(call(lambda db, a: service.send_message(db, a, current.id,
            message.model_copy(update={"instruction": "Different same key"}))))
        checks.append("changed_request_conflict")
        for index in range(5):
            current, _ = await send(current, f"Preserve safe rules {index}")
        require(len(provider_calls[-1]["untrusted_preparation_context"]["prior_instructions"]) == 4, "recall_not_bounded")
        checks.append("bounded_recall")
        preserved = await read(current.id)
        purge_task = await create()
        purge_task, _ = await send(purge_task, "Synthetic archive purge target")
        deleted_exchange = await sql("DELETE FROM workbench_document_dialogue_exchanges WHERE task_id=:task", {"task": purge_task.id}, runtime_actor=actor, superadmin=True)
        deleted_task = await sql("DELETE FROM workbench_document_dialogues WHERE id=:id", {"id": purge_task.id}, runtime_actor=actor, superadmin=True)
        require(deleted_exchange.rowcount == 1 and deleted_task.rowcount == 1 and preserved == await read(current.id), "authorized_purge_not_exact")
        checks.append("authorized_purge_exact_rows")

        hold_instruction = "Hold concurrent request"
        entered.clear(); release.clear()
        pending_body = SendDocumentMessage(request_id=uuid4(), expected_revision=current.revision, instruction=hold_instruction)
        running = asyncio.create_task(call(lambda db, a: service.send_message(db, a, current.id, pending_body)), name=f"document55-{uuid4().hex}")
        await asyncio.wait_for(entered.wait(), 20)
        before_calls = len(provider_calls)
        await reject(call(lambda db, a: service.send_message(db, a, current.id, pending_body)), HTTPException, 409)
        require(len(provider_calls) == before_calls, "pending_reinferred")
        checks.append("concurrent_pending_dedup")
        pending = await read(current.id)
        require(pending.pending_request_id == pending_body.request_id, "pending_not_projected")
        # Explicit new send reclaims only expired reservation. GET itself is read-only.
        class FutureClock:
            future = True
            @staticmethod
            def now(_zone):
                return datetime.now(UTC) + (timedelta(minutes=3) if FutureClock.future else timedelta())
        future_clock = FutureClock
        with patch.object(service, "datetime", FutureClock):
            interrupted = await read(current.id)
            require(interrupted.pending_request_id is None and interrupted.interrupted_request_id == pending_body.request_id,
                    "expired_pending_read_not_interrupted")
            current, _ = await send(interrupted, "New explicit request after interruption")
        release.set()
        await reject(running)
        current = await read(current.id)
        require(next(row for row in current.exchanges if row.id == pending_body.request_id).state == "failed", "late_overwrite")
        checks.append("late_response_refused")
        hold_instruction = None
        future_clock = None

        before_refunds = refund.await_count
        before_usage = (await sql("SELECT cost_cents,request_count FROM tenant_llm_usage WHERE tenant_id=:tenant", {"tenant": tenant})).one()
        await reject(send(current, "Cancel synthetic request"), asyncio.CancelledError)
        current = await read(current.id)
        require(current.exchanges[-1].state == "failed" and current.exchanges[-1].error_code == "interrupted"
                and refund.await_count == before_refunds + 1, "cancel_not_failed_refunded")
        after_usage = (await sql("SELECT cost_cents,request_count FROM tenant_llm_usage WHERE tenant_id=:tenant", {"tenant": tenant})).one()
        require(tuple(before_usage) == tuple(after_usage), "cancel_durable_budget_refund_failed")
        checks.append("cancel_interrupted")
        await reject(send(current, "Unavailable synthetic provider"), HTTPException, 503)
        current = await read(current.id)
        require(current.exchanges[-1].state == "failed" and current.exchanges[-1].error_code == "provider_unavailable", "provider_failure_not_durable")
        checks.append("provider_failure_durable")
        before_calls = len(provider_calls)
        charge.side_effect = HTTPException(429, "Synthetic budget denied")
        await reject(send(current, "Admission denied by budget"), HTTPException, 429)
        charge.side_effect = None
        current = await read(current.id)
        require(current.exchanges[-1].error_code == "budget_denied" and len(provider_calls) == before_calls, "budget_reason_or_no_model_failed")
        checks.append("budget_denial_no_inference")

        for committed in (False, True):
            boundary_task = await create()
            request = SendDocumentMessage(request_id=uuid4(), expected_revision=1, instruction="Commit boundary cancellation")
            before_calls = len(provider_calls)
            async def cancel_commit(db, a):
                original = db.commit
                attempts = 0
                async def commit():
                    nonlocal attempts
                    attempts += 1
                    if attempts == 1:
                        if committed:
                            await original()
                        else:
                            await db.rollback()
                        raise asyncio.CancelledError()
                    await original()
                with patch.object(db, "commit", commit):
                    return await service.send_message(db, a, boundary_task.id, request)
            await reject(call(cancel_commit), asyncio.CancelledError)
            recovered = await read(boundary_task.id)
            require(len(provider_calls) == before_calls, "cancelled_reservation_called_model")
            if committed:
                require(len(recovered.exchanges) == 1 and recovered.exchanges[0].state == "failed"
                        and recovered.exchanges[0].error_code == "interrupted", "committed_cancel_not_reconciled")
            else:
                require(recovered.revision == 1 and recovered.exchanges == [], "rolled_back_cancel_left_reservation")
        checks.append("reservation_commit_cancellation")

        hold_instruction = "Move source during model"
        entered.clear(); release.clear()
        moving = asyncio.create_task(send(current, hold_instruction), name=f"document55-{uuid4().hex}")
        await asyncio.wait_for(entered.wait(), 20)
        await sql("UPDATE documents SET tenant_id=:foreign WHERE id=:id", {"foreign": foreign, "id": doc_id})
        release.set()
        await reject(moving)
        stale = await read(current.id)
        require(stale.source_stale and stale.exchanges[-1].state == "failed" and stale.exchanges[-1].error_code == "source_stale", "moved_source_not_closed")
        await sql("UPDATE documents SET tenant_id=:tenant WHERE id=:id", {"tenant": tenant, "id": doc_id})
        current = await read(current.id)
        hold_instruction = None

    # Direct SQL terminal/scope invariants.
    completed = next(row for row in current.exchanges if row.state == "completed")
    await reject_sql("UPDATE workbench_document_dialogue_exchanges SET instruction='Changed' WHERE id=:id", {"id": completed.id})
    await reject_sql("UPDATE workbench_document_dialogues SET language='kk' WHERE id=:id", {"id": current.id})
    checks.append("terminal_rows_immutable")
    await sql("UPDATE documents SET version=2 WHERE id=:id", {"id": doc_id})
    stale = await read(current.id)
    require(stale.source_stale, "source_revision_drift_not_stale")
    await reject(call(lambda db, a: service.save_task(db, a, current.id, SaveDialogue(expected_revision=current.revision, draft=draft))))
    await sql("UPDATE documents SET version=1 WHERE id=:id", {"id": doc_id})
    checks.append("source_drift_stale")

    from document_content_dev_checks import verify_content
    await verify_content(owner=owner, runtime=runtime, schema=schema, actor=actor,
        foreign_actor=ActorContext(tenant_id=foreign, actor_id=foreign_actor, active_role="methodologist"),
        sibling=ActorContext(tenant_id=tenant, actor_id=sibling, active_role="methodologist"), doc_id=doc_id,
        create=create, call=call, read=read, sql=sql, reject=reject, require=require, checks=checks,
        runtime_connections=runtime_connections)

    preview = await call(lambda db, a: service.preview_task(db, a, current.id, PreviewDialogue(expected_revision=current.revision)))
    require((await read(current.id)).plan_id == preview.plan_id, "preview_link_missing")
    again = await call(lambda db, a: service.preview_task(db, a, current.id, PreviewDialogue(expected_revision=current.revision)))
    require(again.plan_id == preview.plan_id, "ready_preview_duplicated")
    await reject_sql("UPDATE workbench_document_dialogues SET revision=revision+1 WHERE id=:id", {"id": current.id})
    # Existing plan's expiry is immutable in0175; create a genuinely expired snapshot
    # using its supported deterministic clock seam, then link the same task revision.
    expired_task = await create()
    original_create_preview = service.create_document_preview
    async def expired_preview(*args, **kwargs):
        return await original_create_preview(*args, now=datetime.now(UTC) - timedelta(hours=1), **kwargs)
    with patch.object(service, "create_document_preview", expired_preview):
        expired = await call(lambda db, a: service.preview_task(db, a, expired_task.id, PreviewDialogue(expected_revision=1)))
    replacement = await call(lambda db, a: service.preview_task(db, a, expired_task.id, PreviewDialogue(expected_revision=1)))
    require(replacement.plan_id != expired.plan_id, "expired_preview_not_replaced")
    checks.append("preview_expiry_replacement")
    changed_draft = current.draft.model_copy(update={"instruction": "Explicit manual correction"})
    saved = await call(lambda db, a: service.save_task(db, a, current.id, SaveDialogue(expected_revision=current.revision, draft=changed_draft)))
    require(saved.plan_id is None and saved.revision == current.revision + 1, "save_not_invalidating")
    await reject(call(lambda db, a: service.save_task(db, a, current.id, SaveDialogue(expected_revision=current.revision, draft=draft))))
    await reject(call(lambda db, a: plans.confirm_document_plan(db, a, ConfirmationRequest(
        plan_id=preview.plan_id, revision=preview.revision, fingerprint=preview.fingerprint), user)))
    checks.append("save_revision_stale_preview")

    # Real shared job admission persists one job; synthetic dispatcher only.
    from app.modules.ai.job_service import submit_ai_job
    dispatched = []
    class Dispatcher:
        def dispatch(self, _task_name, *, task_id, kwargs):
            require(task_id == kwargs["job_id"], "dispatch_identity_mismatch")
            dispatched.append(task_id)

    async def admission(generation, db, caller, *, before_commit):
        job, _ = await submit_ai_job(db, tenant_id=caller.tenant_id, user_id=caller.id, course_id=None,
            params=synthetic_generation_params(generation.documents), task_name="generate_course",
            task_kwargs=lambda job: {"job_id": str(job.id)}, active_limit=20, worker_concurrency=1,
            historical_estimate_seconds=510, generation=False, dispatcher=Dispatcher(), before_commit=before_commit)
        return AIJobResponse(id=job.id, status=job.status, course_id=job.course_id,
                            created_at=job.created_at, updated_at=job.updated_at, job_type="generation")

    submitted_task = await create()
    ready = await call(lambda db, a: service.preview_task(db, a, submitted_task.id, PreviewDialogue(expected_revision=1)))
    confirmation = ConfirmationRequest(plan_id=ready.plan_id, revision=ready.revision, fingerprint=ready.fingerprint)
    with patch.object(ai_router, "submit_course_generation", admission):
        first = await call(lambda db, a: plans.confirm_document_plan(db, a, confirmation, user))
        second = await call(lambda db, a: plans.confirm_document_plan(db, a, confirmation, user))
    require(first.job.id == second.job.id and len(dispatched) == 1, "confirmation_not_single_job")
    checks.append("single_job_confirmation")
    await reject(call(lambda db, a: service.save_task(db, a, submitted_task.id, SaveDialogue(expected_revision=1, draft=changed_draft))))
    unknown_task = await create()
    unknown_plan = await call(lambda db, a: service.preview_task(db, a, unknown_task.id, PreviewDialogue(expected_revision=1)))
    await sql("DELETE FROM workbench_document_plans WHERE id=:id", {"id": unknown_plan.plan_id})
    require((await read(unknown_task.id)).plan_id == unknown_plan.plan_id, "unknown_locator_lost")
    await reject(call(lambda db, a: service.preview_task(db, a, unknown_task.id, PreviewDialogue(expected_revision=1))))
    checks.append("submitted_unknown_plan_blocked")

    async with owner.connect() as connection:
        try:
            await migration(connection, schema, "downgrade")
        except RuntimeError:
            await connection.rollback()
        else:
            raise GateBlocked("populated_downgrade_accepted")
    checks.append("populated_downgrade_refused")
    statements = [statement.strip() for statement in TENANT_DELETE_SQL]
    exchange_delete = "DELETE FROM workbench_document_dialogue_exchanges WHERE tenant_id = :tenant_id"
    task_delete = "DELETE FROM workbench_document_dialogues WHERE tenant_id = :tenant_id"
    require(statements.index(exchange_delete) < statements.index(task_delete) < statements.index("DELETE FROM users WHERE tenant_id = :tenant_id"), "purge_order_invalid")
    ordinary = await sql(exchange_delete, {"tenant_id": tenant}, runtime_actor=actor)
    require(ordinary.rowcount == 0, "ordinary_archive_delete_allowed")
    foreign_caller = ActorContext(tenant_id=foreign, actor_id=foreign_actor, active_role="methodologist")
    denied = await sql(task_delete, {"tenant_id": tenant}, runtime_actor=foreign_caller, superadmin=True)
    require(denied.rowcount == 0, "foreign_superadmin_purge_allowed")
    checks.append("purge_exchange_before_task")
    await sql("DELETE FROM documents WHERE id=:id", {"id": doc_id})
    require((await read(current.id)).source_stale, "deleted_source_history_unreadable")
    await reject(call(lambda db, a: service.preview_task(db, a, current.id, PreviewDialogue(expected_revision=saved.revision))))
    checks.append("source_move_delete_fail_closed")
    # FK cascades use exact synthetic parent IDs, not broad archive deletion.
    await sql("DELETE FROM users WHERE id=:id", {"id": actor_id})
    remaining = await sql("SELECT (SELECT count(*) FROM workbench_document_dialogues),(SELECT count(*) FROM workbench_document_dialogue_exchanges)")
    require(tuple(remaining.one()) == (0, 0), "actor_cascade_failed")
    foreign_doc = uuid4()
    async with AsyncSession(owner, expire_on_commit=False) as db:
        await set_context(db, schema, foreign, foreign_actor)
        db.add(Document(id=foreign_doc, tenant_id=foreign, uploaded_by=foreign_actor, title="Foreign synthetic source",
            content_type="text/plain", content_sha256="b" * 64, index_status="ready", lifecycle_status="active",
            version=1, index_revision=1))
        await db.commit()
    foreign_body = CreateDialogue(task_id=uuid4(), document_ids=[foreign_doc], language="ru", draft=draft)
    foreign_task = await call(lambda db, a: service.create_task(db, a, foreign_body), foreign_caller)
    require(foreign_task.id == foreign_body.task_id, "foreign_fixture_not_created")
    await sql("UPDATE workbench_document_dialogues SET revision=2 WHERE id=:id", {"id": foreign_task.id}, runtime_actor=foreign_caller)
    await sql("INSERT INTO workbench_document_dialogue_exchanges(id,task_id,tenant_id,actor_id,base_revision,fingerprint,instruction,state) VALUES(:id,:task,:tenant,:actor,1,:fingerprint,'Synthetic tenant cascade','pending')",
        {"id": uuid4(), "task": foreign_task.id, "tenant": foreign, "actor": foreign_actor, "fingerprint": "c" * 64}, runtime_actor=foreign_caller)
    await sql("DELETE FROM tenants WHERE id=:id", {"id": foreign})
    remaining = await sql("SELECT (SELECT count(*) FROM workbench_document_dialogues WHERE id=:id),(SELECT count(*) FROM workbench_document_dialogue_exchanges WHERE task_id=:id)", {"id": foreign_task.id})
    require(tuple(remaining.one()) == (0, 0), "tenant_cascade_failed")
    async with owner.connect() as connection:
        cascade = await connection.scalar(text("SELECT count(*) FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace JOIN pg_class parent ON parent.oid=c.confrelid WHERE n.nspname=:s AND t.relname IN ('workbench_document_dialogues','workbench_document_dialogue_exchanges') AND parent.relname IN ('users','tenants') AND c.confdeltype='c'"), {"s": schema})
        require(cascade == 4, "tenant_actor_cascade_fk_missing")
    checks.append("tenant_actor_cascade")
