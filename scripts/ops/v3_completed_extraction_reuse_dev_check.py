"""Disposable-schema real PostgreSQL reuse exercise; no model transport."""
from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any
from uuid import uuid4


async def _exercise(owner: Any, runtime: Any, schema: str, *, execution_enabled: bool = False, phase: dict[str, str]) -> None:
    if execution_enabled is not True:
        raise RuntimeError("reuse_gate_unreviewed")
    from datetime import datetime
    import ai_generation_checkpoint_dev_check as canonical
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.models.ai_job import AIJob
    from app.modules.ai.delivery_ownership import delivery_id
    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.job_service import abandon_unknown_generation, interrupt_claimed_generation_execution, is_resumable_generation_job
    from app.modules.ai.managed_luna_client import ManagedLunaClient
    from app.modules.ai.qa_luna_dev_route import QA_TENANT
    from app.modules.ai.v3.completed_extraction_reuse import PARENT_KEY, REUSE_KEY, validate_parent_admission
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError, _digest, extract_once
    from app.modules.ai.v3.owned_route_binding import KEY as ROUTE_KEY, POLICY as ROUTE_POLICY
    from app.modules.ai.v3.owned_source_context import OwnedSourceContext
    from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
    from app.modules.ai.v3.qa_luna_pending_policy import KEY, MANAGED_POLICY
    from app.modules.ai.v3.revision_policy import stamp_policy
    from app.modules.ai.v3.stage_checkpoint import stage_once
    from types import SimpleNamespace

    canonical.validate_schema(schema)
    tenant, actor, document = QA_TENANT, uuid4(), uuid4()
    parent, child = str(uuid4()), str(uuid4())
    content = "Synthetic completed extraction " + str(document)
    source_sha = hashlib.sha256(content.encode()).hexdigest()
    params = {"documents": [str(document)], "reference_decisions": [],
              "source_analysis": stamp_policy({"generation_engine": "evidence_v3", KEY: MANAGED_POLICY})}
    sessions = async_sessionmaker(runtime, expire_on_commit=False)
    def client(job: str) -> ManagedLunaClient:
        return ManagedLunaClient(base_url="http://10.77.77.2:18999/v1", api_key="synthetic-only",
            tenant_id=tenant, user_id=actor, job_id=job, credential_revision="synthetic")
    parent_client, child_client = client(parent), client(child)
    route = {"policy": ROUTE_POLICY, "fingerprint": parent_client.cache_fingerprint()}
    phase["value"] = "fixture"
    async with owner.begin() as conn:
        await conn.execute(text(f'INSERT INTO "{schema}".tenants(id,name,slug) VALUES(:t,:name,:s)'),
                           {"t": tenant, "name": "Synthetic reuse", "s": "synthetic-reuse-" + str(document)})
        await conn.execute(text(f'''INSERT INTO "{schema}".documents
            (id,tenant_id,uploaded_by,title,filename,content_type,file_size,category,content_sha256,lifecycle_status)
            VALUES(:d,:t,:a,'synthetic','synthetic.txt','text/plain',:size,'general',:sha,'active')'''),
            {"d": document, "t": tenant, "a": actor, "size": len(content), "sha": source_sha})
        for job, extra, when in ((parent, {}, "2026-10-01T01:00:00Z"),
                                 (child, {PARENT_KEY: parent}, "2026-10-01T02:00:00Z")):
            await conn.execute(text(f'''INSERT INTO "{schema}".ai_jobs
                (id,tenant_id,user_id,status,params,result,created_at)
                VALUES(:j,:t,:a,'running',CAST(:p AS json),CAST(:r AS json),CAST(:when AS timestamptz))'''),
                {"j": job, "t": tenant, "a": actor, "p": json.dumps(params | extra),
                 "r": json.dumps({ROUTE_KEY: route}), "when": datetime.fromisoformat(when.replace("Z", "+00:00"))})
    doc = DirectSourceDocument(str(document), "synthetic", "synthetic.txt", "general",
                               "document:" + source_sha, (), source_text=content)
    corpus = DirectSourceCorpus(str(tenant), (doc,), len(content), 0)
    def journal(job: str) -> PendingStageJournal:
        value = PendingStageJournal(str(tenant), actor, job, sessions)
        source = OwnedSourceContext(corpus, value, tenant, actor, job, (str(document),))
        value.verify_source = source.verify_locked
        return value
    parent_journal, child_journal = journal(parent), journal(child)
    child_journal.completed_extraction_parent_job_id = parent
    messages = [{"role": "user", "content": "synthetic extraction"}]
    identity = {"tenant_id": str(tenant), "job_id": parent, "document_id": str(document),
        "source_revision": doc.source_revision, "source_sha256": source_sha, "unit_sha256": source_sha,
        "context_sha256": hashlib.sha256(b"").hexdigest(), "prompt_sha256": _digest(messages),
        "route_fingerprint": parent_client.cache_fingerprint(), "unit_start": "0", "unit_end": str(len(content))}
    response = {"rules": [{"rule_id": "r1", "statement": content, "source_quote": content}]}
    async def prepare(_messages: Any, **options: Any) -> object:
        if await options["ownership_checkpoint"]() is not True:
            raise AssertionError("reuse_parent_prepare_unowned")
        return object()
    async def complete(_capability: Any, **options: Any) -> Any:
        if await options["ownership_checkpoint"]() is not True:
            raise AssertionError("reuse_parent_invoke_unowned")
        return SimpleNamespace(content=response, model="gpt-5.6-luna", usage=SimpleNamespace(
            input_tokens=7, output_tokens=3, cached_input_tokens=None, reasoning_tokens=None))
    async def forbidden(*_args: Any, **_options: Any) -> Any:
        raise AssertionError("reuse_called_model")
    parent_client.prepare, parent_client.invoke = prepare, complete
    phase["value"] = "parent_extraction"
    token = delivery_id.set(parent)
    try:
        saved = await extract_once(parent_journal, identity, forbidden,
                                   direct_client=parent_client, direct_messages=messages)
        if saved != response:
            raise AssertionError("reuse_parent_result_invalid")
        async def unknown(*_args: Any, **_options: Any) -> Any:
            raise RuntimeError("synthetic_unknown")
        parent_client.invoke = unknown
        try:
            await stage_once(parent_journal, stage="lesson", group_id="unknown-parent-lesson",
                source_sha256=source_sha, route_fingerprint=parent_client.cache_fingerprint(),
                messages=messages, response_format={"type": "json_object"}, invoke=forbidden,
                direct_client=parent_client)
        except ExtractionOutcomeUnknownError:
            pass
        else:
            raise AssertionError("reuse_parent_unknown_not_held")
        phase["value"] = "parent_abandon"
        async with sessions() as session:
            await canonical.set_tenant(session, tenant)
            await abandon_unknown_generation(session, job_id=parent, tenant_id=tenant, user_id=actor)
            await session.commit()
    finally:
        delivery_id.reset(token)
    async def parent_snapshot() -> str:
        async with sessions() as session:
            await canonical.set_tenant(session, tenant)
            row = await session.scalar(select(AIJob).where(AIJob.id == parent))
            cps = (await session.execute(text(f'''SELECT r.plan_payload,c.content_status,c.review_status,
                c.assessment_status,c.assessment_payload FROM "{schema}".ai_generation_runs r
                JOIN "{schema}".ai_generation_lesson_checkpoints c ON c.generation_run_id=r.id
                WHERE r.source_job_id=:j ORDER BY r.generation_key'''), {"j": parent})).all()
            return _digest([row.status, row.params, row.result, [list(x) for x in cps]])
    phase["value"] = "snapshot"
    before = await parent_snapshot()
    token = delivery_id.set(child)
    child_client.prepare = child_client.invoke = forbidden
    try:
        async with sessions() as session:
            await canonical.set_tenant(session, tenant)
            await validate_parent_admission(session, tenant_id=tenant, user_id=actor, parent_job_id=__import__('uuid').UUID(parent),
                policy=MANAGED_POLICY, documents=params["documents"], references=[], course_id=None)
        async def reuse_once() -> dict[str, Any]:
            cold = journal(child)
            cold.completed_extraction_parent_job_id = parent
            return await extract_once(cold, identity | {"job_id": child}, forbidden,
                                      direct_client=child_client, direct_messages=messages)
        phase["value"] = "concurrent_cold"
        if await asyncio.gather(reuse_once(), reuse_once()) != [response, response]:
            raise AssertionError("reuse_concurrent_or_cold_response_invalid")
        async with sessions() as session:
            await canonical.set_tenant(session, tenant)
            row = await session.scalar(select(AIJob).where(AIJob.id == child))
            if len(row.result[REUSE_KEY]["entries"]) != 1 or "direct_metadata" in row.result:
                raise AssertionError("reuse_origin_or_usage_invalid")
            count = await session.scalar(text(f'SELECT count(*) FROM "{schema}".ai_generation_runs WHERE source_job_id=:j'), {"j": child})
            if count != 0:
                raise AssertionError("reuse_created_provider_checkpoint")
        phase["value"] = "source_drift"
        drift = hashlib.sha256((child + "source-drift").encode()).hexdigest()
        async with owner.begin() as conn:
            await conn.execute(text(f'UPDATE "{schema}".documents SET content_sha256=:h WHERE id=:d'), {"h": drift, "d": document})
        try:
            try:
                await reuse_once()
            except ExtractionOutcomeUnknownError:
                pass
            else:
                raise AssertionError("reuse_source_drift_allowed")
        finally:
            async with owner.begin() as conn:
                await conn.execute(text(f'UPDATE "{schema}".documents SET content_sha256=:h WHERE id=:d'), {"h": source_sha, "d": document})
        if await parent_snapshot() != before:
            raise AssertionError("reuse_changed_parent_history")
        phase["value"] = "source_review"
        async with sessions() as session:
            await canonical.set_tenant(session, tenant)
            row = await session.scalar(select(AIJob).where(AIJob.id == child))
            preserved = _digest([row.params, row.result])
            if not await interrupt_claimed_generation_execution(session, child, str(tenant), child,
                                                                reason="source_reference_review_required"):
                raise AssertionError("source_review_interruption_unverified")
        async with sessions() as session:
            await canonical.set_tenant(session, tenant)
            row = await session.scalar(select(AIJob).where(AIJob.id == child))
            if (row.status != "interrupted" or row.errors != ["source_reference_review_required"]
                    or is_resumable_generation_job(row) or _digest([row.params, row.result]) != preserved):
                raise AssertionError("source_review_did_not_preserve_work")
        if await parent_snapshot() != before:
            raise AssertionError("source_review_changed_parent")
        # A separate fixture job exercises private rejection custody without
        # reactivating the source-review-held child or making a provider call.
        phase["value"] = "managed_rejection"
        import base64
        from app.modules.ai.managed_response_rejection import ManagedResponseRejectedError
        from app.modules.ai.v3.managed_rejection_quarantine import KEY as QUARANTINE_KEY
        from app.modules.ai.v3.managed_rejection_quarantine import POLICY as QUARANTINE_POLICY
        from app.modules.ai.v3.stage_checkpoint import _digest
        from app.modules.ai.v3.pending_stage_transactions import has_pending
        rejected_job = str(uuid4())
        rejected_client = client(rejected_job)
        async with owner.begin() as conn:
            await conn.execute(text(f'''INSERT INTO "{schema}".ai_jobs
                (id,tenant_id,user_id,status,params,result)
                VALUES(:j,:t,:a,'running',CAST(:p AS json),CAST(:r AS json))'''),
                {"j": rejected_job, "t": tenant, "a": actor, "p": json.dumps(params),
                 "r": json.dumps({ROUTE_KEY: {"policy": ROUTE_POLICY, "fingerprint": rejected_client.cache_fingerprint()}})})
        raw = b'{"model":"gpt-5.6-luna","choices":[{"message":{"content":"synthetic invalid json"}}]}'
        attempts = 0
        async def rejected(_capability: Any, **options: Any) -> Any:
            nonlocal attempts
            attempts += 1
            if await options["ownership_checkpoint"]() is not True:
                raise AssertionError("quarantine_fixture_unowned")
            raise ManagedResponseRejectedError(raw=raw, tenant_id=tenant, user_id=actor, job_id=rejected_job,
                stage=options["stage_id"], route_fingerprint=rejected_client.cache_fingerprint(),
                wire_request_sha256=hashlib.sha256(b"synthetic request").hexdigest(), phase="content_json",
                cause=ValueError("source_first_qa_response_invalid"))
        rejected_client.prepare, rejected_client.invoke = prepare, rejected
        rejected_token = delivery_id.set(rejected_job)
        try:
            for _ in range(2):
                try:
                    await stage_once(journal(rejected_job), stage="lesson", group_id="synthetic rejected lesson",
                        source_sha256=source_sha, route_fingerprint=rejected_client.cache_fingerprint(),
                        messages=messages, response_format={"type": "json_object"}, invoke=forbidden,
                        direct_client=rejected_client)
                except ExtractionOutcomeUnknownError:
                    pass
                else:
                    raise AssertionError("quarantine_fixture_accepted")
            async with sessions() as session:
                await canonical.set_tenant(session, tenant)
                row = await session.scalar(select(AIJob).where(AIJob.id == rejected_job))
                entries = row.result[QUARANTINE_KEY]["entries"]
                if attempts != 1 or len(entries) != 1 or not has_pending(row.result) or row.status != "running" or row.params != params:
                    raise AssertionError("quarantine_fixture_custody_changed")
                digest, reference = next(iter(entries.items()))
                if "raw_base64" in reference or "synthetic invalid json" in json.dumps(row.result):
                    raise AssertionError("quarantine_fixture_raw_in_job")
                custody = journal(rejected_job)
                stored_plan = await custody.repository.load_plan(session, tenant_id=str(tenant),
                    generation_key=custody._owned_key(reference["checkpoint_key"]))
                if (stored_plan.source_job_id != rejected_job or stored_plan.plan_payload.get("policy") != QUARANTINE_POLICY
                        or stored_plan.plan_payload.get("accepted") is not False
                        or _digest(stored_plan.plan_payload.get("stage_plan")) != digest):
                    raise AssertionError("quarantine_fixture_plan_invalid")
                receipt = await custody.read_owned_value_in_session(session, reference["checkpoint_key"],
                    dict(stored_plan.plan_payload))
                if not isinstance(receipt, dict):
                    raise AssertionError("quarantine_fixture_receipt_missing")
                if (base64.b64decode(receipt["raw_base64"], validate=True) != raw
                        or receipt["body_sha256"] != hashlib.sha256(raw).hexdigest() or receipt["accepted"] is not False):
                    raise AssertionError("quarantine_fixture_bytes_invalid")
            async with sessions() as session:
                await canonical.set_tenant(session, uuid4())
                if await session.scalar(select(AIJob).where(AIJob.id == rejected_job)) is not None:
                    raise AssertionError("quarantine_fixture_cross_tenant_visible")
        finally:
            delivery_id.reset(rejected_token)
            rejected_client.close()
        if await parent_snapshot() != before:
            raise AssertionError("quarantine_changed_parent")
    finally:
        delivery_id.reset(token)
        parent_client.close()
        child_client.close()


