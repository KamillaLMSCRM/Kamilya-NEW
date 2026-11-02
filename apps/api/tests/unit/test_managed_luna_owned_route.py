"""Offline managed-route custody regressions; no provider or DB transport."""
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest

from app.modules.ai.managed_luna_client import ManagedLunaClient
from app.modules.ai.qa_luna_dev_route import QA_TENANT
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.qa_luna_pending_policy import (
    DIRECT_POLICY,
    KEY,
    MANAGED_POLICY,
    admission_marker,
    check_worker_marker,
)


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*_a, **_kw):
        raise AssertionError("offline transport denied")
    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(httpx, "AsyncClient", deny)
    monkeypatch.setattr(httpx, "Client", deny)


def settings(environment="render-development", **extra):
    values = dict(DEPLOYMENT_ENVIRONMENT=environment, AI_MANAGED_LUNA_QA_DEV_ENABLED=True,
        AI_DIRECT_LUNA_QA_DEV_ENABLED=False, AI_QA_LUNA_DEV_ENABLED=True,
        AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED=True)
    values.update(extra)
    return SimpleNamespace(**values)


def test_managed_admission_is_fresh_exact_tenant_and_mutually_exclusive():
    actor = uuid4()
    args = dict(tenant_id=QA_TENANT, user_id=actor, course_id=None, source_first=False)
    assert admission_marker(settings=settings(), **args) == MANAGED_POLICY
    assert admission_marker(settings=settings(), **(args | {"tenant_id": uuid4()})) is None
    for extra in ({"AI_DIRECT_LUNA_QA_DEV_ENABLED": True}, {"AI_MANAGED_LUNA_QA_DEV_ENABLED": "true"},
                  {"AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED": False}):
        with pytest.raises(ValueError):
            admission_marker(settings=settings(**extra), **args)
    with pytest.raises(ValueError):
        admission_marker(settings=settings(), **(args | {"course_id": uuid4()}))
    worker = settings("vm-development-worker")
    assert check_worker_marker(settings=worker, tenant_id=QA_TENANT, user_id=actor,
        stored=MANAGED_POLICY, dispatched=MANAGED_POLICY, course_id=None)
    for stored, dispatched in ((DIRECT_POLICY, MANAGED_POLICY), (MANAGED_POLICY, DIRECT_POLICY),
                                (DIRECT_POLICY, DIRECT_POLICY)):
        with pytest.raises(ValueError):
            check_worker_marker(settings=worker, tenant_id=QA_TENANT, user_id=actor,
                stored=stored, dispatched=dispatched, course_id=None)


def managed(tenant, actor, job):
    return ManagedLunaClient(base_url="http://127.0.0.1:18999/v1", api_key="synthetic" * 6,
        tenant_id=UUID(str(tenant)), user_id=actor, job_id=job, credential_revision="managed-r1")


@pytest.mark.asyncio
async def test_owned_managed_claim_finalize_cold_replay_and_unknown_hold(monkeypatch):
    from app.modules.ai.direct_luna_api import LunaUsage
    from app.modules.ai.direct_luna_responses_client import ResponsesResult
    from app.modules.ai.v3.direct_luna_owned_stage import run_direct_owned_stage
    from app.modules.ai.v3.pending_stage_transactions import has_pending
    from tests.unit.test_direct_luna_owned_stage import options, setup

    fake, journal, _, plan, validate = setup()
    client = managed(journal.tenant_id, journal.user_id, journal.job_id)
    async def prepare(*_a, ownership_checkpoint, **_kw):
        assert not fake.plans
        assert await ownership_checkpoint()
        return object()
    async def invoke(*_a, ownership_checkpoint, **_kw):
        assert has_pending(fake.job.result)
        assert await ownership_checkpoint()
        return ResponsesResult({"ok": True}, "gpt-5.6-luna", LunaUsage(12, 8, None, None))
    prepare_mock, invoke_mock = AsyncMock(side_effect=prepare), AsyncMock(side_effect=invoke)
    monkeypatch.setattr(client, "prepare", prepare_mock)
    monkeypatch.setattr(client, "invoke", invoke_mock)
    kwargs = options(journal, client, plan, validate)
    assert await run_direct_owned_stage(**kwargs) == {"ok": True}
    assert not has_pending(fake.job.result)
    cold = managed(journal.tenant_id, journal.user_id, journal.job_id)
    assert await run_direct_owned_stage(**(kwargs | {"client": cold})) == {"ok": True}
    prepare_mock.assert_awaited_once()
    invoke_mock.assert_awaited_once()
    assert fake.values["result"]["direct_metadata"]["model"] == "gpt-5.6-luna"

    fake, journal, _, plan, validate = setup()
    client = managed(journal.tenant_id, journal.user_id, journal.job_id)
    monkeypatch.setattr(client, "prepare", AsyncMock(return_value=object()))
    invocation = AsyncMock(side_effect=TimeoutError())
    monkeypatch.setattr(client, "invoke", invocation)
    kwargs = options(journal, client, plan, validate)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await run_direct_owned_stage(**kwargs)
    assert has_pending(fake.job.result)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await run_direct_owned_stage(**kwargs)
    invocation.assert_awaited_once()


