"""Guarded fail-first test for the unwired checkpoint/save boundary."""
import asyncio
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import httpx
import pytest

from app.modules.ai import pipeline
from app.modules.ai.delivery_ownership import delivery_id
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.final_save_contract import FENCE_POLICY, INTENT_KEY, PENDING_KEY, RECEIPT_KEY, _digest
from app.modules.ai.v3.final_save_owned_checkpoint import checkpoint_final_output
from app.modules.ai.v3.pending_stage_transactions import has_pending
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
async def test_actual_writer_holds_existing_owned_final_intent_before_any_save(monkeypatch):
    data, journal, context = setup(monkeypatch)
    state, intent = data["state"], data["intent"]
    state.owned_v3_source_context = context
    state.owned_v3_route_fingerprint = intent["route_fingerprint"]
    await checkpoint_final_output(journal=journal, context=context, state=state, intent=intent)
    assert has_pending(journal.job.result)
    session = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock(return_value=journal.job),
                              add=Mock(), flush=AsyncMock(), commit=AsyncMock())
    class Manager:
        async def __aenter__(self):
            return session
        async def __aexit__(self, *_args):
            return None
    monkeypatch.setattr(pipeline, "async_session_factory", Manager)
    monkeypatch.setattr(pipeline, "lock_owned_delivery", AsyncMock())
    token = delivery_id.set(intent["delivery_id"])
    try:
        with pytest.raises(ExtractionOutcomeUnknownError, match="v3_final_source_unverified"):
            await pipeline._save_generation_to_db(state, UUID(intent["tenant_id"]), UUID(intent["user_id"]))
    finally:
        delivery_id.reset(token)
    session.add.assert_not_called()
    session.commit.assert_not_awaited()
    assert has_pending(journal.job.result)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["ok", "lost_ack", "cancel"])
async def test_actual_save_emits_receipt_or_unknown_after_owned_checkpoint(monkeypatch, mode):
    data, journal, context = setup(monkeypatch)
    state, intent = data["state"], data["intent"]
    state.owned_v3_source_context = context
    state.owned_v3_route_fingerprint = intent["route_fingerprint"]
    await checkpoint_final_output(journal=journal, context=context, state=state, intent=intent)
    saved = []
    async def commit():
        if mode == "lost_ack":
            raise TimeoutError("ack lost")
        if mode == "cancel":
            raise asyncio.CancelledError()
    session = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock(return_value=journal.job),
                              add=Mock(side_effect=saved.append), flush=AsyncMock(), commit=commit)
    class Manager:
        async def __aenter__(self):
            return session
        async def __aexit__(self, *_args):
            return None
    monkeypatch.setattr(pipeline, "async_session_factory", Manager)
    monkeypatch.setattr(pipeline, "lock_owned_delivery", AsyncMock())
    token = delivery_id.set(intent["delivery_id"])
    try:
        if mode == "ok":
            await pipeline._save_generation_to_db(state, UUID(intent["tenant_id"]), UUID(intent["user_id"]),
                                                  final_intent=intent)
        else:
            with pytest.raises(ExtractionOutcomeUnknownError, match="v3_final_save_outcome_unknown"):
                await pipeline._save_generation_to_db(state, UUID(intent["tenant_id"]), UUID(intent["user_id"]),
                                                      final_intent=intent)
    finally:
        delivery_id.reset(token)
    assert saved and journal.job.result[RECEIPT_KEY]["policy"] == "v3-final-save-receipt-v2"


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["tenant_id", "user_id", "job_id", "delivery_id", "route_fingerprint"])
async def test_final_intent_identity_mismatch_never_writes(monkeypatch, field):
    data, journal, context = setup(monkeypatch)
    state, intent = data["state"], data["intent"]
    state.owned_v3_source_context = context
    state.owned_v3_route_fingerprint = intent["route_fingerprint"]
    await checkpoint_final_output(journal=journal, context=context, state=state, intent=intent)
    changed = dict(intent)
    changed[field] = "b" * 64 if field == "route_fingerprint" else (
        "other-delivery" if field == "delivery_id" else str(UUID(int=123)))
    changed["intent_digest"] = _digest({key: value for key, value in changed.items() if key != "intent_digest"})
    journal.job.result[INTENT_KEY] = changed
    journal.job.result[PENDING_KEY] = {"policy": FENCE_POLICY, "intent_digest": changed["intent_digest"],
                                       "attempt_id": changed["attempt_id"]}
    session = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock(return_value=journal.job),
                              add=Mock(), flush=AsyncMock(), commit=AsyncMock())
    class Manager:
        async def __aenter__(self):
            return session
        async def __aexit__(self, *_args):
            return None
    monkeypatch.setattr(pipeline, "async_session_factory", Manager)
    monkeypatch.setattr(pipeline, "lock_owned_delivery", AsyncMock())
    token = delivery_id.set(intent["delivery_id"])
    try:
        with pytest.raises(ExtractionOutcomeUnknownError, match="v3_final_save_outcome_unknown"):
            await pipeline._save_generation_to_db(state, UUID(intent["tenant_id"]), UUID(intent["user_id"]),
                                                  final_intent=changed)
    finally:
        delivery_id.reset(token)
    session.add.assert_not_called()
    session.commit.assert_not_awaited()
