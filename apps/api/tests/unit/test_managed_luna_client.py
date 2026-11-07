import asyncio
import base64
import hashlib
import hmac
import json
import socket
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.modules.ai.managed_luna_client import ManagedLunaClient, ManagedLunaCompletedJsonError, ManagedLunaError


@pytest.mark.asyncio
async def test_retained_author_replay_is_one_use_and_never_posts(setup):
    from app.modules.ai.v3.practical_contract import _course_format
    from app.modules.ai.v3.response_contracts import response_contract_hash

    client, tenant, user, _, requests = setup
    fmt = _course_format(["SRC1"])
    content = {"title": "Course", "lessons": [{"id": "lesson-1", "title": "Lesson", "content": "Text",
        "questions": [{"id": "q1", "prompt": "Question?", "choices": ["A", "B", "C"],
                       "correct_index": 0, "explanation": "Because", "source_refs": ["SRC1"]}]}]}
    body = {"model": client.model, "structured_output_policy": "typed-json-object-v1",
            "response_format_sha256": response_contract_hash(fmt),
            "choices": [{"message": {"content": json.dumps(content)}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 2}}
    raw = json.dumps(body).encode()
    checkpoint = AsyncMock(return_value=True)
    async def token():
        return await client.prepare([{"role": "user", "content": "synthetic"}], max_output_tokens=8,
                                    ownership_checkpoint=checkpoint, response_format=fmt)
    cap = await token()
    receipt = {"policy": "managed-response-quarantine-v1", "accepted": False, "complete_http_response": True,
        "status": 200, "phase": "structured_shape", "stage_sha256": "a" * 64,
        "route_fingerprint": client.cache_fingerprint(), "wire_request_sha256": hashlib.sha256(client._prepared[cap]).hexdigest(),
        "raw_base64": base64.b64encode(raw).decode(), "byte_count": len(raw), "body_sha256": hashlib.sha256(raw).hexdigest()}
    result = await client.replay_completed(cap, receipt=receipt, tenant_id=tenant, user_id=user, job_id="job",
                                           stage_id="a" * 64, ownership_checkpoint=checkpoint)
    assert result.content == content and result.usage.input_tokens == 8 and not requests
    with pytest.raises(ManagedLunaError):
        await client.replay_completed(cap, receipt=receipt, tenant_id=tenant, user_id=user, job_id="job",
                                      stage_id="a" * 64, ownership_checkpoint=checkpoint)
    for field, value in (("wire_request_sha256", "0" * 64), ("body_sha256", "0" * 64), ("phase", "content_json")):
        with pytest.raises(ManagedLunaError, match="replay_unverified"):
            await client.replay_completed(await token(), receipt={**receipt, field: value}, tenant_id=tenant,
                user_id=user, job_id="job", stage_id="a" * 64, ownership_checkpoint=checkpoint)
    different_cap = await client.prepare([{"role": "user", "content": "synthetic"}], max_output_tokens=9,
                                         ownership_checkpoint=checkpoint, response_format=fmt)
    with pytest.raises(ManagedLunaError, match="replay_unverified"):
        await client.replay_completed(different_cap, receipt=receipt, tenant_id=tenant, user_id=user,
                                      job_id="job", stage_id="a" * 64, ownership_checkpoint=checkpoint)
    assert not requests


@pytest.mark.asyncio
async def test_luna6_rejection_receipt_records_actual_configured_model(setup):
    from app.modules.ai.managed_response_rejection import ManagedResponseRejectedError
    _, tenant, actor, state, _ = setup
    job_id = str(uuid4())
    client = ManagedLunaClient(base_url="http://10.77.77.2:18999/v1", api_key="private-secret",
        tenant_id=tenant, user_id=actor, job_id=job_id, credential_revision="r1", model="gpt-6-luna")
    state['body'] = {'model': 'gpt-6-luna', 'choices': [], 'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}
    checkpoint = AsyncMock(return_value=True)
    cap = await client.prepare([{'role': 'user', 'content': 'synthetic'}], max_output_tokens=8,
                               ownership_checkpoint=checkpoint)
    with pytest.raises(ManagedResponseRejectedError) as exc:
        await client.invoke(cap, tenant_id=tenant, user_id=actor, job_id=job_id,
                            ownership_checkpoint=checkpoint, stage_id='a' * 64)
    receipt = exc.value.checked_receipt(tenant_id=str(tenant), user_id=actor, job_id=job_id,
        stage='a' * 64, route_fingerprint=client.cache_fingerprint())
    assert receipt['configured_model'] == 'gpt-6-luna'


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
async def test_medium_effort_is_bound_in_fingerprint_and_wire(setup):
    low, tenant, user, _, requests = setup
    medium = ManagedLunaClient(base_url="http://10.77.77.2:18999/v1", api_key="private-secret",
        tenant_id=tenant, user_id=user, job_id="job", credential_revision="r1", reasoning_effort="medium")
    assert low.cache_fingerprint() != medium.cache_fingerprint()
    token = await medium.prepare([{"role": "user", "content": "synthetic"}], max_output_tokens=8,
                                 ownership_checkpoint=AsyncMock(return_value=True))
    await medium.invoke(token, tenant_id=tenant, user_id=user, job_id="job",
                        ownership_checkpoint=AsyncMock(return_value=True))
    assert json.loads(requests[0].content)["reasoning_effort"] == "medium"
    assert medium.generation_deadline_seconds == 60


@pytest.mark.parametrize('effort', ['high', '', None, True])
def test_invalid_reasoning_effort_rejected(effort):
    with pytest.raises(ValueError, match='managed_luna_config_invalid'):
        ManagedLunaClient(base_url='http://10.77.77.2:18999/v1', api_key='private-secret',
            tenant_id=uuid4(), user_id=uuid4(), job_id='job', credential_revision='r1', reasoning_effort=effort)


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
async def test_completed_invalid_json_is_distinct_from_unknown_transport(setup):
    client, tenant, user, state, requests = setup
    state["body"]["choices"][0]["message"]["content"] = '{"patches": ['
    checkpoint = AsyncMock(return_value=True)
    messages = [{"role": "user", "content": "Synthetic source"}]
    token = await client.prepare(messages, max_output_tokens=8, ownership_checkpoint=checkpoint)
    with pytest.raises(ManagedLunaCompletedJsonError, match="managed_luna_response_invalid"):
        await client.invoke(token, tenant_id=tenant, user_id=user, job_id="job", ownership_checkpoint=checkpoint,
                            classify_invalid_json=True)
    state["status"] = 503
    token = await client.prepare(messages, max_output_tokens=8, ownership_checkpoint=checkpoint)
    with pytest.raises(ManagedLunaError, match="managed_luna_outcome_unknown") as failure:
        await client.invoke(token, tenant_id=tenant, user_id=user, job_id="job", ownership_checkpoint=checkpoint,
                            classify_invalid_json=True)
    assert type(failure.value) is ManagedLunaError and len(requests) == 2


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


@pytest.mark.asyncio
async def test_legacy_wire_and_fingerprint_parity(setup):
    client, _, _, _, _ = setup
    messages = [{'role': 'user', 'content': 'synthetic'}]
    capability = await client.prepare(messages, max_output_tokens=8, ownership_checkpoint=AsyncMock(return_value=True))
    expected = {'model': 'gpt-5.6-luna', 'messages': messages, 'temperature': 0.2, 'max_tokens': 8,
                'response_format': {'type': 'json_object'}}
    assert client._prepared[capability] == json.dumps(expected, ensure_ascii=False, allow_nan=False,
                                                       separators=(',', ':')).encode()
    policy = ['managed-cli-v1', 'http://10.77.77.2:18999/v1/chat/completions', 'gpt-5.6-luna',
              'low', 'json-object', 60.0, 'r1']
    assert client.cache_fingerprint() == hmac.new(b'private-secret',
        json.dumps(policy, separators=(',', ':')).encode(), hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_luna6_wire_deadline_fingerprint_and_response_model(setup):
    old, tenant, user, state, requests = setup
    client = ManagedLunaClient(base_url='http://10.77.77.2:18999/v1', api_key='private-secret',
        tenant_id=tenant, user_id=user, job_id='job', credential_revision='r1', model='gpt-6-luna',
        reasoning_effort='high', deadline_seconds=300)
    assert client.generation_deadline_seconds == 300 and client.cache_fingerprint() != old.cache_fingerprint()
    async def call():
        token = await client.prepare([{'role': 'user', 'content': 'synthetic'}], max_output_tokens=8,
                                     ownership_checkpoint=AsyncMock(return_value=True))
        return await client.invoke(token, tenant_id=tenant, user_id=user, job_id='job',
                                   ownership_checkpoint=AsyncMock(return_value=True))
    with pytest.raises(ManagedLunaError, match='managed_luna_response_invalid'):
        await call()
    state['body']['model'] = 'gpt-6-luna'
    result = await call()
    assert result.model == 'gpt-6-luna'
    wire = json.loads(requests[-1].content)
    assert wire['model'] == 'gpt-6-luna' and wire['reasoning_effort'] == 'high'


@pytest.mark.parametrize(('model', 'effort', 'deadline'), [
    ('unknown', 'low', 60), ('gpt-5.6-luna', 'high', 60), ('gpt-5.6-luna', 'low', 300),
    ('gpt-6-luna', 'high', 301)])
def test_invalid_model_policy_rejected(model, effort, deadline):
    with pytest.raises(ValueError, match='managed_luna_config_invalid'):
        ManagedLunaClient(base_url='http://10.77.77.2:18999/v1', api_key='private-secret',
            tenant_id=uuid4(), user_id=uuid4(), job_id='job', credential_revision='r1', model=model,
            reasoning_effort=effort, deadline_seconds=deadline)
