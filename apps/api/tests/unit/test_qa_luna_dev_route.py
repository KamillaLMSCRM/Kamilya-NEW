"""DEV QA-only route: explicit opt-in, exact identity, and no fallback."""
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.modules.admin.model_routing import chatgpt_reserve
from app.modules.ai import llm_client
from app.modules.ai.qa_luna_dev_route import QA_TENANT, qa_luna_dev_client


def settings(**updates):
    values = {"AI_QA_LUNA_DEV_ENABLED": True, "DEPLOYMENT_ENVIRONMENT": "render-development-worker",
              "AI_LESSON_CYCLE_DEV_ENABLED": True, "AI_LESSON_CYCLE_DEV_TENANTS": [str(QA_TENANT)]}
    values.update(updates)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,tenant", [
    ({"AI_QA_LUNA_DEV_ENABLED": False}, QA_TENANT),
    ({"AI_QA_LUNA_DEV_ENABLED": False, "DEPLOYMENT_ENVIRONMENT": "production"}, QA_TENANT),
    ({}, UUID("00000000-0000-0000-0000-000000000001")),
])
async def test_no_override_outside_exact_opted_in_dev_qa(changes, tenant):
    assert await qa_luna_dev_client(settings=settings(**changes), tenant_id=tenant, temperature=0.1) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"DEPLOYMENT_ENVIRONMENT": "production"},
    {"DEPLOYMENT_ENVIRONMENT": "render-development"},
    {"AI_LESSON_CYCLE_DEV_ENABLED": False},
    {"AI_LESSON_CYCLE_DEV_TENANTS": []},
])
async def test_enabled_qa_misconfiguration_fails_closed(changes):
    with pytest.raises(RuntimeError, match="dev_qa_luna_route_misconfigured"):
        await qa_luna_dev_client(settings=settings(**changes), tenant_id=QA_TENANT, temperature=0.1)


@pytest.mark.asyncio
async def test_unavailable_worker_connector_never_falls_back(monkeypatch):
    async def unavailable():
        return SimpleNamespace(ready=False)
    monkeypatch.setattr(chatgpt_reserve, "check_readiness", unavailable)
    with pytest.raises(RuntimeError, match="dev_qa_luna_connector_not_ready"):
        await qa_luna_dev_client(settings=settings(), tenant_id=QA_TENANT, temperature=0.1)


@pytest.mark.asyncio
async def test_qa_single_reserve_provider_and_no_fallback(monkeypatch):
    async def ready():
        return SimpleNamespace(ready=True)
    config = llm_client.LLMProviderConfig(name="chatgpt-reserve", base_url="http://127.0.0.1:1234/v1",
        model="gpt-5.6-luna", api_key="synthetic", max_retries=0)
    monkeypatch.setattr(chatgpt_reserve, "check_readiness", ready)
    monkeypatch.setattr(llm_client, "_generation_fallback_providers", lambda ids: [config])
    client = await qa_luna_dev_client(settings=settings(), tenant_id=QA_TENANT, temperature=0.1)
    assert len(client._clients) == 1
    assert client._clients[0].config.name == "chatgpt-reserve"
    assert client._clients[0].config.model == "gpt-5.6-luna"
    assert client._clients[0].max_retries == 0

@pytest.mark.asyncio
async def test_vm_worker_exact_qa_route(monkeypatch):
    async def ready():
        return SimpleNamespace(ready=True)
    config = llm_client.LLMProviderConfig(name='chatgpt-reserve', base_url='http://127.0.0.1:1234/v1',
        model='gpt-5.6-luna', api_key='synthetic', max_retries=0)
    monkeypatch.setattr(chatgpt_reserve, 'check_readiness', ready)
    monkeypatch.setattr(llm_client, '_generation_fallback_providers', lambda ids: [config])
    client = await qa_luna_dev_client(settings=settings(DEPLOYMENT_ENVIRONMENT='vm-development-worker'), tenant_id=QA_TENANT, temperature=0.1)
    assert len(client._clients) == 1
    assert client._clients[0].config.model == 'gpt-5.6-luna'

@pytest.mark.asyncio
@pytest.mark.parametrize('changes,tenant,should_raise', [
    ({'AI_QA_LUNA_DEV_ENABLED': False}, QA_TENANT, False),
    ({'AI_LESSON_CYCLE_DEV_ENABLED': False}, QA_TENANT, True),
    ({'AI_LESSON_CYCLE_DEV_TENANTS': []}, QA_TENANT, True),
    ({}, UUID('00000000-0000-0000-0000-000000000001'), False),
])
async def test_vm_worker_qa_route_fails_closed_or_stays_outside_scope(changes, tenant, should_raise):
    values = {'DEPLOYMENT_ENVIRONMENT': 'vm-development-worker', **changes}
    if should_raise:
        with pytest.raises(RuntimeError, match='dev_qa_luna_route_misconfigured'):
            await qa_luna_dev_client(settings=settings(**values), tenant_id=tenant, temperature=0.1)
    else:
        assert await qa_luna_dev_client(settings=settings(**values), tenant_id=tenant, temperature=0.1) is None
