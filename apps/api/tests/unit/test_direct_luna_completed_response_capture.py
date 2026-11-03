import base64
import hashlib
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.modules.ai.direct_luna_responses_client import DirectLunaResponsesClient, ResponsesResult
from app.modules.ai.managed_response_rejection import ManagedResponsesResult


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['owned', 'unowned', 'echo'])
async def test_success_capture_exact_wire_and_scope(monkeypatch, caplog, mode):
    tenant, user, job = uuid4(), uuid4(), str(uuid4())
    key = 'synthetic-private-token'
    client = DirectLunaResponsesClient(api_key=key, tenant_id=tenant, user_id=user, job_id=job)
    text = key if mode == 'echo' else 'synthetic payload'
    raw = json.dumps({'model': 'gpt-6-luna', 'status': 'completed',
        'output': [{'type': 'message', 'role': 'assistant', 'status': 'completed',
                    'content': [{'type': 'output_text', 'text': json.dumps({'text': text})}]}],
        'usage': {'input_tokens': 12, 'output_tokens': 8}}, ensure_ascii=False, indent=2).encode()
    requests = []
    class Stream(httpx.AsyncByteStream):
        def __init__(self, body): self.body = body
        async def __aiter__(self): yield self.body
    def handler(request):
        requests.append(request)
        body = json.dumps({'object': 'response.input_tokens', 'input_tokens': 12}).encode() if request.url.path.endswith('input_tokens') else raw
        return httpx.Response(200, stream=Stream(body))
    real = httpx.AsyncClient
    monkeypatch.setattr('app.modules.ai.direct_luna_responses_client.httpx.AsyncClient',
                        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    checkpoint = AsyncMock(return_value=True)
    capability = await client.prepare([{'role': 'user', 'content': 'source'}], max_output_tokens=100,
                                      ownership_checkpoint=checkpoint)
    stage = None if mode == 'unowned' else 'a' * 64
    result = await client.invoke(capability, tenant_id=tenant, user_id=user, job_id=job,
                                 ownership_checkpoint=checkpoint, stage_id=stage)
    assert result.content == {'text': text} and len(requests) == 2
    assert key not in repr(result) and key not in caplog.text
    if mode != 'owned':
        assert type(result) is ResponsesResult
        return
    assert isinstance(result, ManagedResponsesResult)
    rejection = result.rejection_for('stage_validation', ValueError('synthetic'))
    assert rejection is not None and key not in repr(rejection)
    receipt = rejection.checked_receipt(tenant_id=str(tenant), user_id=user, job_id=job, stage=stage,
                                        route_fingerprint=client.cache_fingerprint())
    assert base64.b64decode(receipt['raw_base64'], validate=True) == raw
    assert receipt['wire_request_sha256'] == hashlib.sha256(requests[1].content).hexdigest()
    assert receipt['configured_model'] == 'gpt-6-luna'
    with pytest.raises(AttributeError):
        rejection._model = 'other'
    with pytest.raises(ValueError):
        rejection.checked_receipt(tenant_id=str(uuid4()), user_id=user, job_id=job, stage=stage,
                                  route_fingerprint=client.cache_fingerprint())
    with pytest.raises(ValueError):
        rejection.checked_receipt(tenant_id=str(tenant), user_id=user, job_id=job, stage=stage,
                                  route_fingerprint='b' * 64)
