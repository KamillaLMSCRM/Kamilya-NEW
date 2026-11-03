import asyncio
import json
import socket
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.modules.ai.managed_luna_client import ManagedLunaClient, ManagedLunaError


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("network denied")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)


@pytest.fixture
def setup(monkeypatch):
    requests = []
    state = {"status": 200, "body": {"model": "gpt-5.6-luna", "choices": [{"message": {"content": '{"ok":true}'}}],
             "usage": {"prompt_tokens": 8, "completion_tokens": 2}}}
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield json.dumps(state["body"]).encode()
    def handler(request):
        requests.append(request)
        return httpx.Response(state["status"], stream=Stream())
    real = httpx.AsyncClient
    monkeypatch.setattr("app.modules.ai.managed_luna_client.httpx.AsyncClient",
                        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    tenant, user = uuid4(), uuid4()
    client = ManagedLunaClient(base_url="http://10.77.77.2:18999/v1", api_key="private-secret",
                               tenant_id=tenant, user_id=user, job_id="job", credential_revision="r1")
    return client, tenant, user, state, requests


@pytest.mark.asyncio
async def test_preparation_is_local_one_use_and_freezes_payload(setup):
    client, tenant, user, _, requests = setup
    messages = [{"role": "user", "content": "synthetic"}]
    token = await client.prepare(messages, max_output_tokens=8, ownership_checkpoint=AsyncMock(return_value=True))
    messages[0]["content"] = "changed"
    assert not requests
    result = await client.invoke(token, tenant_id=tenant, user_id=user, job_id="job",
                                 ownership_checkpoint=AsyncMock(return_value=True), stage_id="a" * 64)
    payload = json.loads(requests[0].content)
    assert set(payload) == {"model", "messages", "temperature", "max_tokens", "response_format"}
    assert payload["messages"][0]["content"] == "synthetic" and "reasoning_effort" not in payload
    assert result.model == "gpt-5.6-luna" and result.content == {"ok": True}
    assert result.usage.input_tokens == 8 and result.usage.output_tokens == 2
    assert result.usage.cached_input_tokens is None and result.usage.reasoning_tokens is None
    with pytest.raises(ManagedLunaError):
        await client.invoke(token, tenant_id=tenant, user_id=user, job_id="job", ownership_checkpoint=AsyncMock(return_value=True))
    assert len(requests) == 1 and "private-secret" not in repr(client)


@pytest.mark.asyncio
async def test_foreign_scope_discard_close_and_cancel_deny_send(setup):
    client, tenant, user, _, requests = setup
    async def prepare():
        return await client.prepare([{"role": "user", "content": "x"}], max_output_tokens=8,
                                    ownership_checkpoint=AsyncMock(return_value=True))
    token = await prepare()
    with pytest.raises(ManagedLunaError):
        await client.invoke(token, tenant_id=tenant, user_id=uuid4(), job_id="job", ownership_checkpoint=AsyncMock(return_value=True))
    token = await prepare()
    client.discard(token)
    with pytest.raises(ManagedLunaError):
        await client.invoke(token, tenant_id=tenant, user_id=user, job_id="job", ownership_checkpoint=AsyncMock(return_value=True))
    with pytest.raises(asyncio.CancelledError):
        await client.prepare([{"role": "user", "content": "x"}], max_output_tokens=8,
                             ownership_checkpoint=AsyncMock(side_effect=asyncio.CancelledError()))
    token = await prepare()
    client.close()
    with pytest.raises(ManagedLunaError):
        await client.invoke(token, tenant_id=tenant, user_id=user, job_id="job", ownership_checkpoint=AsyncMock(return_value=True))
    assert not requests


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["status", "model", "duplicate", "overlimit", "usage", "refusal"])
async def test_bad_response_fails_without_retry_or_secret(setup, failure):
    client, tenant, user, state, requests = setup
    if failure == "status":
        state["status"] = 500
    if failure == "model":
        state["body"]["model"] = "other"
    if failure == "duplicate":
        state["body"]["choices"].append(state["body"]["choices"][0])
    if failure == "overlimit":
        state["body"]["usage"]["completion_tokens"] = 9
    if failure == "usage":
        state["body"]["usage"]["prompt_tokens"] = True
    if failure == "refusal":
        state["body"]["choices"][0]["message"]["content"] = "not json"
    token = await client.prepare([{"role": "user", "content": "x"}], max_output_tokens=8,
                                 ownership_checkpoint=AsyncMock(return_value=True))
    with pytest.raises(ManagedLunaError) as error:
        await client.invoke(token, tenant_id=tenant, user_id=user, job_id="job", ownership_checkpoint=AsyncMock(return_value=True))
    assert len(requests) == 1 and "private-secret" not in str(error.value)


