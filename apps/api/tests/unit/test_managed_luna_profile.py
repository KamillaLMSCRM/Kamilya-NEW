"""Offline QA profile isolation and exact-model readiness."""
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.modules.admin.model_routing import chatgpt_reserve
from app.modules.ai.direct_luna_responses_factory import create_managed_qa_client
from app.modules.ai.qa_luna_dev_route import QA_TENANT


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError('network denied')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket.socket, 'connect_ex', deny)


def settings(**updates):
    data = dict(DEPLOYMENT_ENVIRONMENT='vm-development-worker', AI_MANAGED_LUNA_QA_DEV_ENABLED=True,
        AI_DIRECT_LUNA_QA_DEV_ENABLED=False, AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED=True,
        AI_MANAGED_LUNA_QA_CREDENTIAL_REVISION='r1', CHATGPT_RESERVE_URL='http://127.0.0.1:18999/v1',
        CHATGPT_RESERVE_TOKEN='synthetic-token', CHATGPT_RESERVE_MODEL='gpt-5.6-luna',
        CHATGPT_RESERVE_AUTH_MODE='codex_cli')
    data.update(updates)
    return SimpleNamespace(**data)


@pytest.mark.asyncio
async def test_luna6_uses_isolated_model_view_and_exact_readiness(monkeypatch):
    s = settings()
    reported = {'model': 'gpt-5.6-luna'}
    real = httpx.AsyncClient
    def handler(_request):
        return httpx.Response(200, json={'protocol': chatgpt_reserve.PROTOCOL, 'authorization': 'codex_cli',
                                          'model': reported['model'], 'ready': True})
    monkeypatch.setattr(chatgpt_reserve.httpx, 'AsyncClient',
                        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    async def create():
        return await create_managed_qa_client(settings=s, tenant_id=QA_TENANT, user_id=uuid4(),
                                              job_id='job', profile='luna6')
    with pytest.raises(ValueError, match='managed_qa_luna_unavailable'):
        await create()
    reported['model'] = 'gpt-6-luna'
    client = await create()
    assert client.generation_deadline_seconds == 300
    assert client._model == 'gpt-6-luna' and client._reasoning_effort == 'high'
    assert s.CHATGPT_RESERVE_MODEL == 'gpt-5.6-luna'


@pytest.mark.asyncio
@pytest.mark.parametrize(('changes', 'tenant', 'profile'), [
    ({}, 'foreign', 'luna6'), ({'DEPLOYMENT_ENVIRONMENT': 'production'}, 'qa', 'luna6'),
    ({'AI_MANAGED_LUNA_QA_DEV_ENABLED': False}, 'qa', 'luna6'),
    ({'AI_DIRECT_LUNA_QA_DEV_ENABLED': True}, 'qa', 'luna6'),
    ({'AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED': False}, 'qa', 'luna6'),
    ({}, 'qa', 'other'), ({'CHATGPT_RESERVE_MODEL': 'gpt-6-luna'}, 'qa', 'legacy-luna56')])
async def test_profile_rejects_outside_scope_before_readiness(monkeypatch, changes, tenant, profile):
    ready = AsyncMock(return_value=SimpleNamespace(ready=True))
    monkeypatch.setattr(chatgpt_reserve, 'check_readiness', ready)
    with pytest.raises(ValueError, match='managed_qa_luna_unavailable'):
        await create_managed_qa_client(settings=settings(**changes),
            tenant_id=QA_TENANT if tenant == 'qa' else uuid4(), user_id=uuid4(), job_id='job', profile=profile)
    ready.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_readiness_receives_original_settings(monkeypatch):
    ready = AsyncMock(return_value=SimpleNamespace(ready=True))
    monkeypatch.setattr(chatgpt_reserve, 'check_readiness', ready)
    s = settings()
    client = await create_managed_qa_client(settings=s, tenant_id=QA_TENANT, user_id=uuid4(), job_id='job')
    ready.assert_awaited_once_with(s)
    assert client._model == 'gpt-5.6-luna' and client.generation_deadline_seconds == 60