@pytest.mark.asyncio
async def test_route_binding_rejects_direct_to_managed_policy_swap(monkeypatch):
    from app.modules.ai.direct_luna_responses_client import DirectLunaResponsesClient
    from app.modules.ai.v3.owned_route_binding import KEY as ROUTE_KEY
    from app.modules.ai.v3.owned_route_binding import bind_owned_route
    from tests.unit.test_v3_final_save_owned_checkpoint import setup

    data, journal, _ = setup(monkeypatch)
    intent = data["intent"]
    journal.job.result.pop(ROUTE_KEY)
    journal.job.params["source_analysis"][KEY] = MANAGED_POLICY
    original = journal.sessions
    def sessions():
        session = original()
        calls = 0
        async def scalar(_statement):
            nonlocal calls
            calls += 1
            return journal.job if calls == 1 else None
        session.scalar = scalar
        return session
    journal.sessions = sessions
    actor = UUID(intent["user_id"])
    direct = DirectLunaResponsesClient(api_key="synthetic", tenant_id=QA_TENANT,
        user_id=actor, job_id=journal.job_id)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await bind_owned_route(journal=journal, user_id=actor, client=direct)
    client = managed(QA_TENANT, actor, journal.job_id)
    fingerprint = await bind_owned_route(journal=journal, user_id=actor, client=client)
    assert journal.job.result[ROUTE_KEY]["fingerprint"] == fingerprint
    journal.job.params["source_analysis"][KEY] = DIRECT_POLICY
    with pytest.raises(ExtractionOutcomeUnknownError):
        await bind_owned_route(journal=journal, user_id=actor, client=client)


def test_managed_final_intent_preserves_policy_and_no_legacy_alias():
    from app.modules.ai.v3.final_save_contract import install_intent, make_intent, resolve_intent
    args = dict(tenant_id=str(QA_TENANT), user_id=str(uuid4()), job_id=str(uuid4()),
        delivery_id="delivery", route_policy=MANAGED_POLICY, route_fingerprint="b" * 64,
        documents=[{"doc_id": str(uuid4()), "revision": "document:" + "a" * 64, "text_sha256": "a" * 64}],
        output_digest="c" * 64)
    intent = make_intent(**args)
    assert intent["route_policy"] == MANAGED_POLICY
    held = install_intent({}, intent)
    assert resolve_intent(held, intent, course_id=str(uuid4()), output_digest="c" * 64)["v3_final_save_receipt"]
    with pytest.raises(ValueError):
        make_intent(**(args | {"route_policy": "qa-luna-pending-journal-v1"}))


@pytest.mark.asyncio
async def test_factory_readiness_uses_exact_validated_settings(monkeypatch):
    from app.modules.admin.model_routing import chatgpt_reserve as reserve
    from app.modules.ai.direct_luna_responses_factory import create_managed_qa_client
    config = settings("vm-development-worker", CHATGPT_RESERVE_URL="http://127.0.0.1:18999/v1",
        CHATGPT_RESERVE_TOKEN="synthetic" * 6, CHATGPT_RESERVE_MODEL="gpt-5.6-luna",
        CHATGPT_RESERVE_AUTH_MODE="codex_cli", AI_MANAGED_LUNA_QA_CREDENTIAL_REVISION="managed-r1")
    readiness = AsyncMock(return_value=SimpleNamespace(ready=True))
    monkeypatch.setattr(reserve, "check_readiness", readiness)
    value = await create_managed_qa_client(settings=config, tenant_id=QA_TENANT,
        user_id=uuid4(), job_id=str(uuid4()))
    assert type(value) is ManagedLunaClient
    readiness.assert_awaited_once_with(config)
    config.AI_DIRECT_LUNA_QA_DEV_ENABLED = True
    with pytest.raises(ValueError):
        await create_managed_qa_client(settings=config, tenant_id=QA_TENANT,
            user_id=uuid4(), job_id=str(uuid4()))
    readiness.assert_awaited_once()
