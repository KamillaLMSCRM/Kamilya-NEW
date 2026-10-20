"""One opt-in request profile; no managed route, credentials, or shared mutation."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.ai import llm_client as llm


async def test_validated_evidence_profile_is_local_and_applies_to_syntax_correction(monkeypatch):
    provider = chain()
    configs = [client.config for client in provider._clients]
    seen = []

    async def invoke(client, messages, **kwargs):
        seen.append((client.config, client.max_tokens, client.max_retries))
        return SimpleNamespace(content='{"ok":true}' if len(seen) == 2 else '{"ok":true')

    monkeypatch.setattr(llm.LLMClient, "ainvoke", invoke)
    result = await provider.ainvoke_validated("synthetic", json.loads,
        request_profile="evidence_low", repair_json_syntax=True)
    assert result.value == {"ok": True} and result.attempt_count == 2
    assert len(seen) == 2
    assert all(cfg.extra_body == {"thinking": {"type": "enabled"}, "reasoning_effort": "low"}
               and tokens == 8192 and retries == 0 for cfg, tokens, retries in seen)
    assert [client.config for client in provider._clients] == configs
    assert provider.max_tokens == 2000


async def test_validated_evidence_profile_preserves_existing_fallback_and_byok(monkeypatch):
    provider = chain()
    seen = []

    async def invoke(client, messages, **kwargs):
        seen.append((client.name, client.config.extra_body, client.max_tokens))
        if client.name == "deepseek":
            raise llm.ProviderFailedError(client.name, RuntimeError("synthetic unavailable"))
        return SimpleNamespace(content='{"ok":true}')

    monkeypatch.setattr(llm.LLMClient, "ainvoke", invoke)
    result = await provider.ainvoke_validated("synthetic", json.loads, request_profile="evidence_low")
    assert result.provider == "fallback" and result.attempt_count == 2
    assert seen == [("deepseek", {"thinking": {"type": "enabled"}, "reasoning_effort": "low"}, 8192),
                    ("fallback", {}, 2000)]
    provider = llm.ResilientLLMClient([llm.LLMProviderConfig("deepseek", "https://byok.invalid",
        "synthetic", "same-model", extra_body={"thinking": {"type": "disabled"}})], max_tokens=2000)
    with pytest.raises(llm.AllProvidersFailedError):
        await provider.ainvoke_validated("synthetic", json.loads, request_profile="evidence_low")
    assert seen[-1] == ("deepseek", {"thinking": {"type": "disabled"}}, 2000)


async def test_validated_profile_timeout_falls_back_without_mutating_shared_clients(monkeypatch):
    provider = chain()
    configs = [client.config for client in provider._clients]
    from app.modules.admin.runtime_configuration.catalog import default_snapshot
    snapshot = default_snapshot()
    policy = SimpleNamespace(integer=snapshot.integer, number=lambda name: 0.001)
    monkeypatch.setattr(llm, "resolve_runtime_settings", AsyncMock(return_value=policy))

    async def invoke(client, *args, **kwargs):
        if client.name == "deepseek":
            await asyncio.Event().wait()
        return SimpleNamespace(content='{"ok":true}')

    monkeypatch.setattr(llm.LLMClient, "ainvoke", invoke)
    result = await provider.ainvoke_validated("synthetic", json.loads, request_profile="evidence_low")
    assert result.provider == "fallback" and result.attempt_count == 2
    assert [client.config for client in provider._clients] == configs


@pytest.mark.parametrize("profile", [True, "high", "evidence_low ", ""])
async def test_invalid_validated_profile_rejected_before_any_call(monkeypatch, profile):
    invoke = AsyncMock(side_effect=AssertionError("no provider call allowed"))
    monkeypatch.setattr(llm.LLMClient, "ainvoke", invoke)
    with pytest.raises(ValueError, match="request_profile_invalid"):
        await chain().ainvoke_validated("synthetic", json.loads, request_profile=profile)
    invoke.assert_not_called()


def chain():
    return llm.ResilientLLMClient([
        llm.LLMProviderConfig("deepseek", "https://primary.invalid", "synthetic", "same-model",
            max_retries=2, extra_body={"thinking": {"type": "disabled"}}, managed_evidence_profile=True),
        llm.LLMProviderConfig("fallback", "https://fallback.invalid", "synthetic", "same-fallback", max_retries=0),
    ], temperature=0, max_tokens=2000)


async def test_profile_changes_only_managed_deepseek_attempt_and_not_next_request(monkeypatch):
    provider = chain()
    original_configs = [client.config for client in provider._clients]
    seen, deadlines = [], []
    original_timeout = asyncio.timeout

    def timeout(seconds):
        deadlines.append(seconds)
        return original_timeout(seconds)

    async def request(client, payload):
        seen.append(payload)
        assert client.max_retries == 0
        return {"choices": [{"message": {"content": "synthetic"}}]}

    monkeypatch.setattr(llm.asyncio, "timeout", timeout)
    monkeypatch.setattr(llm.LLMClient, "_request", request)
    await provider.ainvoke("synthetic", request_profile="evidence_low", provider_deadline_seconds=8)
    await provider.ainvoke("synthetic", provider_deadline_seconds=8)
    assert seen[0]["model"] == seen[1]["model"] == "same-model"
    assert seen[0]["thinking"] == {"type": "enabled"} and seen[0]["reasoning_effort"] == "low"
    assert seen[0]["max_tokens"] == 8192 and deadlines == [45, 8]
    assert seen[1]["thinking"] == {"type": "disabled"} and seen[1]["max_tokens"] == 2000
    assert "reasoning_effort" not in seen[1]
    assert [client.config for client in provider._clients] == original_configs
    assert provider.max_tokens == 2000 and provider.provider_names == ["deepseek", "fallback"]


async def test_profile_failure_uses_existing_fallback_with_original_limits_no_retry(monkeypatch):
    provider = chain()
    seen, deadlines = [], []
    original_timeout = asyncio.timeout

    def timeout(seconds):
        deadlines.append(seconds)
        return original_timeout(seconds)

    async def invoke(client, *args, **kwargs):
        seen.append((client.name, client.max_tokens, client.config.extra_body))
        assert client.max_retries == 0
        if client.name == "deepseek":
            raise llm.ProviderFailedError(client.name, RuntimeError("synthetic unavailable"))
        return SimpleNamespace(content="fallback")

    monkeypatch.setattr(llm.asyncio, "timeout", timeout)
    monkeypatch.setattr(llm.LLMClient, "ainvoke", invoke)
    result = await provider.ainvoke("synthetic", request_profile="evidence_low", provider_deadline_seconds=8)
    assert result.content == "fallback" and deadlines == [45, 8]
    assert seen == [("deepseek", 8192, {"thinking": {"type": "enabled"}, "reasoning_effort": "low"}),
                    ("fallback", 2000, {})]


@pytest.mark.parametrize("profile", [True, "high", "evidence_low ", ""])
async def test_invalid_profile_rejected_before_provider_call(profile, monkeypatch):
    async def unexpected(*args, **kwargs):
        raise AssertionError("no provider call allowed")
    monkeypatch.setattr(llm.LLMClient, "ainvoke", unexpected)
    with pytest.raises(ValueError, match="request_profile_invalid"):
        await chain().ainvoke("synthetic", request_profile=profile)


async def test_tenant_override_named_deepseek_does_not_gain_managed_profile(monkeypatch):
    from app.modules.admin.tenant_ai_providers import service as overrides
    config = llm.LLMProviderConfig("deepseek", "https://tenant.invalid", "synthetic", "tenant-model",
        extra_body={"thinking": {"type": "disabled"}})
    monkeypatch.setattr(overrides, "resolve_tenant_provider", AsyncMock(return_value=config))
    provider = await llm.ResilientLLMClient.from_settings_async(tenant_id=UUID(int=1), max_tokens=2000)
    seen = []
    async def request(client, payload):
        seen.append(payload)
        return {"choices": [{"message": {"content": "synthetic"}}]}
    monkeypatch.setattr(llm.LLMClient, "_request", request)
    await provider.ainvoke("synthetic", request_profile="evidence_low", provider_deadline_seconds=8)
    assert seen[0]["thinking"] == {"type": "disabled"}
    assert seen[0]["max_tokens"] == 2000 and "reasoning_effort" not in seen[0]
    assert provider._clients[0].config is config


def test_only_global_deepseek_builder_marks_profile_capability(monkeypatch):
    monkeypatch.setattr(llm, "get_settings", lambda: SimpleNamespace(DEEPSEEK_API_KEY="synthetic",
        DEEPSEEK_BASE_URL="https://primary.invalid", DEEPSEEK_MODEL="same-model"))
    assert llm._deepseek_llm_provider().managed_evidence_profile is True


@pytest.mark.parametrize("env_key", ["synthetic-env", ""])
async def test_global_factory_preserves_capability_for_env_and_stored_key(monkeypatch, env_key):
    monkeypatch.setattr(llm, "get_settings", lambda: SimpleNamespace(DEEPSEEK_API_KEY=env_key,
        DEEPSEEK_BASE_URL="https://primary.invalid", DEEPSEEK_MODEL="same-model"))
    monkeypatch.setattr(llm, "resolve_runtime_generation_model_order", AsyncMock(return_value=[llm.DEEPSEEK_ROUTE_ID]))
    monkeypatch.setattr(llm, "_resolve_db_key", AsyncMock(return_value="synthetic-resolved"))
    provider = await llm.ResilientLLMClient.from_settings_async(max_tokens=2000)
    assert provider.provider_names == ["deepseek"]
    assert provider._clients[0].config.managed_evidence_profile is True
