import asyncio
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.modules.ai.direct_luna_responses_client import DirectLunaResponsesClient, ResponsesClientError


@pytest.fixture
def fixture(monkeypatch):
    requests = []
    state = {"count": {"object": "response.input_tokens", "input_tokens": 12}, "status": 200,
             "output": [{"type": "message", "role": "assistant", "status": "completed",
                         "content": [{"type": "output_text", "text": '{"ok":true}'}]}]}
    class Stream(httpx.AsyncByteStream):
        def __init__(self, value):
            self.value = value
        async def __aiter__(self):
            yield json.dumps(self.value).encode()
    def handler(request):
        requests.append(request)
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(state["status"], stream=Stream(state["count"]))
        return httpx.Response(200, stream=Stream({"model": "gpt-6-luna", "status": "completed",
                                                "output": state["output"], "usage": {"input_tokens": 0}}))
    real = httpx.AsyncClient
    monkeypatch.setattr("app.modules.ai.direct_luna_responses_client.httpx.AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    tenant, user = uuid4(), uuid4()
    client = DirectLunaResponsesClient(api_key="synthetic-secret", tenant_id=tenant, user_id=user, job_id="job")
    return client, tenant, user, state, requests


@pytest.mark.asyncio
async def test_count_capability_generation_once_and_exact_input(fixture):
    client, tenant, user, _, requests = fixture
    messages = [{"role": "user", "content": "synthetic"}]
    cap = await client.prepare(messages, max_output_tokens=100, ownership_checkpoint=AsyncMock(return_value=True))
    messages[0]["content"] = "mutated"
    result = await client.invoke(cap, tenant_id=tenant, user_id=user, job_id="job", ownership_checkpoint=AsyncMock(return_value=True))
    count, generation = [json.loads(request.content) for request in requests]
    assert count == {key: value for key, value in generation.items() if key not in {"store", "max_output_tokens"}}
    assert generation["input"][1]["content"] == "synthetic" and generation["store"] is False
    assert result.content == {"ok": True} and result.usage.input_tokens == 0 and result.usage.output_tokens is None
    assert "synthetic-secret" not in repr(client) and "ok" not in repr(result)
    with pytest.raises(ResponsesClientError, match="capability_invalid"):
        await client.invoke(cap, tenant_id=tenant, user_id=user, job_id="job", ownership_checkpoint=AsyncMock(return_value=True))
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"object": "response.input_tokens", "input_tokens": True},
                                   {"object": "response.input_tokens", "input_tokens": 1050000}])
async def test_invalid_count_never_enables_generation(fixture, body):
    client, _, _, state, requests = fixture
    state["count"] = body
    with pytest.raises(ResponsesClientError, match="count_unverified") as error:
        await client.prepare([{"role": "user", "content": "synthetic"}], max_output_tokens=100, ownership_checkpoint=AsyncMock(return_value=True))
    assert error.value.__context__ is None and len(requests) == 1


