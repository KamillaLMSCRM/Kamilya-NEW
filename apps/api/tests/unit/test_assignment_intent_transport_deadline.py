"""Replay the DEV slow-primary pattern without network, credentials or sleeps."""
import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest

from app.modules.ai import llm_client as llm
from app.modules.methodologist_workbench import intent_application as application
from app.modules.methodologist_workbench.assignment_schemas import AssignmentInterpretRequest
from app.modules.methodologist_workbench.plan_contract import ActorContext

CONTENT = json.dumps({"action": "assignment_preview", "course_query": "Course", "department_query": "QA",
                      "due_date": "2026-12-20", "due_time": "18:00:00", "notify": False, "include_descendants": False})


def chain():
    return llm.ResilientLLMClient([
        llm.LLMProviderConfig("primary", "https://primary.invalid", "synthetic", "first", timeout=120, max_retries=2),
        llm.LLMProviderConfig("fallback", "https://fallback.invalid", "synthetic", "second", timeout=60, max_retries=1),
    ], temperature=0, max_tokens=1200, max_retries_per_provider=0)


async def test_hanging_primary_reaches_existing_fallback_without_changing_route(monkeypatch):
    original = chain()
    calls = []
    async def invoke(self, messages, **kwargs):
        calls.append(self.name)
        if self.name == "primary":
            await asyncio.Event().wait()
        return SimpleNamespace(content=CONTENT)
    monkeypatch.setattr(llm.LLMClient, "ainvoke", invoke)
    result = await original.ainvoke([{"role": "user", "content": "synthetic"}], provider_deadline_seconds=0.01)
    assert result.content == CONTENT and calls == ["primary", "fallback"]
    assert [c.max_retries for c in original._clients] == [2, 1]
    assert [c.config for c in original._clients] == [c.config for c in chain()._clients]
    assert original.max_tokens == 1200 and original.temperature == 0


async def test_all_hanging_providers_terminate_without_repeating(monkeypatch):
    calls = []
    async def hang(self, *args, **kwargs):
        calls.append(self.name)
        await asyncio.Event().wait()
    monkeypatch.setattr(llm.LLMClient, "ainvoke", hang)
    with pytest.raises(llm.AllProvidersFailedError):
        await chain().ainvoke("synthetic", provider_deadline_seconds=0.01)
    assert calls == ["primary", "fallback"]


async def test_external_cancellation_does_not_fall_back(monkeypatch):
    calls = []
    async def cancel(self, *args, **kwargs):
        calls.append(self.name)
        raise asyncio.CancelledError()
    monkeypatch.setattr(llm.LLMClient, "ainvoke", cancel)
    with pytest.raises(asyncio.CancelledError):
        await chain().ainvoke("synthetic", provider_deadline_seconds=0.01)
    assert calls == ["primary"]


@pytest.mark.parametrize("deadline", [True, False, 0, -1, float("nan"), float("inf"), "8"])
async def test_invalid_deadlines_reject_before_calls(deadline):
    with pytest.raises(ValueError, match="provider_deadline_invalid"):
        await chain().ainvoke("synthetic", provider_deadline_seconds=deadline)


async def test_default_unbounded_call_preserves_configured_retries(monkeypatch):
    retries = []
    async def invoke(self, *args, **kwargs):
        retries.append(self.max_retries)
        return SimpleNamespace(content=CONTENT)
    monkeypatch.setattr(llm.LLMClient, "ainvoke", invoke)
    await chain().ainvoke("synthetic")
    assert retries == [2]


@pytest.mark.parametrize("semantic_valid", [True, False])
async def test_application_admits_once_and_does_not_semantically_retry(monkeypatch, semantic_valid):
    calls = []
    async def invoke(self, messages, **kwargs):
        calls.append(self.name)
        assert self.max_retries == 0
        if semantic_valid and self.name == "primary":
            await asyncio.Event().wait()
        return SimpleNamespace(content=CONTENT if semantic_valid else "broken JSON")
    monkeypatch.setattr(llm.LLMClient, "ainvoke", invoke)
    charge, refund = AsyncMock(), AsyncMock()
    monkeypatch.setattr(application, "check_and_charge_llm_budget", charge)
    monkeypatch.setattr(application, "refund_llm_budget", refund)
    monkeypatch.setattr(application, "_set_tenant_security_context", AsyncMock())
    monkeypatch.setattr(application, "_set_user_security_context", AsyncMock())
    db = SimpleNamespace(commit=AsyncMock())
    actor = ActorContext(tenant_id=UUID(int=2), actor_id=UUID(int=3), active_role="methodologist")
    body = AssignmentInterpretRequest(instruction="Assign Course to QA by20December2026", timezone_name="Asia/Almaty")
    monkeypatch.setattr(application, "INTENT_PROVIDER_DEADLINE_SECONDS", 0.01, raising=False)
    resolver = AsyncMock(return_value=chain())
    result = await application.interpret_assignment(db, actor, body, provider_resolver=resolver,
                                                  now=datetime(2026, 10, 15, tzinfo=UTC))
    charge.assert_awaited_once()
    resolver.assert_awaited_once()
    db.commit.assert_awaited_once()
    if semantic_valid:
        assert result.state == "interpreted" and calls == ["primary", "fallback"]
        refund.assert_not_awaited()
    else:
        # Existing parser maps non-JSON prose to clarification, never a retry.
        assert result.code == "intent_clarification" and calls == ["primary"]
        refund.assert_awaited_once()


