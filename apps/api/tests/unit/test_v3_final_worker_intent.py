"""Guarded worker checkpoint tests; not database durability evidence."""
import asyncio
import socket
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest

from app.modules.ai import pipeline
from app.modules.ai.delivery_ownership import delivery_id
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.final_save_contract import INTENT_KEY
from app.modules.ai.v3.pending_stage_transactions import has_pending
from app.modules.ai.v3.qa_luna_pending_policy import DIRECT_POLICY, KEY
from tests.unit.test_v3_final_save_owned_checkpoint import setup


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(httpx, "Client", deny)
    monkeypatch.setattr(httpx, "AsyncClient", deny)


@pytest.mark.asyncio
async def test_worker_prepares_checkpoint_before_returning_save_intent(monkeypatch):
    data, journal, context = setup(monkeypatch)
    state = data["state"]
    state.owned_v3_source_context = context
    state.owned_v3_route_fingerprint = data["intent"]["route_fingerprint"]
    token = delivery_id.set(data["intent"]["delivery_id"])
    try:
        intent = await pipeline._prepare_fresh_v3_final_intent(state, context.tenant_id, context.user_id)
    finally:
        delivery_id.reset(token)
    assert has_pending(journal.job.result)
    assert journal.job.result[INTENT_KEY] == intent
    assert len(journal.values) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["lost_ack", "cancel"])
async def test_uncertain_checkpoint_never_returns_intent(monkeypatch, failure):
    data, journal, context = setup(monkeypatch)
    state = data["state"]
    state.owned_v3_source_context = context
    state.owned_v3_route_fingerprint = data["intent"]["route_fingerprint"]
    if failure == "lost_ack":
        journal.fail_ack = True
    else:
        async def cancelled(*_args, **_kwargs):
            raise asyncio.CancelledError()
        monkeypatch.setattr(context, "verify_locked", cancelled)
    token = delivery_id.set(data["intent"]["delivery_id"])
    try:
        with pytest.raises(ExtractionOutcomeUnknownError):
            await pipeline._prepare_fresh_v3_final_intent(state, context.tenant_id, context.user_id)
    finally:
        delivery_id.reset(token)
    if failure == "lost_ack":
        assert has_pending(journal.job.result)


@pytest.mark.asyncio
async def test_worker_rejects_foreign_actor_before_checkpoint(monkeypatch):
    data, journal, context = setup(monkeypatch)
    state = data["state"]
    state.owned_v3_source_context = context
    state.owned_v3_route_fingerprint = data["intent"]["route_fingerprint"]
    token = delivery_id.set(data["intent"]["delivery_id"])
    try:
        with pytest.raises(ExtractionOutcomeUnknownError):
            await pipeline._prepare_fresh_v3_final_intent(state, context.tenant_id, UUID(int=123))
    finally:
        delivery_id.reset(token)
    assert not journal.values


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement_delivery", [False, True])
async def test_repeated_prepare_never_replaces_durable_intent(monkeypatch, replacement_delivery):
    data, journal, context = setup(monkeypatch)
    save, refund = AsyncMock(), AsyncMock()
    monkeypatch.setattr(pipeline, "_save_generation_to_db", save)
    monkeypatch.setattr(pipeline, "_release_generation_reservation", refund)
    state = data["state"]
    state.owned_v3_source_context = context
    state.owned_v3_route_fingerprint = data["intent"]["route_fingerprint"]
    token = delivery_id.set(data["intent"]["delivery_id"])
    try:
        first = await pipeline._prepare_fresh_v3_final_intent(state, context.tenant_id, context.user_id)
        if replacement_delivery:
            delivery_id.set("replacement-delivery")
        with pytest.raises(ExtractionOutcomeUnknownError):
            await pipeline._prepare_fresh_v3_final_intent(state, context.tenant_id, context.user_id)
    finally:
        delivery_id.reset(token)
    assert journal.job.result[INTENT_KEY] == first and has_pending(journal.job.result)
    assert len(journal.values) == 1
    save.assert_not_awaited()
    refund.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("checkpoint_fails", [False, True])