async def exercise(owner: Any, runtime: Any, schema: str, *, execution_enabled: bool = False) -> None:
    """Only finite diagnostic codes cross the disposable exercise boundary."""
    phase = {"value": "preflight"}
    try:
        await _exercise(owner, runtime, schema, execution_enabled=execution_enabled, phase=phase)
    except Exception as exc:
        import re
        original = getattr(exc, "orig", None)
        nested = getattr(original, "__cause__", None)
        sqlstate = getattr(original, "sqlstate", None) or getattr(nested, "sqlstate", None)
        safe_state = sqlstate if isinstance(sqlstate, str) and re.fullmatch(r"[0-9A-Z]{5}", sqlstate) else "unknown"
        label = phase["value"] if phase["value"] in {"preflight", "fixture", "parent_extraction", "parent_abandon", "snapshot", "concurrent_cold", "source_drift", "source_review", "managed_rejection"} else "unknown"
        category = type(exc).__name__ if type(exc).__name__ in {"DBAPIError", "IntegrityError", "AssertionError", "RuntimeError", "ValueError", "ExtractionOutcomeUnknownError", "TimeoutError"} else "other"
        print("EVIDENCE|phase=reuse_" + label + "|error_class=" + category + "|sqlstate=" + safe_state, flush=True)
        raise