@pytest.mark.asyncio
async def test_foreign_scope_and_cancel_do_not_generate(fixture):
    client, tenant, user, _, requests = fixture
    cap = await client.prepare([{"role": "user", "content": "x"}], max_output_tokens=1, ownership_checkpoint=AsyncMock(return_value=True))
    with pytest.raises(ResponsesClientError, match="capability_invalid"):
        await client.invoke(cap, tenant_id=tenant, user_id=uuid4(), job_id="job", ownership_checkpoint=AsyncMock(return_value=True))
    cap = await client.prepare([{"role": "user", "content": "x"}], max_output_tokens=1, ownership_checkpoint=AsyncMock(return_value=True))
    with pytest.raises(ResponsesClientError, match="ownership_unverified"):
        await client.invoke(cap, tenant_id=tenant, user_id=user, job_id="job", ownership_checkpoint=AsyncMock(side_effect=asyncio.CancelledError()))
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_non200_count_fails_without_generate(fixture):
    client, _, _, state, requests = fixture
    state["status"] = 401
    with pytest.raises(ResponsesClientError, match="transport_unknown"):
        await client.prepare([{"role": "user", "content": "x"}], max_output_tokens=1, ownership_checkpoint=AsyncMock(return_value=True))
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_forged_capability_and_other_client_rejected(fixture):
    client, tenant, user, _, requests = fixture
    cap = await client.prepare([{"role": "user", "content": "x"}], max_output_tokens=1, ownership_checkpoint=AsyncMock(return_value=True))
    other = DirectLunaResponsesClient(api_key="other", tenant_id=tenant, user_id=user, job_id="job")
    for candidate in (object(), cap):
        with pytest.raises(ResponsesClientError, match="capability_invalid"):
            await other.invoke(candidate, tenant_id=tenant, user_id=user, job_id="job", ownership_checkpoint=AsyncMock(return_value=True))
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_oversized_count_fails_before_generation(fixture, monkeypatch):
    client, _, _, _, requests = fixture
    monkeypatch.setattr("app.modules.ai.direct_luna_responses_client.MAX_RESPONSE_BYTES", 5)
    with pytest.raises(ResponsesClientError, match="transport_unknown"):
        await client.prepare([{"role": "user", "content": "x"}], max_output_tokens=1, ownership_checkpoint=AsyncMock(return_value=True))
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_count_timeout_sanitized_no_generation(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("synthetic-secret")
    real = httpx.AsyncClient
    monkeypatch.setattr("app.modules.ai.direct_luna_responses_client.httpx.AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    client = DirectLunaResponsesClient(api_key="synthetic-secret", tenant_id=uuid4(), user_id=uuid4(), job_id="job")
    with pytest.raises(ResponsesClientError) as error:
        await client.prepare([{"role": "user", "content": "x"}], max_output_tokens=1, ownership_checkpoint=AsyncMock(return_value=True))
    assert error.value.__context__ is None and "synthetic-secret" not in str(error.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [False, None, asyncio.CancelledError("synthetic")])
async def test_denied_or_cancelled_ownership_prevents_count(fixture, result):
    client, _, _, _, requests = fixture
    checkpoint = AsyncMock(side_effect=result) if isinstance(result, BaseException) else AsyncMock(return_value=result)
    with pytest.raises(ResponsesClientError, match="ownership_unverified"):
        await client.prepare([{"role": "user", "content": "x"}], max_output_tokens=1, ownership_checkpoint=checkpoint)
    assert not requests


@pytest.mark.asyncio
async def test_concurrent_capability_invoked_once(fixture):
    client, tenant, user, _, requests = fixture
    cap = await client.prepare([{"role": "user", "content": "x"}], max_output_tokens=1, ownership_checkpoint=AsyncMock(return_value=True))
    checkpoint = AsyncMock(return_value=True)
    async def run():
        return await client.invoke(cap, tenant_id=tenant, user_id=user, job_id="job", ownership_checkpoint=checkpoint)
    outcomes = await asyncio.gather(run(), run(), return_exceptions=True)
    assert sum(isinstance(item, ResponsesClientError) for item in outcomes) == 1
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("output", [
    [{"type": "message", "role": "assistant", "status": "completed", "content": [{"type": "refusal", "refusal": "no"}]}],
    [{"type": "function_call", "name": "x"}],
    [{"type": "message", "role": "user", "status": "completed", "content": [{"type": "output_text", "text": "{}"}]}],
    [{"type": "message", "role": "assistant", "status": "in_progress", "content": [{"type": "output_text", "text": "{}"}]}],
    [{"type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": "{}"}, {"type": "refusal"}]}],
])
async def test_refusal_tool_mixed_wrong_role_and_status_rejected(fixture, output):
    client, tenant, user, state, requests = fixture
    state["output"] = output
    cap = await client.prepare([{"role": "user", "content": "x"}], max_output_tokens=1, ownership_checkpoint=AsyncMock(return_value=True))
    with pytest.raises(ResponsesClientError, match="generation_unverified"):
        await client.invoke(cap, tenant_id=tenant, user_id=user, job_id="job", ownership_checkpoint=AsyncMock(return_value=True))
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_reasoning_item_followed_by_completed_assistant_accepted(fixture):
    client, tenant, user, state, _ = fixture
    state["output"].insert(0, {"type": "reasoning", "summary": []})
    cap = await client.prepare([{"role": "user", "content": "x"}], max_output_tokens=1, ownership_checkpoint=AsyncMock(return_value=True))
    result = await client.invoke(cap, tenant_id=tenant, user_id=user, job_id="job", ownership_checkpoint=AsyncMock(return_value=True))
    assert result.content == {"ok": True}


