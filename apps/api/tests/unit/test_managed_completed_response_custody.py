import base64
import json
from uuid import UUID, uuid4

import httpx
import pytest

from app.modules.ai.managed_luna_client import ManagedLunaClient
from app.modules.ai.v3.direct_luna_owned_stage import run_direct_owned_stage
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError, _validate_response
from app.modules.ai.v3.managed_rejection_quarantine import KEY, private_key
from app.modules.ai.v3.pending_stage_transactions import has_pending
from app.modules.ai.v3.stage_checkpoint import _digest
from tests.unit.test_direct_luna_owned_stage import options, setup


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['validation', 'finalize', 'source', 'owner', 'success'])
async def test_completed_response_private_custody(monkeypatch, caplog, case):
    fake, journal, _, plan, validate = setup()
    fake.job_id = journal.job_id = str(uuid4())
    plan['job_id'] = journal.job_id
    client = ManagedLunaClient(base_url='http://127.0.0.1:18999/v1', api_key='private-credential',
        tenant_id=UUID(journal.tenant_id), user_id=journal.user_id, job_id=journal.job_id, credential_revision='test')
    plan['route_fingerprint'] = client.cache_fingerprint()
    returned = False
    async def verify(_session, _job, _plan):
        return not (returned and case == 'source')
    journal.verify_source = verify
    rule = {'rule_id': 'r1', 'statement': 'synthetic', 'timing': ['invalid'] if case != 'success' else 'now'}
    raw = json.dumps({'model': 'gpt-5.6-luna', 'choices': [{'message': {'content': json.dumps({'rules': [rule]})}}],
        'usage': {'prompt_tokens': 12, 'completion_tokens': 8}}).encode()
    requests = []
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield raw
    def handler(request):
        nonlocal returned
        returned = True
        requests.append(request)
        if case == 'owner':
            fake.job.user_id = uuid4()
        return httpx.Response(200, stream=Stream())
    real = httpx.AsyncClient
    monkeypatch.setattr('app.modules.ai.managed_luna_client.httpx.AsyncClient',
        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    kwargs = options(journal, client, plan, validate)
    kwargs['validate_response'] = (lambda value: value) if case == 'finalize' else _validate_response
    if case == 'finalize':
        def invalid(_value):
            raise ValueError('synthetic-finalize')
        kwargs['validate_value'] = invalid
    if case == 'success':
        assert (await run_direct_owned_stage(**kwargs))['rules'][0]['timing'] == 'now'
        assert KEY not in fake.job.result
    else:
        with pytest.raises(ExtractionOutcomeUnknownError):
            await run_direct_owned_stage(**kwargs)
        assert has_pending(fake.job.result)
        if case in {'validation', 'finalize'}:
            reference = fake.job.result[KEY]['entries'][_digest(plan)]
            assert 'raw_base64' not in json.dumps(fake.job.result)
            receipt = fake.values[private_key(_digest(plan))]
            assert reference['checkpoint_key'] == private_key(_digest(plan))
            assert base64.b64decode(receipt['raw_base64'], validate=True) == raw
            assert receipt['phase'] == ('stage_finalize' if case == 'finalize' else 'stage_validation')
            assert receipt['accepted'] is False
        else:
            assert KEY not in fake.job.result
        with pytest.raises(ExtractionOutcomeUnknownError):
            await run_direct_owned_stage(**kwargs)
    assert len(requests) == 1
    assert 'private-credential' not in repr(client) and 'private-credential' not in caplog.text
