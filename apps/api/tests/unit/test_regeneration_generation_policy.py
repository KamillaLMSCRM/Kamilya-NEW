"""Regeneration must use the same factual-generation policy as new courses."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.admin.runtime_configuration import runtime
from app.modules.admin.runtime_configuration.catalog import RuntimeSnapshot, effective_values
from app.modules.ai import router


@pytest.mark.asyncio
async def test_regeneration_client_uses_one_configured_generation_temperature(monkeypatch):
    previous_policy = runtime._scope.get()
    policy = RuntimeSnapshot(7, effective_values({"generation.temperature": 0.15}))
    read = AsyncMock(return_value=policy)
    monkeypatch.setattr(runtime, "resolve_runtime_settings", read)
    tenant = uuid4()

    async def factory(**kwargs):
        assert runtime._scope.get() is policy
        assert kwargs == {"tenant_id": tenant, "temperature": 0.15, "max_tokens": 2000}
        return "owned-fake-client"

    monkeypatch.setattr(router.ResilientLLMClient, "from_settings_async", factory)
    assert await router._regeneration_llm(tenant_id=tenant, max_tokens=2000) == "owned-fake-client"
    read.assert_awaited_once_with()
    assert runtime._scope.get() is previous_policy
