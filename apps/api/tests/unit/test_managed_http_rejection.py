import hashlib
import logging
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.modules.ai.managed_luna_client import ManagedLunaClient, ManagedLunaError, ManagedLunaHttpRejectedError


class Body(httpx.AsyncByteStream):
    def __init__(self, value):
        self.value = value

    async def __aiter__(self):
        yield self.value


async def invoke_with(monkeypatch, response, *, stage='a' * 64):
    requests = []
    async def handler(request):
        requests.append(request)
        return response
    real = httpx.AsyncClient
    monkeypatch.setattr('app.modules.ai.managed_luna_client.httpx.AsyncClient',
                        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    tenant, user = uuid4(), uuid4()
    client = ManagedLunaClient(base_url='http://10.77.77.2:18999/v1', api_key='private-secret',
                               tenant_id=tenant, user_id=user, job_id='job', credential_revision='r1')
    check = AsyncMock(return_value=True)
    cap = await client.prepare([{'role': 'user', 'content': 'private source'}], max_output_tokens=8,
                               ownership_checkpoint=check)
    wire_hash = hashlib.sha256(client._prepared[cap]).hexdigest()
    try:
        await client.invoke(cap, tenant_id=tenant, user_id=user, job_id='job', stage_id=stage,
                            ownership_checkpoint=check)
    except ManagedLunaError as error:
        return error, client, tenant, user, requests, wire_hash
    pytest.fail('expected connector failure')


@pytest.mark.asyncio
@pytest.mark.parametrize(('status', 'code'), [(503, 'capacity'), (503, 'unavailable'),
                                              (400, 'invalid_input'), (401, 'authorization_required'),
                                              (504, 'timeout')])
async def test_complete_finite_error_preserves_scoped_evidence_without_retry(monkeypatch, caplog, status, code):
    body = ('{"error":"' + code + '"}').encode()
    caplog.set_level(logging.INFO, logger='app.modules.ai.managed_luna_client')
    error, client, tenant, user, requests, wire_hash = await invoke_with(monkeypatch, httpx.Response(status, stream=Body(body)))
    assert type(error) is ManagedLunaHttpRejectedError and len(requests) == 1
    assert error.checked_receipt(tenant_id=str(tenant), user_id=user, job_id='job', stage='a' * 64) == {
        'tenant_id': str(tenant), 'user_id': str(user), 'job_id': 'job', 'stage': 'a' * 64,
        'status': status, 'code': code, 'body_sha256': hashlib.sha256(body).hexdigest(),
        'byte_count': len(body), 'wire_request_sha256': wire_hash, 'route_fingerprint': client.cache_fingerprint()}
    with pytest.raises(ValueError):
        error.checked_receipt(tenant_id=str(uuid4()), user_id=user, job_id='job', stage='a' * 64)
    with pytest.raises(ValueError):
        error.checked_receipt(tenant_id=str(tenant), user_id=user, job_id='job', stage='b' * 64)
    assert 'private-secret' not in repr(error) + caplog.text
    assert 'private source' not in repr(error) + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(('body', 'status', 'headers', 'stage'), [
    (b'{"error":"capacity",', 503, {}, 'a' * 64),
    (b'{"error":"capacity","error":"capacity"}', 503, {}, 'a' * 64),
    (b'{"error":"new-code"}', 503, {}, 'a' * 64),
    (b'{"error":"capacity","token":"private-secret"}', 503, {}, 'a' * 64),
    (b'{"error":"capacity","note":"extra"}', 503, {}, 'a' * 64),
    (b'{"error":"capacity"}' + b' ' * 1024, 503, {}, 'a' * 64),
    (b'{"error":"capacity"}', 503, {'content-encoding': 'gzip'}, 'a' * 64),
    (b'{"error":"capacity"}', 503, {'content-length': '99'}, 'a' * 64),
    (b'{"error":"capacity"}', 302, {}, 'a' * 64),
    (b'{"error":"capacity"}', 503, {}, None),
])
async def test_uncertain_http_response_is_unknown(monkeypatch, body, status, headers, stage):
    error, _, _, _, requests, _ = await invoke_with(monkeypatch,
        httpx.Response(status, headers=headers, stream=Body(body)), stage=stage)
    assert type(error) is ManagedLunaError and str(error) == 'managed_luna_outcome_unknown'
    assert len(requests) == 1 and 'private-secret' not in repr(error)


@pytest.mark.asyncio
async def test_interrupted_error_stream_cannot_be_recorded(monkeypatch):
    class Interrupted(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"error":"capacity"}'
            raise httpx.ReadError('private-secret')
    error, _, _, _, requests, _ = await invoke_with(monkeypatch, httpx.Response(503, stream=Interrupted()))
    assert type(error) is ManagedLunaError and str(error) == 'managed_luna_outcome_unknown'
    assert len(requests) == 1