async def test_worker_orders_checkpoint_before_save_and_holds_unknown(monkeypatch, checkpoint_fails):
    from uuid import uuid4

    from app.modules.ai.qa_luna_dev_route import QA_TENANT

    calls = []
    marker = {"synthetic": "intent"}
    async def prepare(*_args):
        calls.append("checkpoint")
        if checkpoint_fails:
            raise ExtractionOutcomeUnknownError("synthetic_unknown")
        return marker
    async def save(*_args, **kwargs):
        calls.append("save")
        assert kwargs["final_intent"] is marker
    monkeypatch.setattr(pipeline, "_check_generation_source_job", AsyncMock())
    monkeypatch.setattr(pipeline, "_update_job_db", AsyncMock(return_value=False))
    monkeypatch.setattr(pipeline, "load_direct_source_corpus", AsyncMock(return_value=object()))
    monkeypatch.setattr(pipeline, "_run_v3_generation", AsyncMock())
    monkeypatch.setattr(pipeline, "_check_cancelled_async", AsyncMock())
    monkeypatch.setattr(pipeline, "_prepare_fresh_v3_final_intent", prepare)
    monkeypatch.setattr(pipeline, "_save_generation_to_db", save)
    hold, refund = AsyncMock(return_value=True), AsyncMock()
    monkeypatch.setattr(pipeline, "_persist_pending_stage_hold", hold)
    monkeypatch.setattr(pipeline, "_release_generation_reservation", refund)
    await pipeline.run_generation_pipeline("job", [str(uuid4())], tenant_id=QA_TENANT, user_id=uuid4(),
        source_analysis={"generation_engine": "evidence_v3", "analysis_mode": "direct_source", KEY: DIRECT_POLICY})
    assert calls == (["checkpoint"] if checkpoint_fails else ["checkpoint", "save"])
    if checkpoint_fails:
        hold.assert_awaited_once()
    refund.assert_not_awaited()


@pytest.mark.asyncio
async def test_v2_worker_never_enters_fresh_v3_checkpoint(monkeypatch):
    from uuid import uuid4

    from app.modules.ai.qa_luna_dev_route import QA_TENANT

    monkeypatch.setattr(pipeline, "_check_generation_source_job", AsyncMock())
    monkeypatch.setattr(pipeline, "_update_job_db", AsyncMock(return_value=False))
    monkeypatch.setattr(pipeline, "load_direct_source_corpus", AsyncMock(return_value=object()))
    monkeypatch.setattr(pipeline, "_run_evidence_v2_generation", AsyncMock())
    monkeypatch.setattr(pipeline, "_check_cancelled_async", AsyncMock())
    prepare, save = AsyncMock(), AsyncMock()
    monkeypatch.setattr(pipeline, "_prepare_fresh_v3_final_intent", prepare)
    monkeypatch.setattr(pipeline, "_save_generation_to_db", save)
    await pipeline.run_generation_pipeline("job", [str(uuid4())], tenant_id=QA_TENANT, user_id=uuid4(),
        source_analysis={"generation_engine": "evidence_v2", "analysis_mode": "direct_source"})
    prepare.assert_not_awaited()
    save.assert_awaited_once()
    assert "final_intent" not in save.await_args.kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize("verified", [True, False])
