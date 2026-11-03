"""Fresh QA final-save fence; fake transactions, no DB or provider."""
import socket
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest

from app.modules.ai import pipeline
from app.modules.ai.delivery_ownership import DeliveryOwnershipLostError, delivery_id
from app.modules.ai.qa_luna_dev_route import QA_TENANT
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.owned_source_context import OwnedSourceContext
from app.modules.ai.v3.qa_luna_pending_policy import DIRECT_POLICY, DIRECT_POLICY_V2, KEY
from tests.unit.test_v3_primary_source_manifest import sample


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(httpx, "AsyncClient", deny)
    monkeypatch.setattr(httpx, "Client", deny)


def owned():
    corpus, _ = sample()
    doc_id = str(uuid4())
    corpus = replace(corpus, tenant_id=str(QA_TENANT), documents=(replace(corpus.documents[0], doc_id=doc_id),))
    user = uuid4()
    journal = SimpleNamespace(tenant_id=str(QA_TENANT), user_id=user, job_id="job")
    context = OwnedSourceContext(corpus, journal, QA_TENANT, user, "job", (doc_id,))
    state = pipeline.GenerationState(job_id="job", source_document_ids=[doc_id],
        source_analysis={KEY: DIRECT_POLICY}, owned_v3_source_context=context, owned_v3_route_fingerprint="a" * 64)
    job = SimpleNamespace(id="job", tenant_id=QA_TENANT, user_id=user, status="running",
        result={"v3_owned_route_binding": {"policy": "v3-owned-route-binding-v1", "fingerprint": "a" * 64}},
        params={"documents": [doc_id], "source_analysis": {KEY: DIRECT_POLICY,
                "generation_engine": "evidence_v3", "analysis_mode": "direct_source"}})
    return state, job, user


@pytest.mark.asyncio
async def test_fresh_owned_success_checks_same_session_and_plan(monkeypatch):
    state, job, user = owned()
    verify = AsyncMock(return_value=True)
    monkeypatch.setattr(state.owned_v3_source_context, "verify_locked", verify)
    session = object()
    token = delivery_id.set("delivery")
    try:
        await pipeline._verify_fresh_v3_final_source(session, job, state, QA_TENANT, user)
    finally:
        delivery_id.reset(token)
    args = verify.await_args.args
    assert args[0] is session and args[1] is job
    assert args[2]["schema"] == "v3-stage-checkpoint-v1" and len(args[2]["source_sha256"]) == 64


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["pending_null", "pending_malformed", "malformed_result", "policy", "engine", "selection", "tenant", "owner", "missing_context", "source_drift", "source_deleted", "verifier_error", "route_drift", "route_missing"])
async def test_invalid_final_source_holds_before_course_insert(monkeypatch, problem):
    state, job, user = owned()
    verify = AsyncMock(return_value=problem not in {"source_drift", "source_deleted"})
    if problem == "verifier_error":
        verify.side_effect = RuntimeError("private source")
    monkeypatch.setattr(state.owned_v3_source_context, "verify_locked", verify)
    if problem == "pending_null":
        job.result = {"v3_pending_stages": None}
    if problem == "pending_malformed":
        job.result = {"v3_pending_stages": {}}
    if problem == "malformed_result":
        job.result = []
    if problem == "policy":
        job.params["source_analysis"][KEY] = DIRECT_POLICY_V2
    if problem == "engine":
        job.params["source_analysis"]["generation_engine"] = "evidence_v2"
    if problem == "selection":
        state.source_document_ids = ["other"]
    if problem == "tenant":
        state.owned_v3_source_context.tenant_id = uuid4()
    if problem == "owner":
        state.owned_v3_source_context.user_id = uuid4()
    if problem == "missing_context":
        state.owned_v3_source_context = None
    if problem == "route_drift":
        job.result["v3_owned_route_binding"]["fingerprint"] = "b" * 64
    if problem == "route_missing":
        del job.result["v3_owned_route_binding"]
    session = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock(return_value=job), add=Mock(), commit=AsyncMock())
    class Manager:
        async def __aenter__(self): return session
        async def __aexit__(self, *_args): return None
    monkeypatch.setattr(pipeline, "async_session_factory", Manager)
    monkeypatch.setattr(pipeline, "lock_owned_delivery", AsyncMock())
    token = delivery_id.set("delivery")
    try:
        with pytest.raises(ExtractionOutcomeUnknownError, match="v3_final_source_unverified"):
            await pipeline._save_generation_to_db(state, QA_TENANT, user)
    finally:
        delivery_id.reset(token)
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_delivery_fails_and_legacy_not_changed():
    state, job, user = owned()
    token = delivery_id.set(None)
    try:
        with pytest.raises(DeliveryOwnershipLostError):
            await pipeline._verify_fresh_v3_final_source(object(), job, state, QA_TENANT, user)
        state.source_analysis = {}
        job.params["source_analysis"] = {}
        state.owned_v3_source_context = None
        await pipeline._verify_fresh_v3_final_source(object(), job, state, QA_TENANT, user)
    finally:
        delivery_id.reset(token)


