from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.config import LUNA6_MODEL, Settings
from app.modules.admin.model_routing import chatgpt_reserve
from app.modules.admin.model_routing.catalog import CHATGPT_RESERVE_ROUTE_ID, DEEPSEEK_ROUTE_ID
from app.modules.ai import llm_client
from app.modules.ai.production_smoke_route import PRODUCTION_SMOKE_TENANT, uses_production_smoke_route


@pytest.fixture
def smoke_settings(monkeypatch):
    settings = Settings(
        DEPLOYMENT_ENVIRONMENT="kz-production",
        AI_PRODUCTION_SMOKE_LUNA_ONLY=True,
        CHATGPT_RESERVE_URL="http://10.0.0.25:8100/v1",
        CHATGPT_RESERVE_TOKEN="synthetic-test-token",
        CHATGPT_RESERVE_AUTH_MODE="codex_cli",
        ASUS_EMBEDDINGS_ENABLED=True,
    )
    monkeypatch.setattr(llm_client, "get_settings", lambda: settings)
    monkeypatch.setattr(llm_client, "_resolve_db_key", AsyncMock(side_effect=AssertionError("managed key lookup")))
    return settings


def test_only_the_existing_production_synthetic_tenant_is_in_scope(smoke_settings):
    assert uses_production_smoke_route(smoke_settings, PRODUCTION_SMOKE_TENANT)
    assert uses_production_smoke_route(smoke_settings, str(PRODUCTION_SMOKE_TENANT))
    assert not uses_production_smoke_route(smoke_settings, uuid4())
    assert not uses_production_smoke_route(smoke_settings, None)
    assert not uses_production_smoke_route(
        smoke_settings.model_copy(update={"AI_PRODUCTION_SMOKE_LUNA_ONLY": False}), PRODUCTION_SMOKE_TENANT,
    )
    assert not uses_production_smoke_route(
        smoke_settings.model_copy(update={"DEPLOYMENT_ENVIRONMENT": "vm-development-worker"}),
        PRODUCTION_SMOKE_TENANT,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["ready", "disabled", "wrong-model", "offline"])
async def test_luna_is_the_only_generation_provider(monkeypatch, smoke_settings, state):
    order = (DEEPSEEK_ROUTE_ID, CHATGPT_RESERVE_ROUTE_ID) if state != "disabled" else (DEEPSEEK_ROUTE_ID,)
    monkeypatch.setattr(llm_client, "resolve_runtime_generation_model_order", AsyncMock(return_value=order))
    monkeypatch.setattr(llm_client, "resolve_runtime_settings", AsyncMock(return_value=SimpleNamespace(
        text=lambda _key: LUNA6_MODEL if state != "wrong-model" else "gpt-5.6-luna",
        number=lambda _key: 80.0,
    )))
    ready = AsyncMock(return_value=SimpleNamespace(ready=state == "ready"))
    monkeypatch.setattr(chatgpt_reserve, "check_readiness", ready)

    if state == "ready":
        client = await llm_client.ResilientLLMClient.from_settings_async(tenant_id=PRODUCTION_SMOKE_TENANT)
        assert client.provider_names == ["chatgpt-reserve"]
        assert client._clients[0].config.model == LUNA6_MODEL
        assert client._clients[0].max_retries == 0
    else:
        with pytest.raises(llm_client.AllProvidersFailedError, match="production_smoke_luna_unavailable"):
            await llm_client.ResilientLLMClient.from_settings_async(tenant_id=PRODUCTION_SMOKE_TENANT)
    if state in {"ready", "offline"}:
        ready.assert_awaited_once_with(smoke_settings, model=LUNA6_MODEL)
    else:
        ready.assert_not_awaited()
    llm_client._resolve_db_key.assert_not_awaited()


@pytest.mark.asyncio
async def test_synthetic_upload_uses_only_the_private_embedding_pool(smoke_settings):
    client = await llm_client.ResilientEmbeddingsClient.from_settings_async(tenant_id=PRODUCTION_SMOKE_TENANT)
    assert {item.config.embedding_space_provider for item in client._clients} == {"asus-qwen-embedding-8b"}
    assert len(client.provider_names) == 3

    smoke_settings.ASUS_EMBEDDINGS_ENABLED = False
    with pytest.raises(llm_client.AllProvidersFailedError, match="production_smoke_private_embeddings_unavailable"):
        await llm_client.ResilientEmbeddingsClient.from_settings_async(tenant_id=PRODUCTION_SMOKE_TENANT)
    llm_client._resolve_db_key.assert_not_awaited()
