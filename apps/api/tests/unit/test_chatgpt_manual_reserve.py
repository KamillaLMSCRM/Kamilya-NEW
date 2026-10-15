"""Synthetic dormant connector contract; no DB, provider, account or inference."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.modules.admin.model_routing import chatgpt_reserve as reserve
from app.modules.admin.model_routing import service
from app.modules.admin.model_routing.catalog import DEFAULT_GENERATION_MODEL_ORDER
from app.modules.admin.model_routing.router import router
from app.modules.admin.model_routing.schemas import GenerationModelRoutingUpdate
from app.modules.ai import llm_client as llm


def settings(**changes):
    return Settings(_env_file=None, **{
        "CHATGPT_RESERVE_URL": "http://127.0.0.1:18999/v1",
        "CHATGPT_RESERVE_TOKEN": "synthetic-gateway-credential",
        "CHATGPT_RESERVE_AUTH_MODE": "codex_cli",
        "DEEPSEEK_API_KEY": "synthetic-primary",
        **changes,
    })


def row(order=None):
    return SimpleNamespace(
        ordered_model_ids=list(order or DEFAULT_GENERATION_MODEL_ORDER),
        revision=2, updated_by=None, updated_at=datetime.now(UTC),
    )


def routing_service(monkeypatch, saved=None, config=None):
    saved = saved or row()
    db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())
    monkeypatch.setattr(service.repo, "get_routing", AsyncMock(return_value=saved))
    monkeypatch.setattr(service, "get_settings", lambda: config or settings())
    monkeypatch.setattr(service, "get_active_global_key", AsyncMock(return_value=None))
    return service.GenerationModelRoutingService(db), saved, db


def transport(monkeypatch, callback):
    client = httpx.AsyncClient
    monkeypatch.setattr(reserve.httpx, "AsyncClient", lambda **kw: client(
        transport=httpx.MockTransport(callback), **kw,
    ))


def test_default_route_excludes_reserve_and_configuration_is_empty():
    assert "chatgpt_reserve" not in DEFAULT_GENERATION_MODEL_ORDER
    s = settings(CHATGPT_RESERVE_URL="", CHATGPT_RESERVE_TOKEN="", CHATGPT_RESERVE_AUTH_MODE="unconfigured")
    assert reserve.configuration_blocker(s) == "not_configured"


@pytest.mark.parametrize("url", [
    "https://api.openai.com/v1", "http://169.254.169.254/v1", "http://gateway.test/v1",
    "http://user:pass@127.0.0.1/v1", "http://127.0.0.1/v1?q=token",
    "http://127.0.0.1/v1#x", "file:///v1", "http://127.0.0.1/admin",
    "http://127.0.0.1:0/v1", "http://127.0.0.1:99999/v1",
    "http://100.64.0.1/v1", "http://[fe80::1]/v1",
])
def test_rejects_public_dns_metadata_and_unsafe_destinations(url):
    assert reserve.configuration_blocker(settings(CHATGPT_RESERVE_URL=url)) == "not_configured"


@pytest.mark.parametrize("url", ["http://10.77.77.1:18999/v1", "http://127.0.0.1", "http://[::1]/v1"])
def test_allows_server_owned_literal_private_destination(url):
    assert reserve.configuration_blocker(settings(CHATGPT_RESERVE_URL=url)) is None


async def test_status_and_unconfigured_readiness_do_not_call_gateway(monkeypatch):
    s = settings(CHATGPT_RESERVE_URL="", CHATGPT_RESERVE_TOKEN="")
    monkeypatch.setattr(reserve, "get_settings", lambda: s)
    gateway = AsyncMock(side_effect=AssertionError("unexpected network"))
    monkeypatch.setattr(reserve.httpx, "AsyncClient", gateway)
    svc, saved, db = routing_service(monkeypatch, config=s)
    result = await svc.get()
    item = next(item for item in result.models if item.id == "chatgpt_reserve")
    assert not item.is_enabled and not item.is_configured
    assert item.activation_blocker == "not_configured"
    assert (await reserve.check_readiness()).reason == "not_configured"
    gateway.assert_not_called()
    db.commit.assert_not_awaited()
    assert saved.ordered_model_ids == list(DEFAULT_GENERATION_MODEL_ORDER)


async def test_authorization_required_without_calling_gateway(monkeypatch):
    monkeypatch.setattr(reserve, "get_settings", lambda: settings(CHATGPT_RESERVE_AUTH_MODE="unconfigured"))
    gateway = AsyncMock(side_effect=AssertionError("unexpected network"))
    monkeypatch.setattr(reserve.httpx, "AsyncClient", gateway)
    result = await reserve.check_readiness()
    assert not result.ready and result.reason == "authorization_required"
    gateway.assert_not_called()


@pytest.mark.parametrize("payload,reason", [
    ({"ready": True, "model": "gpt-5.6-luna", "authorization": "codex_cli", "protocol": reserve.PROTOCOL}, "ready"),
    ({"ready": True}, "protocol_mismatch"),
    ({"ready": True, "model": "other", "authorization": "codex_cli", "protocol": reserve.PROTOCOL}, "protocol_mismatch"),
    ({"ready": True, "model": "gpt-5.6-luna", "authorization": "chatgpt", "protocol": reserve.PROTOCOL}, "protocol_mismatch"),
    ({"ready": 1, "model": "gpt-5.6-luna", "authorization": "codex_cli", "protocol": reserve.PROTOCOL}, "protocol_mismatch"),
    (["unexpected"], "protocol_mismatch"),
])
async def test_explicit_readiness_checks_protocol_without_inference(monkeypatch, payload, reason):
    monkeypatch.setattr(reserve, "get_settings", settings)
    calls = []
    def respond(request):
        calls.append(request)
        assert request.method == "GET" and request.url.path == "/v1/readiness"
        assert request.headers["authorization"] == "Bearer synthetic-gateway-credential"
        assert request.content == b""
        return httpx.Response(200, json=payload)
    transport(monkeypatch, respond)
    result = await reserve.check_readiness()
    assert result.reason == reason and result.ready == (reason == "ready")
    assert len(calls) == 1
    assert "synthetic-gateway" not in result.model_dump_json()
    assert "127.0.0.1" not in result.model_dump_json()


@pytest.mark.parametrize("status,body,reason", [
    (302, b"", "unavailable"), (401, b"secret error", "authorization_required"),
    (500, b"secret error", "unavailable"), (200, b"not-json-secret", "unavailable"),
    (200, b"x" * 8193, "protocol_mismatch"),
])
async def test_readiness_sanitizes_errors_and_bounds_response(monkeypatch, status, body, reason):
    monkeypatch.setattr(reserve, "get_settings", settings)
    transport(monkeypatch, lambda request: httpx.Response(status, content=body, headers={"Location": "https://public.test"}))
    result = await reserve.check_readiness()
    assert not result.ready and result.reason == reason
    assert "secret" not in result.model_dump_json()


async def test_readiness_timeout_has_no_retry(monkeypatch):
    monkeypatch.setattr(reserve, "get_settings", settings)
    calls = []
    def fail(request):
        calls.append(request)
        raise httpx.ConnectTimeout("secret endpoint")
    transport(monkeypatch, fail)
    assert (await reserve.check_readiness()).reason == "unavailable"
    assert len(calls) == 1


async def test_slow_stream_hits_total_wall_clock_deadline(monkeypatch):
    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"{"
            await asyncio.Event().wait()
    monkeypatch.setattr(reserve, "get_settings", settings)
    monkeypatch.setattr(reserve, "READINESS_DEADLINE_SECONDS", 0.01)
    transport(monkeypatch, lambda request: httpx.Response(200, stream=SlowStream()))
    result = await reserve.check_readiness()
    assert result.reason == "unavailable"


async def test_external_cancellation_is_not_reported_as_gateway_failure(monkeypatch):
    monkeypatch.setattr(reserve, "get_settings", settings)
    def cancel(request):
        raise asyncio.CancelledError()
    transport(monkeypatch, cancel)
    with pytest.raises(asyncio.CancelledError):
        await reserve.check_readiness()


async def test_activation_is_explicit_revision_checked_and_audited(monkeypatch):
    svc, saved, db = routing_service(monkeypatch)
    probe = AsyncMock(return_value=reserve.ChatGPTReserveReadiness(ready=True, reason="ready", checked_at=datetime.now(UTC)))
    monkeypatch.setattr(service, "check_readiness", probe)
    actor = uuid4()
    response = await svc.update(GenerationModelRoutingUpdate(
        revision=2, ordered_model_ids=["deepseek", "chatgpt_reserve", "glm53_flash"],
    ), user_id=actor)
    assert response.revision == 3 and saved.updated_by == actor
    assert saved.ordered_model_ids == ["deepseek", "chatgpt_reserve", "glm53_flash"]
    db.commit.assert_awaited_once()
    probe.assert_awaited_once()
    with pytest.raises(service.RoutingRevisionConflictError):
        await svc.update(GenerationModelRoutingUpdate(revision=2, ordered_model_ids=["deepseek"]), user_id=actor)
    assert db.commit.await_count == 1


async def test_failed_activation_preserves_saved_route(monkeypatch):
    svc, saved, db = routing_service(monkeypatch)
    original = list(saved.ordered_model_ids)
    monkeypatch.setattr(service, "check_readiness", AsyncMock(return_value=reserve.ChatGPTReserveReadiness(
        ready=False, reason="unavailable", checked_at=datetime.now(UTC),
    )))
    with pytest.raises(service.RoutingReserveNotReadyError, match="unavailable"):
        await svc.update(GenerationModelRoutingUpdate(
            revision=2, ordered_model_ids=["deepseek", "chatgpt_reserve"],
        ), user_id=uuid4())
    assert saved.ordered_model_ids == original and saved.revision == 2
    db.commit.assert_not_awaited()


async def test_disabling_needs_neither_ready_gateway_nor_primary_key(monkeypatch):
    svc, saved, db = routing_service(monkeypatch, row(["deepseek", "chatgpt_reserve", "glm53_flash"]), settings(DEEPSEEK_API_KEY=""))
    probe = AsyncMock(side_effect=AssertionError("disable must never probe"))
    monkeypatch.setattr(service, "check_readiness", probe)
    await svc.update(GenerationModelRoutingUpdate(revision=2, ordered_model_ids=["deepseek", "glm53_flash"]), user_id=uuid4())
    assert saved.ordered_model_ids == ["deepseek", "glm53_flash"]
    probe.assert_not_awaited()
    db.commit.assert_awaited_once()


async def test_runtime_off_excludes_reserve_even_when_configured(monkeypatch):
    monkeypatch.setattr(llm, "get_settings", settings)
    assert "chatgpt-reserve" not in [p.name for p in llm._generation_fallback_providers()]
    monkeypatch.setattr(llm, "resolve_runtime_generation_model_order", AsyncMock(return_value=("deepseek", "glm53_flash")))
    monkeypatch.setattr(llm, "_resolve_db_key", AsyncMock(return_value="synthetic-primary"))
    client = await llm.ResilientLLMClient.from_settings_async()
    assert client.provider_names == ["deepseek", "glm53-flash-asus"]


@pytest.mark.parametrize("reserve_status", [200, 503])
async def test_runtime_selected_reserve_uses_real_http_seam_and_falls_through(monkeypatch, reserve_status):
    monkeypatch.setattr(llm, "get_settings", settings)
    monkeypatch.setattr(llm, "resolve_runtime_generation_model_order", AsyncMock(return_value=("deepseek", "chatgpt_reserve", "glm53_flash")))
    monkeypatch.setattr(llm, "_resolve_db_key", AsyncMock(return_value="synthetic-primary"))
    client = await llm.ResilientLLMClient.from_settings_async(max_retries_per_provider=0)
    assert client.provider_names == ["deepseek", "chatgpt-reserve", "glm53-flash-asus"]
    assert client._clients[1].config.trust_env is False
    assert client._clients[1].max_retries == 0
    calls = []
    def respond(request):
        calls.append(request)
        if request.url.host == "127.0.0.1":
            return httpx.Response(reserve_status, json={"choices": [{"message": {"content": "synthetic reserve result"}}]})
        if request.url.host == "10.66.66.28":
            return httpx.Response(200, json={"choices": [{"message": {"content": "synthetic GLM result"}}]})
        return httpx.Response(503)
    transport(monkeypatch, respond)
    result = await client.ainvoke("synthetic request")
    assert result.content == ("synthetic reserve result" if reserve_status == 200 else "synthetic GLM result")
    assert len(calls) == (2 if reserve_status == 200 else 3)
    assert calls[1].url.path == "/v1/chat/completions"


def test_config_removed_does_not_invoke_or_reactivate_reserve(monkeypatch):
    monkeypatch.setattr(llm, "get_settings", lambda: settings(CHATGPT_RESERVE_TOKEN=""))
    assert llm._generation_fallback_providers(("chatgpt_reserve",)) == []


async def test_tenant_byok_never_uses_global_reserve(monkeypatch):
    from app.modules.admin.tenant_ai_providers import service as tenant_service
    override = llm.LLMProviderConfig("tenant", "https://tenant.invalid/v1", "synthetic", "model")
    monkeypatch.setattr(tenant_service, "resolve_tenant_provider", AsyncMock(return_value=override))
    global_read = AsyncMock(side_effect=AssertionError("global route is forbidden"))
    monkeypatch.setattr(llm, "resolve_runtime_generation_model_order", global_read)
    client = await llm.ResilientLLMClient.from_settings_async(tenant_id=uuid4())
    assert client.provider_names == ["tenant"]
    global_read.assert_not_awaited()


@pytest.mark.parametrize("role", ["admin", "methodologist", "student"])
async def test_non_superadmin_cannot_probe_or_change_routing(role):
    from app.core.auth import get_current_active_user
    from app.core.db import get_db
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_active_user] = lambda: SimpleNamespace(role=role, id=uuid4())
    app.dependency_overrides[get_db] = lambda: object()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        responses = [
            await client.post("/admin/model-routing/chatgpt-readiness"),
            await client.get("/admin/model-routing"),
            await client.put("/admin/model-routing", json={"revision": 2, "ordered_model_ids": ["deepseek", "chatgpt_reserve"]}),
        ]
    assert [response.status_code for response in responses] == [403, 403, 403]


def test_migration_only_expands_constraint_never_seeds_or_enables():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).parents[2] / "alembic/versions/0180_optional_chatgpt_reserve.py"
    spec = importlib.util.spec_from_file_location("reserve_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    statements = []
    module.op = SimpleNamespace(
        execute=statements.append,
        get_context=lambda: SimpleNamespace(opts={"version_table_schema": "synthetic_test"}),
    )
    module.upgrade()
    sql = " ".join(statements)
    assert module.down_revision == "0179"
    assert "BETWEEN 1 AND 4" in sql and "chatgpt_reserve" in sql
    assert "UPDATE " not in sql and "INSERT " not in sql and "POLICY" not in sql
    assert '"synthetic_test".generation_model_routing' in sql
    assert "ordered_model_ids ->> 2 <> ordered_model_ids ->> 3" in sql