async def test_application_passes_eight_second_budget_to_actual_provider_seam(monkeypatch):
    for name in ("check_and_charge_llm_budget", "refund_llm_budget", "_set_tenant_security_context", "_set_user_security_context"):
        monkeypatch.setattr(application, name, AsyncMock())
    provider = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content=CONTENT)))
    result = await application.interpret_assignment(
        SimpleNamespace(commit=AsyncMock()),
        ActorContext(tenant_id=UUID(int=2), actor_id=UUID(int=3), active_role="methodologist"),
        AssignmentInterpretRequest(instruction="Assign Course to QA on20December2026", timezone_name="Asia/Almaty"),
        provider_resolver=AsyncMock(return_value=provider), now=datetime(2026, 10, 15, tzinfo=UTC))
    assert result.state == "interpreted"
    assert provider.ainvoke.call_args.kwargs == {"provider_deadline_seconds": 8}


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("single_provider", [False, True])
async def test_actual_http_retryable_errors_fail_over_once_without_sleep(monkeypatch, status, single_provider):
    original = chain()
    if single_provider:
        original = llm.ResilientLLMClient([original._clients[0].config], temperature=0, max_tokens=1200)
    calls = []
    class Transport:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, url, *, json, headers):
            calls.append(url)
            assert headers == {"Authorization": "Bearer synthetic"}
            assert json["temperature"] == 0 and json["max_tokens"] == 1200
            assert json["model"] == ("first" if "primary" in url else "second")
            return httpx.Response(status if "primary" in url else 200,
                request=httpx.Request("POST", url), headers={"retry-after": "90"},
                json={"choices": [{"message": {"content": CONTENT}}]})
    monkeypatch.setattr(llm.httpx, "AsyncClient", Transport)
    sleep = AsyncMock(side_effect=AssertionError("Bounded attempt must not sleep/retry"))
    monkeypatch.setattr(llm.asyncio, "sleep", sleep)
    if single_provider:
        with pytest.raises(llm.AllProvidersFailedError):
            await original.ainvoke("synthetic", provider_deadline_seconds=0.1)
        assert calls == ["https://primary.invalid/chat/completions"]
    else:
        response = await original.ainvoke("synthetic", provider_deadline_seconds=0.1)
        assert response.content == CONTENT
        assert calls == ["https://primary.invalid/chat/completions", "https://fallback.invalid/chat/completions"]
    sleep.assert_not_awaited()


async def test_bounded_request_preserves_provider_payload_and_format_adaptation(monkeypatch):
    cfg = llm.LLMProviderConfig("deepseek", "https://primary.invalid", "synthetic", "first", timeout=120,
                                max_retries=2, extra_body={"thinking": {"type": "disabled"}})
    original = llm.ResilientLLMClient([cfg], temperature=0.25, max_tokens=1200)
    seen = []
    async def request(self, payload):
        assert self.config == llm.replace(cfg, max_retries=0)
        assert self.max_retries == 0
        seen.append(payload)
        return {"choices": [{"message": {"content": CONTENT}}]}
    monkeypatch.setattr(llm.LLMClient, "_request", request)
    await original.ainvoke("synthetic", config={"max_tokens": 1000},
        response_format={"type": "json_schema", "json_schema": {"name": "example"}}, provider_deadline_seconds=0.1)
    assert seen == [{"model": "first", "messages": [{"role": "user", "content": "synthetic"}],
                     "temperature": 0.25, "max_tokens": 1000, "thinking": {"type": "disabled"},
                     "response_format": {"type": "json_object"}}]
    assert original._clients[0].config is cfg and original._clients[0].max_retries == 2
