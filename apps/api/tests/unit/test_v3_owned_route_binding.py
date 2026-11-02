"""Offline route binding tests with an owned fake transaction."""
import socket
from uuid import UUID

import httpx
import pytest

from app.modules.ai.direct_luna_responses_client import DirectLunaResponsesClient
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.owned_route_binding import KEY, bind_owned_route
from app.modules.ai.v3.pending_stage_transactions import KEY as PENDING_KEY
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


def client(intent, key="synthetic"):
    return DirectLunaResponsesClient(api_key=key, tenant_id=UUID(intent["tenant_id"]),
        user_id=UUID(intent["user_id"]), job_id=intent["job_id"], credential_revision="r1")


@pytest.mark.asyncio
async def test_fresh_binding_and_cold_replay_rotation_hold(monkeypatch):
    data, journal, _ = setup(monkeypatch)
    journal.job.result.pop("v3_owned_route_binding")
    original_scalar = journal.sessions
    def sessions():
        session = original_scalar()
        calls = 0
        async def scalar(_statement):
            nonlocal calls
            calls += 1
            return journal.job if calls == 1 else None
        session.scalar = scalar
        return session
    journal.sessions = sessions
    c = client(data["intent"])
    kwargs = dict(journal=journal, user_id=UUID(data["intent"]["user_id"]), client=c)
    value = await bind_owned_route(**kwargs)
    assert journal.job.result[KEY]["fingerprint"] == value
    assert await bind_owned_route(**kwargs) == value
    with pytest.raises(ExtractionOutcomeUnknownError):
        await bind_owned_route(**(kwargs | {"client": client(data["intent"], "rotated")}))


@pytest.mark.asyncio
async def test_unbound_pending_is_held(monkeypatch):
    data, journal, _ = setup(monkeypatch)
    journal.job.result.pop(KEY)
    journal.job.result[PENDING_KEY] = None
    with pytest.raises(ExtractionOutcomeUnknownError):
        await bind_owned_route(journal=journal, user_id=UUID(data["intent"]["user_id"]), client=client(data["intent"]))
    assert KEY not in journal.job.result


@pytest.mark.asyncio
async def test_unbound_prior_stage_history_is_held(monkeypatch):
    data, journal, _ = setup(monkeypatch)
    journal.job.result.pop(KEY)
    original_sessions = journal.sessions
    def sessions():
        session = original_sessions()
        calls = 0
        async def scalar(_statement):
            nonlocal calls
            calls += 1
            return journal.job if calls == 1 else 1
        session.scalar = scalar
        return session
    journal.sessions = sessions
    with pytest.raises(ExtractionOutcomeUnknownError):
        await bind_owned_route(journal=journal, user_id=UUID(data["intent"]["user_id"]), client=client(data["intent"]))
    assert KEY not in journal.job.result
