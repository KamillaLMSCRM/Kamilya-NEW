"""Autonomous profile budgets are request local and checkpoint-bound."""
from dataclasses import replace
from uuid import uuid4

import pytest

from app.modules.admin.runtime_configuration.catalog import RuntimeSnapshot
from app.modules.ai import llm_client
from app.modules.ai.v3.provider_profile import V3ProfiledClient


def policy(deep=65536, luna=32768):
    return RuntimeSnapshot(1, {"provider.deepseek.timeout_seconds": 120,
        "provider.chatgpt.timeout_seconds": 60, "generation.editorial_deepseek_max_tokens": deep,
        "generation.editorial_luna_max_tokens": luna})


def route():
    return llm_client.ResilientLLMClient([
        llm_client.LLMProviderConfig("deepseek", "https://primary.invalid/v1", "synthetic", "deep",
            managed_evidence_profile=True),
        llm_client.LLMProviderConfig("chatgpt-reserve", "https://reserve.invalid/v1", "synthetic", "reserve", timeout=60),
    ], max_tokens=8192)


@pytest.mark.asyncio
async def test_autonomous_wire_caps_fallback_and_shared_clients(monkeypatch):
    seen = []
    async def request(self, payload):
        seen.append((self.config.name, payload["max_tokens"], self.config.timeout))
        if self.config.name == "deepseek":
            import httpx
            rejection = httpx.Response(401, request=httpx.Request('POST', 'https://primary.invalid/v1'))
            raise llm_client.ProviderFailedError("deepseek", httpx.HTTPStatusError(
                'explicit rejection', request=rejection.request, response=rejection))
        return {"choices": [{"message": {"content": "{}"}}]}
    monkeypatch.setattr(llm_client.LLMClient, "_request", request)
    raw = route()
    before = [(x.config, x.max_tokens) for x in raw._clients]
    profiled = V3ProfiledClient(raw, policy(), job_id=str(uuid4()), cooperative_deadline=True, autonomous_output=True)
    await profiled.ainvoke("question")
    assert [(name, cap) for name, cap, _ in seen] == [("deepseek", 65536), ("chatgpt-reserve", 32768)]
    assert seen[1][2] == 60
    assert [(x.config, x.max_tokens) for x in raw._clients] == before


def test_legacy_profile_and_budget_identity():
    raw = route()
    old = V3ProfiledClient(raw, policy(), job_id="a", cooperative_deadline=True)
    old_other = V3ProfiledClient(raw, policy(32768, 16384), job_id="b", cooperative_deadline=True)
    assert old.cache_fingerprint() == old_other.cache_fingerprint()
    new = V3ProfiledClient(raw, policy(), job_id="a", cooperative_deadline=True, autonomous_output=True)
    changed = V3ProfiledClient(raw, policy(32768, 16384), job_id="b", cooperative_deadline=True, autonomous_output=True)
    assert new.cache_fingerprint() != changed.cache_fingerprint()
    assert new.generation_deadline_seconds == 240
    assert new._request_profile == "course_generation_autonomous"
    assert old._request_profile == "course_generation"


def test_mixed_or_unmanaged_route_never_upgrades():
    raw = route()
    raw._clients[0].config = replace(raw._clients[0].config, managed_evidence_profile=False)
    old = V3ProfiledClient(raw, policy(), job_id="a", cooperative_deadline=True)
    requested = V3ProfiledClient(raw, policy(), job_id="b", cooperative_deadline=True, autonomous_output=True)
    assert requested.cache_fingerprint() == old.cache_fingerprint()


@pytest.mark.asyncio
async def test_owned_direct_managed_budget_and_checkpoint_change(monkeypatch):
    from types import SimpleNamespace

    from app.modules.ai.direct_luna_responses_client import DirectLunaResponsesClient
    from app.modules.ai.managed_luna_client import ManagedLunaClient
    from app.modules.ai.v3.revision_policy import AUTONOMOUS_EDITORIAL_REVIEW_POLICY
    from app.modules.ai.v3.service import _practical_output_budget
    from app.modules.ai.v3.stage_checkpoint import _digest, stage_plan
    managed = ManagedLunaClient.__new__(ManagedLunaClient)
    managed._model = "gpt-6-luna"
    direct = DirectLunaResponsesClient.__new__(DirectLunaResponsesClient)
    import app.core.db as core_db
    from app.modules.admin.runtime_configuration.runtime import resolve_runtime_settings, runtime_settings_scope
    captured = RuntimeSnapshot(37, {**policy().values, "generation.editorial_max_revisions": 4})
    def forbidden_db():
        raise AssertionError("scoped v33 operation must not reopen runtime settings DB")
    monkeypatch.setattr(core_db, "async_session_factory", forbidden_db)
    with runtime_settings_scope(captured):
        assert await _practical_output_budget(AUTONOMOUS_EDITORIAL_REVIEW_POLICY, managed) == 32768
        observed = await resolve_runtime_settings()
        assert observed.revision == 37 and observed.integer("generation.editorial_max_revisions") == 4
        assert await _practical_output_budget(AUTONOMOUS_EDITORIAL_REVIEW_POLICY, direct) == 16384
        assert await _practical_output_budget("legacy-policy", managed) == 16384
    journal = SimpleNamespace(tenant_id="tenant", job_id="job")
    def plan(cap):
        return stage_plan(journal, stage="review", group_id="practical:test:output=" + str(cap),
            source_sha256="a" * 64, route_fingerprint="b" * 64, messages=[], response_format=None)
    assert _digest(plan(16384)) != _digest(plan(32768))


@pytest.mark.asyncio
async def test_server_reserve_only_uses_luna_cap_without_creating_deepseek(monkeypatch):
    seen = []
    async def request(self, payload):
        seen.append((self.config.name, payload["max_tokens"], self.config.timeout))
        return {"choices": [{"message": {"content": "{}"}}]}
    monkeypatch.setattr(llm_client.LLMClient, "_request", request)
    raw = llm_client.ResilientLLMClient([
        llm_client.LLMProviderConfig("chatgpt-reserve", "https://reserve.invalid/v1", "synthetic", "reserve", timeout=60),
    ], max_tokens=8192)
    profiled = V3ProfiledClient(raw, policy(), job_id=str(uuid4()), cooperative_deadline=True, autonomous_output=True)
    await profiled.ainvoke("question")
    assert seen == [("chatgpt-reserve", 32768, 60)]
    assert profiled.provider_names == ["chatgpt-reserve"]
    assert profiled.generation_deadline_seconds == 60