@pytest.mark.asyncio
async def test_displaced_delivery_fails_before_job_or_course_write(monkeypatch):
    state, job, user = owned()
    session = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock(return_value=job), add=Mock(), commit=AsyncMock())
    class Manager:
        async def __aenter__(self): return session
        async def __aexit__(self, *_args): return None
    monkeypatch.setattr(pipeline, "async_session_factory", Manager)
    monkeypatch.setattr(pipeline, "lock_owned_delivery", AsyncMock(side_effect=DeliveryOwnershipLostError("displaced")))
    with pytest.raises(DeliveryOwnershipLostError):
        await pipeline._save_generation_to_db(state, QA_TENANT, user)
    session.scalar.assert_not_awaited()
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_source_failure_outer_handler_holds_without_refund(monkeypatch):
    user, document = uuid4(), uuid4()
    monkeypatch.setattr(pipeline, "_check_generation_source_job", AsyncMock())
    monkeypatch.setattr(pipeline, "_update_job_db", AsyncMock(return_value=False))
    monkeypatch.setattr(pipeline, "load_direct_source_corpus", AsyncMock(return_value=object()))
    monkeypatch.setattr(pipeline, "_run_v3_generation", AsyncMock())
    monkeypatch.setattr(pipeline, "_check_cancelled_async", AsyncMock())
    monkeypatch.setattr(pipeline, "_save_generation_to_db", AsyncMock(side_effect=ExtractionOutcomeUnknownError("v3_final_source_unverified")))
    hold = AsyncMock(return_value=True)
    refund = AsyncMock()
    monkeypatch.setattr(pipeline, "_persist_pending_stage_hold", hold)
    monkeypatch.setattr(pipeline, "_release_generation_reservation", refund)
    state = await pipeline.run_generation_pipeline("job", [str(document)], tenant_id=QA_TENANT, user_id=user,
        source_analysis={"generation_engine": "evidence_v3", "analysis_mode": "direct_source", KEY: DIRECT_POLICY})
    assert state.status == "interrupted" and state.errors == ["generation_stage_outcome_unknown"]
    hold.assert_awaited_once()
    refund.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_source_and_course_commit_share_owned_session(monkeypatch):
    state, job, user = owned()
    verify = AsyncMock(return_value=True)
    monkeypatch.setattr(state.owned_v3_source_context, "verify_locked", verify)
    session = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock(return_value=job), add=Mock(),
                              flush=AsyncMock(), commit=AsyncMock())
    class Manager:
        async def __aenter__(self): return session
        async def __aexit__(self, *_args): return None
    monkeypatch.setattr(pipeline, "async_session_factory", Manager)
    lock = AsyncMock()
    monkeypatch.setattr(pipeline, "lock_owned_delivery", lock)
    token = delivery_id.set("delivery")
    try:
        await pipeline._save_generation_to_db(state, QA_TENANT, user)
    finally:
        delivery_id.reset(token)
    lock.assert_awaited_once_with(session, "job", str(QA_TENANT), require_running=True)
    assert verify.await_args.args[:2] == (session, job)
    assert session.add.call_count == 1
    session.commit.assert_awaited_once()
    assert state.status == "completed" and job.status == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["none", "hash", "deleted", "foreign"])