async def test_worker_recovers_only_verified_completed_receipt(monkeypatch, verified):
    from uuid import uuid4

    from app.modules.ai.v3 import final_save_recovery

    data, _journal, context = setup(monkeypatch)
    intent = data["intent"]
    course_id = uuid4()
    async def generate(state, *_args, **_kwargs):
        state.owned_v3_source_context = context
        state.owned_v3_route_fingerprint = intent["route_fingerprint"]
    monkeypatch.setattr(pipeline, "_check_generation_source_job", AsyncMock())
    monkeypatch.setattr(pipeline, "_update_job_db", AsyncMock(return_value=False))
    monkeypatch.setattr(pipeline, "load_direct_source_corpus", AsyncMock(return_value=object()))
    monkeypatch.setattr(pipeline, "_run_v3_generation", generate)
    monkeypatch.setattr(pipeline, "_check_cancelled_async", AsyncMock())
    monkeypatch.setattr(pipeline, "_prepare_fresh_v3_final_intent", AsyncMock(return_value=intent))
    monkeypatch.setattr(pipeline, "_save_generation_to_db", AsyncMock(
        side_effect=ExtractionOutcomeUnknownError("v3_final_save_outcome_unknown")))
    recovery = AsyncMock(return_value=course_id if verified else None)
    monkeypatch.setattr(final_save_recovery, "recover_completed_course_id", recovery)
    hold, refund = AsyncMock(return_value=True), AsyncMock()
    monkeypatch.setattr(pipeline, "_persist_pending_stage_hold", hold)
    monkeypatch.setattr(pipeline, "_release_generation_reservation", refund)
    state = await pipeline.run_generation_pipeline(intent["job_id"], [intent["documents"][0]["doc_id"]],
        tenant_id=context.tenant_id, user_id=context.user_id,
        source_analysis={"generation_engine": "evidence_v3", "analysis_mode": "direct_source", KEY: DIRECT_POLICY})
    recovery.assert_awaited_once()
    assert state.status == ("completed" if verified else "interrupted")
    assert state.course_id == (str(course_id) if verified else None)
    if verified:
        hold.assert_not_awaited()
    else:
        hold.assert_awaited_once()
    refund.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "session_exit", "cancel", "foreign_owner", "cold_context"])
@pytest.mark.parametrize("durable_state", ["pending", "completed_receipt"])
async def test_recovery_failures_never_refund_or_retry(monkeypatch, failure, durable_state):
    from copy import deepcopy
    from uuid import uuid4

    from app.modules.ai.v3 import final_save_recovery

    data, journal, context = setup(monkeypatch)
    intent = data["intent"]
    if durable_state == "pending":
        journal.job.result["v3_pending_stages"] = {"synthetic": "held"}
    else:
        journal.job.result["v3_final_save_receipt"] = {"synthetic": "completed"}
    before = deepcopy(journal.job.result)
    async def generate(state, *_args, **_kwargs):
        state.owned_v3_source_context = None if failure == "cold_context" else context
        state.owned_v3_route_fingerprint = intent["route_fingerprint"]
        if failure == "foreign_owner":
            context.user_id = uuid4()
    monkeypatch.setattr(pipeline, "_check_generation_source_job", AsyncMock())
    monkeypatch.setattr(pipeline, "_update_job_db", AsyncMock(return_value=False))
    monkeypatch.setattr(pipeline, "load_direct_source_corpus", AsyncMock(return_value=object()))
    monkeypatch.setattr(pipeline, "_run_v3_generation", generate)
    monkeypatch.setattr(pipeline, "_check_cancelled_async", AsyncMock())
    monkeypatch.setattr(pipeline, "_prepare_fresh_v3_final_intent", AsyncMock(return_value=intent))
    save = AsyncMock(side_effect=ExtractionOutcomeUnknownError("v3_final_save_outcome_unknown"))
    monkeypatch.setattr(pipeline, "_save_generation_to_db", save)
    failures = {"timeout": TimeoutError(), "session_exit": RuntimeError(), "cancel": asyncio.CancelledError()}
    recovery = AsyncMock(side_effect=failures.get(failure, RuntimeError()))
    monkeypatch.setattr(final_save_recovery, "recover_completed_course_id", recovery)
    hold, refund = AsyncMock(return_value=True), AsyncMock()
    monkeypatch.setattr(pipeline, "_persist_pending_stage_hold", hold)
    monkeypatch.setattr(pipeline, "_release_generation_reservation", refund)
    kwargs = dict(tenant_id=UUID(intent["tenant_id"]), user_id=UUID(intent["user_id"]),
        source_analysis={"generation_engine": "evidence_v3", "analysis_mode": "direct_source", KEY: DIRECT_POLICY})
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await pipeline.run_generation_pipeline(intent["job_id"], [intent["documents"][0]["doc_id"]], **kwargs)
    else:
        state = await pipeline.run_generation_pipeline(intent["job_id"], [intent["documents"][0]["doc_id"]], **kwargs)
        assert state.status == "interrupted"
        hold.assert_awaited_once()
    if failure in {"foreign_owner", "cold_context"}:
        recovery.assert_not_awaited()
    else:
        recovery.assert_awaited_once()
    save.assert_awaited_once()
    refund.assert_not_awaited()
    assert journal.job.result == before
