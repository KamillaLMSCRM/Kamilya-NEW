"""Autonomous provider failover must fence unknown post-dispatch outcomes."""

import copy
from types import SimpleNamespace

import httpx
import pytest

from app.modules.admin.runtime_configuration.catalog import default_snapshot
from app.modules.admin.runtime_configuration.runtime import runtime_settings_scope
from app.modules.ai import llm_client


def chain():
    return llm_client.ResilientLLMClient(
        [
            llm_client.LLMProviderConfig(
                "deepseek",
                "https://primary.invalid/v1",
                "fake",
                "primary",
                managed_evidence_profile=True,
                max_retries=2,
            ),
            llm_client.LLMProviderConfig(
                "chatgpt-reserve", "https://reserve.invalid/v1", "fake", "reserve", max_retries=2
            ),
        ],
        max_tokens=2000,
        max_retries_per_provider=2,
    )


def failure(kind):
    request = httpx.Request("POST", "https://primary.invalid/v1/chat/completions")
    if kind == "read":
        return httpx.ReadTimeout("synthetic", request=request)
    if kind == "write":
        return httpx.WriteTimeout("synthetic", request=request)
    if kind == "connect":
        return httpx.ConnectError("synthetic", request=request)
    if kind == "connect_timeout":
        return httpx.ConnectTimeout("synthetic", request=request)
    if kind == "pool_timeout":
        return httpx.PoolTimeout("synthetic", request=request)
    if kind == "unknown":
        return RuntimeError("synthetic")
    code = int(kind)
    return httpx.HTTPStatusError("synthetic", request=request, response=httpx.Response(code, request=request))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["read", "write", "outer", "500", "502", "503", "504", "408", "unknown"])
async def test_autonomous_unknown_failure_never_dispatches_reserve(monkeypatch, kind):
    raw = chain()
    calls = []

    async def invoke(self, messages, **kwargs):
        calls.append(self.config.name)
        if self.config.name == "deepseek":
            if kind == "outer":
                raise TimeoutError("synthetic")
            raise llm_client.ProviderFailedError("deepseek", failure(kind))
        return SimpleNamespace(content="{}")

    monkeypatch.setattr(llm_client.LLMClient, "ainvoke", invoke)
    with runtime_settings_scope(default_snapshot()):
        with pytest.raises(Exception) as exc:
            await raw.ainvoke("test", request_profile="course_generation_autonomous", provider_deadline_seconds=10)
    assert type(exc.value).__name__ == "ProviderOutcomeUnknownError"
    assert calls == ["deepseek"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["connect", "connect_timeout", "pool_timeout", "400", "401", "403", "429"])
async def test_known_predispatch_or_terminal_failure_can_fail_over(monkeypatch, kind):
    raw = chain()
    before = copy.deepcopy([(client.config, client.max_retries, client.max_tokens) for client in raw._clients])
    calls = []

    async def invoke(self, messages, **kwargs):
        calls.append((self.config.name, self.config.max_retries, self.max_retries, self.max_tokens))
        if self.config.name == "deepseek":
            raise llm_client.ProviderFailedError("deepseek", failure(kind))
        return SimpleNamespace(content="{}")

    monkeypatch.setattr(llm_client.LLMClient, "ainvoke", invoke)
    with runtime_settings_scope(default_snapshot()):
        await raw.ainvoke("test", request_profile="course_generation_autonomous", provider_deadline_seconds=10)
    assert [x[0] for x in calls] == ["deepseek", "chatgpt-reserve"]
    assert calls[1][1:] == (0, 0, 32768)
    assert [(client.config, client.max_retries, client.max_tokens) for client in raw._clients] == before


@pytest.mark.asyncio
async def test_legacy_profile_keeps_existing_unknown_failure_fallback(monkeypatch):
    raw = chain()
    calls = []

    async def invoke(self, messages, **kwargs):
        calls.append(self.config.name)
        if self.config.name == "deepseek":
            raise llm_client.ProviderFailedError("deepseek", failure("read"))
        return SimpleNamespace(content="{}")

    monkeypatch.setattr(llm_client.LLMClient, "ainvoke", invoke)
    with runtime_settings_scope(default_snapshot()):
        await raw.ainvoke("test", request_profile="course_generation", provider_deadline_seconds=10)
    assert calls == ["deepseek", "chatgpt-reserve"]


@pytest.mark.asyncio
async def test_reserve_only_clone_has_no_retry_even_without_deadline(monkeypatch):
    raw = chain()
    raw._clients = raw._clients[1:]
    before = (raw._clients[0].config, raw._clients[0].max_retries)
    seen = []

    async def invoke(self, messages, **kwargs):
        seen.append((self.config.max_retries, self.max_retries, self.max_tokens))
        return SimpleNamespace(content="{}")

    monkeypatch.setattr(llm_client.LLMClient, "ainvoke", invoke)
    with runtime_settings_scope(default_snapshot()):
        await raw.ainvoke("test", request_profile="course_generation_autonomous")
    assert seen == [(0, 0, 32768)]
    assert (raw._clients[0].config, raw._clients[0].max_retries) == before