async def test_final_save_uses_real_source_verifier_with_locked_document_row(monkeypatch, change):
    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument

    state, job, user = owned()
    doc_id = state.source_document_ids[0]
    doc = DirectSourceDocument(doc_id=doc_id, title="synthetic", filename="fixture", category="general",
        source_revision="document:" + "a" * 64, chunks=(), source_text="synthetic source")
    corpus = DirectSourceCorpus(tenant_id=str(QA_TENANT), documents=(doc,), total_chars=16, total_chunks=0)
    state.owned_v3_source_context.corpus = corpus
    row = SimpleNamespace(id=__import__("uuid").UUID(doc_id), tenant_id=QA_TENANT,
                          lifecycle_status="active", content_sha256="a" * 64)
    if change == "hash":
        row.content_sha256 = "b" * 64
    if change == "deleted":
        row.lifecycle_status = "deleted"
    if change == "foreign":
        row.tenant_id = uuid4()
    session = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock(side_effect=[job, row]), add=Mock(),
                              flush=AsyncMock(), commit=AsyncMock())
    class Manager:
        async def __aenter__(self): return session
        async def __aexit__(self, *_args): return None
    monkeypatch.setattr(pipeline, "async_session_factory", Manager)
    monkeypatch.setattr(pipeline, "lock_owned_delivery", AsyncMock())
    token = delivery_id.set("delivery")
    try:
        if change == "none":
            await pipeline._save_generation_to_db(state, QA_TENANT, user)
            session.commit.assert_awaited_once()
        else:
            with pytest.raises(ExtractionOutcomeUnknownError, match="v3_final_source_unverified"):
                await pipeline._save_generation_to_db(state, QA_TENANT, user)
            session.add.assert_not_called()
            session.commit.assert_not_awaited()
    finally:
        delivery_id.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["source_first_commit_intent", "source_first_partitioned_commit_intent"])
@pytest.mark.parametrize("value", [None, {}])
async def test_foreign_source_first_intent_holds_before_insert(monkeypatch, key, value):
    state, job, user = owned()
    job.result = {key: value}
    session = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock(return_value=job), add=Mock(), commit=AsyncMock())
    class Manager:
        async def __aenter__(self): return session
        async def __aexit__(self, *_args): return None
    monkeypatch.setattr(pipeline, "async_session_factory", Manager)
    monkeypatch.setattr(pipeline, "lock_owned_delivery", AsyncMock())
    token = delivery_id.set("delivery")
    try:
        with pytest.raises(ExtractionOutcomeUnknownError, match="v3_final_source_unverified"):
            await pipeline._save_generation_to_db(state, QA_TENANT, user)
    finally:
        delivery_id.reset(token)
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_source_verifier_cancellation_is_held(monkeypatch):
    import asyncio

    state, job, user = owned()
    monkeypatch.setattr(state.owned_v3_source_context, "verify_locked", AsyncMock(side_effect=asyncio.CancelledError()))
    token = delivery_id.set("delivery")
    try:
        with pytest.raises(ExtractionOutcomeUnknownError, match="v3_final_source_unverified"):
            await pipeline._verify_fresh_v3_final_source(object(), job, state, QA_TENANT, user)
    finally:
        delivery_id.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("new_marker", [None, DIRECT_POLICY_V2])
async def test_owned_context_prevents_both_marker_downgrade(new_marker):
    state, job, user = owned()
    if new_marker is None:
        state.source_analysis.pop(KEY)
        job.params["source_analysis"].pop(KEY)
    else:
        state.source_analysis[KEY] = new_marker
        job.params["source_analysis"][KEY] = new_marker
    token = delivery_id.set("delivery")
    try:
        with pytest.raises(ExtractionOutcomeUnknownError, match="v3_final_source_unverified"):
            await pipeline._verify_fresh_v3_final_source(object(), job, state, QA_TENANT, user)
    finally:
        delivery_id.reset(token)