@pytest.mark.asyncio
async def test_discard_and_close_forget_capabilities_without_generation(fixture):
    client, tenant, user, _, requests = fixture
    cap = await client.prepare([{"role": "user", "content": "private"}], max_output_tokens=1,
                               ownership_checkpoint=AsyncMock(return_value=True))
    client.discard(cap)
    with pytest.raises(ResponsesClientError, match="capability_invalid"):
        await client.invoke(cap, tenant_id=tenant, user_id=user, job_id="job", ownership_checkpoint=AsyncMock(return_value=True))
    another = await client.prepare([{"role": "user", "content": "private"}], max_output_tokens=1,
                                   ownership_checkpoint=AsyncMock(return_value=True))
    client.close()
    with pytest.raises(ResponsesClientError, match="capability_invalid"):
        await client.invoke(another, tenant_id=tenant, user_id=user, job_id="job", ownership_checkpoint=AsyncMock(return_value=True))
    assert len(requests) == 2 and client._key == "" and not client._prepared
    with pytest.raises(ResponsesClientError, match="client_closed"):
        await client.prepare([{"role": "user", "content": "x"}], max_output_tokens=1,
                             ownership_checkpoint=AsyncMock(return_value=True))
    assert len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["count", "generation"])
async def test_close_while_ownership_callback_paused_prevents_next_post(fixture, phase):
    client, tenant, user, _, requests = fixture
    ready, release = asyncio.Event(), asyncio.Event()
    async def paused():
        ready.set()
        await release.wait()
        return True
    if phase == "generation":
        cap = await client.prepare([{"role": "user", "content": "x"}], max_output_tokens=1,
                                   ownership_checkpoint=AsyncMock(return_value=True))
        work = asyncio.create_task(client.invoke(cap, tenant_id=tenant, user_id=user, job_id="job", ownership_checkpoint=paused))
    else:
        work = asyncio.create_task(client.prepare([{"role": "user", "content": "x"}], max_output_tokens=1,
                                                  ownership_checkpoint=paused))
    await ready.wait()
    client.close()
    release.set()
    with pytest.raises(ResponsesClientError, match="client_closed"):
        await work
    assert len(requests) == (1 if phase == "generation" else 0)


@pytest.mark.asyncio
async def test_close_while_http_client_entering_stops_stream(monkeypatch):
    ready, release = asyncio.Event(), asyncio.Event()
    streams = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self):
            ready.set()
            await release.wait()
            return self
        async def __aexit__(self, *args): pass
        def stream(self, *args, **kwargs):
            streams.append(1)
            raise AssertionError("stream must not start")
    monkeypatch.setattr("app.modules.ai.direct_luna_responses_client.httpx.AsyncClient", Client)
    client = DirectLunaResponsesClient(api_key="key", tenant_id=uuid4(), user_id=uuid4(), job_id="job")
    task = asyncio.create_task(client.prepare([{"role": "user", "content": "x"}], max_output_tokens=1,
                                              ownership_checkpoint=AsyncMock(return_value=True)))
    await ready.wait()
    client.close()
    release.set()
    with pytest.raises(ResponsesClientError, match="transport_unknown"):
        await task
    assert not streams
