"""Synthetic content Q&A through real owned SQL, retrieval and budget seams."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker


async def verify_content(*, owner, runtime, schema, actor, foreign_actor, sibling, doc_id,
                         create, call, read, sql, reject, require, checks, runtime_connections):
    from app.core import db as core_db
    from app.modules.methodologist_workbench import document_answers as answers
    from app.modules.methodologist_workbench import document_dialogue as service
    from app.modules.methodologist_workbench.assignment_service import WorkbenchConflict, WorkbenchNotFound
    from app.modules.methodologist_workbench.document_dialogue_schemas import PreviewDialogue, SendDocumentMessage
    from app.modules.methodologist_workbench.plan_contract import ActorContext

    # Clone exact column types/constraints, but use only owned synthetic neighbor policies.
    async with owner.begin() as connection:
        for table in ("document_embeddings", "embedding_active_revisions"):
            await connection.execute(text(f'CREATE TABLE "{schema}".{table} (LIKE public.{table} INCLUDING ALL)'))
            await connection.execute(text(f'REVOKE ALL ON "{schema}".{table} FROM PUBLIC,lms_app'))
            await connection.execute(text(f'GRANT SELECT,INSERT,UPDATE,DELETE ON "{schema}".{table} TO lms_app'))
            await connection.execute(text(f'ALTER TABLE "{schema}".{table} ENABLE ROW LEVEL SECURITY'))
            await connection.execute(text(f'ALTER TABLE "{schema}".{table} FORCE ROW LEVEL SECURITY'))
            predicate = "tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid"
            await connection.execute(text(f'CREATE POLICY gate_content_tenant ON "{schema}".{table} FOR ALL TO lms_app USING({predicate}) WITH CHECK({predicate})'))
    body = "Перед отгрузкой проверьте номер заказа. Повреждённый товар отгружать запрещено. Срок согласования возврата здесь не указан."
    async with owner.connect() as connection:
        dimensions = await connection.scalar(text("SELECT atttypmod FROM pg_attribute WHERE attrelid='public.document_embeddings'::regclass AND attname='embedding'"))
        require(type(dimensions) is int and 1 <= dimensions <= 4096, "content_embedding_type_unknown")
    chunk_id = hashlib.sha256(f"{actor.tenant_id}|{doc_id}|document:{'a'*64}|0|{body}".encode()).hexdigest()
    await sql("""INSERT INTO document_embeddings(id,tenant_id,doc_id,text,embedding_provider,embedding_model,
        embedding_revision,embedding_native_dimensions,embedding_storage_dimensions,embedding_content_sha256,
        embedding_source_revision,embedding_indexed_at,embedding_provenance_state,chunk_index,embedding)
        VALUES(:id,:tenant,:doc,:body,'synthetic','synthetic','r1',:dims,:dims,:hash,:revision,NOW(),'verified',0,:vector)""",
        {"id": chunk_id, "tenant": actor.tenant_id, "doc": str(doc_id), "body": body,
         "hash": hashlib.sha256(body.encode()).hexdigest(), "revision": f"document:{'a'*64}",
         "dims": dimensions, "vector": "[" + ",".join(["0"] * dimensions) + "]"})
    task = await create()
    initial_draft = task.draft
    provider_calls = []

    async def invoke(messages, **kwargs):
        require(runtime_connections() == 0, "content_provider_holds_connection")
        payload = json.loads(messages[1]["content"])
        provider_calls.append(payload)
        require(payload["excerpts"][0]["text"] == body, "content_retrieval_wrong_text")
        if payload["question"] == "Provider outage":
            raise RuntimeError("synthetic")
        if payload["question"] == "Missing with scope":
            return SimpleNamespace(content=json.dumps({"requested_dimensions": ["duration"], "status": "not_found", "answer": "Срок не указан.",
                "citations": [{"handle": 1}]}))
        if payload["question"] == "Malformed evidence":
            return SimpleNamespace(content=json.dumps({"requested_dimensions": ["duration"], "status": "not_found", "answer": "Срок не указан.",
                "citations": [{"handle": 1, "quote": "PRIVATE_UNVERIFIED_PROVIDER_OUTPUT"}]}))
        if payload["question"] in {"Pointer flip", "Pointer flip not found"}:
            await sql("UPDATE embedding_active_revisions SET active_revision_id='other',generation=generation+1 WHERE tenant_id=:tenant AND document_id=:doc",
                {"tenant": actor.tenant_id, "doc": str(doc_id)})
        if payload["question"] == "Pointer flip not found":
            return SimpleNamespace(content=json.dumps({"requested_dimensions": ["duration"], "status": "not_found", "answer": "В доступных фрагментах срок не указан.", "citations": []}))
        return SimpleNamespace(content=json.dumps({"requested_dimensions": ["actions"], "status": "supported", "answer": "Проверьте номер заказа.",
            "citations": [{"handle": 1}]}))

    with patch.object(core_db, "async_session_factory", async_sessionmaker(runtime, expire_on_commit=False)), \
         patch.object(answers.ResilientLLMClient, "from_settings_async", AsyncMock(return_value=SimpleNamespace(ainvoke=invoke))):
        request = SendDocumentMessage(request_id=uuid4(), expected_revision=task.revision, instruction="Что проверить перед отгрузкой?")
        task = await call(lambda db, a: service.send_message(db, a, task.id, request, content_question=True))
        require(task.draft == initial_draft and task.plan_id is None and task.exchanges[-1].response.state == "answered", "content_changed_preparation")
        require(task.exchanges[-1].response.citations[0].chunk_id == chunk_id
            and task.exchanges[-1].response.citations[0].quote == body, "content_real_chunk_identity")
        require(await read(task.id) == task, "content_reload_changed")
        require(await call(lambda db, a: service.send_message(db, a, task.id, request, content_question=True)) == task
            and len(provider_calls) == 1, "content_replay_reinferred")
        checks += ["content_real_retrieval_persistence_replay", "content_provider_connection_released"]
        excerpt = await call(lambda db, a: service.citation_source(db, a, task.id, request.request_id, 1))
        require(excerpt.excerpt == body, "content_citation_sql_mismatch")
        checks.append("content_source_sql_types_quote_hash")
        for caller in (sibling, foreign_actor):
            await reject(call(lambda db, a: service.citation_source(db, a, task.id, request.request_id, 1), caller), WorkbenchNotFound)
            await reject(call(lambda db, a: service.send_message(db, a, task.id, request, content_question=True), caller), WorkbenchNotFound)
        checks.append("content_foreign_actor_tenant_denied")
        await sql("UPDATE documents SET version=2 WHERE id=:id", {"id": doc_id})
        await reject(call(lambda db, a: service.citation_source(db, a, task.id, request.request_id, 1)), WorkbenchConflict)
        await sql("UPDATE documents SET version=1 WHERE id=:id", {"id": doc_id})
        checks.append("content_stale_citation_denied")
        second = SendDocumentMessage(request_id=uuid4(), expected_revision=task.revision, instruction="Объясни проще")
        task = await call(lambda db, a: service.send_message(db, a, task.id, second, content_question=True))
        require(provider_calls[-1]["untrusted_history"] == []
            and provider_calls[-1]["untrusted_previous_turn"] == {
                "question": request.instruction, "answer": "Проверьте номер заказа."}
            and task.draft == initial_draft, "content_followup_lost")
        checks.append("content_recall_separate_from_draft")
        missing_scope = SendDocumentMessage(request_id=uuid4(), expected_revision=task.revision, instruction="Missing with scope")
        task = await call(lambda db, a: service.send_message(db, a, task.id, missing_scope, content_question=True))
        response = task.exchanges[-1].response
        require(response.status == "not_found" and len(response.citations) == 1 and task.draft == initial_draft
            and task.plan_id is None, "content_missing_scope_not_persisted")
        count = len(provider_calls)
        require(await call(lambda db, a: service.send_message(db, a, task.id, missing_scope, content_question=True)) == task
            and len(provider_calls) == count, "content_missing_scope_replay_reinferred")
        excerpt = await call(lambda db, a: service.citation_source(db, a, task.id, missing_scope.request_id, 1))
        require(response.citations[0].quote == body and response.citations[0].quote in excerpt.excerpt,
            "content_missing_scope_quote_lost")
        checks.append("content_not_found_scope_quote_persistence")
        usage = tuple((await sql("SELECT cost_cents,request_count FROM tenant_llm_usage WHERE tenant_id=:tenant", {"tenant": actor.tenant_id})).one())
        malformed = SendDocumentMessage(request_id=uuid4(), expected_revision=task.revision, instruction="Malformed evidence")
        await reject(call(lambda db, a: service.send_message(db, a, task.id, malformed, content_question=True)), HTTPException, 502)
        require(tuple((await sql("SELECT cost_cents,request_count FROM tenant_llm_usage WHERE tenant_id=:tenant", {"tenant": actor.tenant_id})).one()) == usage, "content_invalid_refund_not_durable")
        task = await read(task.id)
        require(task.exchanges[-1].error_code == "invalid_response" and task.exchanges[-1].response is None,
            "content_invalid_response_not_private")
        checks.append("content_invalid_response_private_refund")
        failed = SendDocumentMessage(request_id=uuid4(), expected_revision=task.revision, instruction="Provider outage")
        await reject(call(lambda db, a: service.send_message(db, a, task.id, failed, content_question=True)), HTTPException, 503)
        require(tuple((await sql("SELECT cost_cents,request_count FROM tenant_llm_usage WHERE tenant_id=:tenant", {"tenant": actor.tenant_id})).one()) == usage, "content_budget_refund_not_durable")
        require((await read(task.id)).exchanges[-1].error_code == "provider_unavailable", "content_failure_not_durable")
        checks.append("content_real_budget_refund")
        await sql("UPDATE document_embeddings SET embedding_index_revision_id='legacy',embedding_reindex_run_id='fixture-run' WHERE id=:id", {"id": chunk_id})
        await sql("INSERT INTO embedding_active_revisions(tenant_id,document_id,active_revision_id,generation) VALUES(:tenant,:doc,'legacy',1)",
                  {"tenant": actor.tenant_id, "doc": str(doc_id)})
        task = await read(task.id)
        flipped = SendDocumentMessage(request_id=uuid4(), expected_revision=task.revision, instruction="Pointer flip")
        await reject(call(lambda db, a: service.send_message(db, a, task.id, flipped, content_question=True)), WorkbenchConflict)
        require((await read(task.id)).exchanges[-1].error_code == "source_stale", "content_pointer_race_not_stale")
        checks.append("content_active_pointer_race_denied")
        await sql("UPDATE embedding_active_revisions SET active_revision_id='legacy',generation=generation+1 WHERE tenant_id=:tenant AND document_id=:doc",
                  {"tenant": actor.tenant_id, "doc": str(doc_id)})
        task = await read(task.id)
        missing = SendDocumentMessage(request_id=uuid4(), expected_revision=task.revision, instruction="Pointer flip not found")
        await reject(call(lambda db, a: service.send_message(db, a, task.id, missing, content_question=True)), WorkbenchConflict)
        require((await read(task.id)).exchanges[-1].error_code == "source_stale", "content_not_found_pointer_race_not_stale")
        checks.append("content_not_found_pointer_race_denied")
        await sql("UPDATE embedding_active_revisions SET active_revision_id='legacy',generation=generation+1 WHERE tenant_id=:tenant AND document_id=:doc",
                  {"tenant": actor.tenant_id, "doc": str(doc_id)})
    plan_task = await create()
    await call(lambda db, a: service.preview_task(db, a, plan_task.id, PreviewDialogue(expected_revision=1)))
    request = SendDocumentMessage(request_id=uuid4(), expected_revision=1, instruction="Question")
    await reject(call(lambda db, a: service.send_message(db, a, plan_task.id, request, content_question=True)), WorkbenchConflict)
    checks.append("content_preserves_frozen_preview")