def test_private_url_policy_and_fingerprint():
    tenant, user = uuid4(), uuid4()
    def make(url, token="a", revision="r1"):
        return ManagedLunaClient(base_url=url, api_key=token, tenant_id=tenant, user_id=user,
                                 job_id="job", credential_revision=revision)
    for url in ("https://example.com/v1", "http://10.77.77.2/v1?x=1", "http://x@10.77.77.2/v1"):
        with pytest.raises(ValueError):
            make(url)
    client = make("http://10.77.77.2:18999/v1")
    assert client.cache_fingerprint() != make("http://10.77.77.2:18999/v1", revision="r2").cache_fingerprint()
    assert client.cache_fingerprint() != make("http://10.77.77.2:18999/v1", token="b").cache_fingerprint()


@pytest.mark.asyncio
async def test_oversized_and_injected_messages_block_before_send(setup):
    client, _, _, _, requests = setup
    for messages in ([{"role": "user", "content": "x", "reasoning_effort": "medium"}],
                     [{"role": "user", "content": "x" * 524288}]):
        with pytest.raises(ValueError):
            await client.prepare(messages, max_output_tokens=8, ownership_checkpoint=AsyncMock(return_value=True))
    assert not requests


@pytest.mark.asyncio
async def test_http_cancellation_propagates_without_second_call(monkeypatch):
    entered, requests = asyncio.Event(), []
    async def handler(request):
        requests.append(request.url.path)
        entered.set()
        await asyncio.Event().wait()
    real = httpx.AsyncClient
    monkeypatch.setattr("app.modules.ai.managed_luna_client.httpx.AsyncClient",
                        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    tenant, user = uuid4(), uuid4()
    client = ManagedLunaClient(base_url="http://10.77.77.2:18999/v1", api_key="private-secret",
                              tenant_id=tenant, user_id=user, job_id="job", credential_revision="r1")
    token = await client.prepare([{"role": "user", "content": "x"}], max_output_tokens=8,
                                 ownership_checkpoint=AsyncMock(return_value=True))
    task = asyncio.create_task(client.invoke(token, tenant_id=tenant, user_id=user, job_id="job",
                                              ownership_checkpoint=AsyncMock(return_value=True)))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ManagedLunaError):
        await client.invoke(token, tenant_id=tenant, user_id=user, job_id="job", ownership_checkpoint=AsyncMock(return_value=True))
    assert requests == ["/v1/chat/completions"]


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["not_configured", "authorization_required", "unavailable", "protocol_mismatch", "busy", "invalid_input", "timeout", "output_limit", "tool_use_rejected", "secret-unrecognized"])
async def test_error_diagnostics_allowlist_without_body_or_retry(setup, caplog, code):
    import logging
    client, tenant, user, state, requests = setup
    state["status"] = 503
    state["body"] = {"error": code, "private": "sensitive-source"}
    caplog.set_level(logging.INFO, logger="app.modules.ai.managed_luna_client")
    token = await client.prepare([{"role": "user", "content": "sensitive-source"}], max_output_tokens=8, ownership_checkpoint=AsyncMock(return_value=True))
    with pytest.raises(ManagedLunaError):
        await client.invoke(token, tenant_id=tenant, user_id=user, job_id="job", stage_id="a" * 64, ownership_checkpoint=AsyncMock(return_value=True))
    assert len(requests) == 1
    assert "category=" + ("http_error" if code == "secret-unrecognized" else code) in caplog.text
    assert "sensitive-source" not in caplog.text and "private-secret" not in caplog.text and "secret-unrecognized" not in caplog.text


@pytest.mark.asyncio
async def test_logging_failure_does_not_change_success(setup, monkeypatch):
    client, tenant, user, _, requests = setup
    monkeypatch.setattr("app.modules.ai.managed_luna_client.logger.info", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("private")))
    token = await client.prepare([{"role": "user", "content": "x"}], max_output_tokens=8, ownership_checkpoint=AsyncMock(return_value=True))
    result = await client.invoke(token, tenant_id=tenant, user_id=user, job_id="job", ownership_checkpoint=AsyncMock(return_value=True))
    assert result.content == {"ok": True} and len(requests) == 1


def test_diagnostic_bounds_untrusted_numeric_fields(caplog):
    import logging

    from app.modules.ai.managed_luna_client import _diagnostic
    caplog.set_level(logging.INFO, logger="app.modules.ai.managed_luna_client")
    giant = 10**100
    _diagnostic("response", "not-a-uuid-secret", "a" * 64, 0.0, 999, "validated", giant, True)
    assert "status=None" in caplog.text
    assert "input_tokens=None" in caplog.text and "output_tokens=None" in caplog.text
    assert str(giant) not in caplog.text and "not-a-uuid-secret" not in caplog.text
