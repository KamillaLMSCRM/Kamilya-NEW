import asyncio
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.modules.ai.direct_luna_responses_client import DirectLunaResponsesClient
from app.modules.ai.v3.cooperative_budget import PreclaimYieldError
from app.modules.ai.v3.direct_luna_owned_stage import run_direct_owned_stage
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
from app.modules.ai.v3.pending_stage_transactions import has_pending
from app.modules.ai.v3.stage_checkpoint import _digest
from tests.unit.test_owned_stage_inspection import setup_journal


def setup():
    fake = setup_journal()
    tenant, user = uuid4(), uuid4()
    fake.tenant_id = str(tenant)
    fake.job.user_id = user
    async def verify(_session, _job, _plan): return True
    journal = PendingStageJournal(str(tenant), user, fake.job_id, fake.sessions, verify_source=verify)
    journal.repository = fake
    journal._lock_delivery = fake._lock_delivery
    journal._owned_key = fake._owned_key
    journal.read_owned_value_in_session = fake.read_owned_value_in_session
    client = DirectLunaResponsesClient(api_key='synthetic', tenant_id=tenant, user_id=user, job_id=fake.job_id)
    plan = {'tenant_id': str(tenant), 'job_id': fake.job_id, 'stage': 'synthetic'}
    def validate(value):
        if value.get('identity') != _digest(plan) or value.get('response_sha256') != _digest(value.get('response')):
            raise ValueError('invalid')
        return value['response']
    return fake, journal, client, plan, validate


def options(journal, client, plan, validate):
    return dict(journal=journal, client=client, plan=plan, result_key='result', claim_key='claim',
        validate_value=validate, validate_response=lambda value: value, messages=[{'role':'user','content':'synthetic'}], max_output_tokens=128)


@pytest.mark.asyncio
async def test_count_before_claim_and_completed_replay_has_no_external_call(monkeypatch):
    fake, journal, client, plan, validate = setup()
    cap = object()
    async def prepare(*_args, ownership_checkpoint, **_kwargs):
        assert not fake.plans and await ownership_checkpoint() is True
        return cap
    async def invoke(value, *, ownership_checkpoint, **_kwargs):
        assert value is cap and has_pending(fake.job.result) and await ownership_checkpoint() is True
        return SimpleNamespace(content={'ok': True}, model='gpt-6-luna',
            usage=SimpleNamespace(input_tokens=12, output_tokens=None, cached_input_tokens=0, reasoning_tokens=None))
    prepare_mock, invoke_mock = AsyncMock(side_effect=prepare), AsyncMock(side_effect=invoke)
    monkeypatch.setattr(client, 'prepare', prepare_mock)
    monkeypatch.setattr(client, 'invoke', invoke_mock)
    assert await run_direct_owned_stage(**options(journal, client, plan, validate)) == {'ok': True}
    assert await run_direct_owned_stage(**options(journal, client, plan, validate)) == {'ok': True}
    prepare_mock.assert_awaited_once()
    invoke_mock.assert_awaited_once()
    stored = fake.values['result']
    assert stored['direct_metadata']['usage'] == {'input_tokens': 12, 'output_tokens': None,
        'cached_input_tokens': 0, 'reasoning_tokens': None}
    stored['direct_metadata']['usage']['input_tokens'] = 999
    with pytest.raises(ExtractionOutcomeUnknownError, match='v3_inspection_unverified'):
        await run_direct_owned_stage(**options(journal, client, plan, validate))
    invoke_mock.assert_awaited_once()


@pytest.mark.parametrize('value', [True, -1, '12'])
def test_usage_metadata_rejects_malformed_counts(value):
    from app.modules.ai.v3.direct_usage_metadata import checked_metadata
    with pytest.raises(ValueError, match='direct_usage_metadata_invalid'):
        checked_metadata({'model': 'gpt-6-luna', 'usage': {'input_tokens': value, 'output_tokens': None,
            'cached_input_tokens': None, 'reasoning_tokens': None}})


def test_legacy_result_metadata_absent_remains_valid():
    from app.modules.ai.v3.stage_checkpoint import _validate_direct_metadata
    _validate_direct_metadata({'identity': 'legacy', 'response': {'ok': True}})


@pytest.mark.parametrize('usage', [
    {'input_tokens': 1, 'output_tokens': None, 'cached_input_tokens': 2, 'reasoning_tokens': None},
    {'input_tokens': None, 'output_tokens': 1, 'cached_input_tokens': None, 'reasoning_tokens': 2},
])
def test_usage_metadata_normalizes_subcounts_exceeding_totals(usage):
    from app.modules.ai.v3.direct_usage_metadata import checked_metadata
    result = checked_metadata({'model': 'gpt-6-luna', 'usage': usage})['usage']
    assert result['input_tokens'] == usage['input_tokens'] and result['output_tokens'] == usage['output_tokens']
    assert result['cached_input_tokens'] is None and result['reasoning_tokens'] is None


@pytest.mark.asyncio
async def test_inconsistent_usage_is_unknown_and_response_replays_without_retry(monkeypatch):
    fake, journal, client, plan, validate = setup()
    prepare = AsyncMock(return_value=object())
    invoke = AsyncMock(return_value=SimpleNamespace(content={'ok': True}, model='gpt-6-luna',
        usage=SimpleNamespace(input_tokens=1, output_tokens=None, cached_input_tokens=2, reasoning_tokens=None)))
    monkeypatch.setattr(client, 'prepare', prepare)
    monkeypatch.setattr(client, 'invoke', invoke)
    assert await run_direct_owned_stage(**options(journal, client, plan, validate)) == {'ok': True}
    assert not has_pending(fake.job.result)
    assert fake.values['result']['direct_metadata']['usage']['input_tokens'] == 1
    assert fake.values['result']['direct_metadata']['usage']['cached_input_tokens'] is None
    assert await run_direct_owned_stage(**options(journal, client, plan, validate)) == {'ok': True}
    prepare.assert_awaited_once()
    invoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_count_failure_leaves_no_claim_or_generation(monkeypatch):
    fake, journal, client, plan, validate = setup()
    monkeypatch.setattr(client, 'prepare', AsyncMock(side_effect=ValueError('count failed')))
    invoke = AsyncMock()
    monkeypatch.setattr(client, 'invoke', invoke)
    with pytest.raises(ValueError):
        await run_direct_owned_stage(**options(journal, client, plan, validate))
    assert not fake.plans and not has_pending(fake.job.result)
    invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_client_count_wall_timeout_leaves_no_claim_or_generation(monkeypatch):
    fake, journal, client, plan, validate = setup()
    def deny(*_args, **_kwargs):
        raise AssertionError("network denied")
    monkeypatch.setattr(socket.socket, "connect", deny)
    requests = []
    async def handler(request):
        requests.append(request.url.path)
        await asyncio.Event().wait()
    real = httpx.AsyncClient
    monkeypatch.setattr("app.modules.ai.direct_luna_responses_client.COUNT_DEADLINE_SECONDS", 0.01)
    monkeypatch.setattr("app.modules.ai.direct_luna_responses_client.httpx.AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(PreclaimYieldError, match="generation_count_deadline_exhausted"):
        await run_direct_owned_stage(**options(journal, client, plan, validate))
    assert requests == ["/v1/responses/input_tokens"]
    assert not fake.plans and not has_pending(fake.job.result)


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout_type", [httpx.ConnectTimeout, httpx.ReadTimeout])
async def test_httpx_count_timeout_never_claims_or_generates(monkeypatch, timeout_type):
    fake, journal, client, plan, validate = setup()
    def deny(*_args, **_kwargs):
        raise AssertionError("network denied")
    monkeypatch.setattr(socket.socket, "connect", deny)
    requests = []
    def handler(request):
        requests.append(request.url.path)
        raise timeout_type("synthetic private detail")
    real = httpx.AsyncClient
    monkeypatch.setattr("app.modules.ai.direct_luna_responses_client.httpx.AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(PreclaimYieldError, match="generation_count_deadline_exhausted"):
        await run_direct_owned_stage(**options(journal, client, plan, validate))
    assert requests == ["/v1/responses/input_tokens"]
    assert not fake.plans and not has_pending(fake.job.result)


@pytest.mark.asyncio
async def test_cancel_after_claim_retains_unknown_and_never_repeats(monkeypatch):
    fake, journal, client, plan, validate = setup()
    prepare = AsyncMock(return_value=object())
    invoke = AsyncMock(side_effect=asyncio.CancelledError())
    monkeypatch.setattr(client, "prepare", prepare)
    monkeypatch.setattr(client, "invoke", invoke)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await run_direct_owned_stage(**options(journal, client, plan, validate))
    assert has_pending(fake.job.result)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await run_direct_owned_stage(**options(journal, client, plan, validate))
    prepare.assert_awaited_once()
    invoke.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout_type", [httpx.ConnectTimeout, httpx.ReadTimeout])
async def test_httpx_generation_timeout_keeps_hold_no_repeat(monkeypatch, timeout_type):
    fake, journal, client, plan, validate = setup()
    def deny(*_args, **_kwargs):
        raise AssertionError("network denied")
    monkeypatch.setattr(socket.socket, "connect", deny)
    requests = []
    class CountStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"object":"response.input_tokens","input_tokens":12}'
    def handler(request):
        requests.append(request.url.path)
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(200, stream=CountStream())
        raise timeout_type("synthetic private detail")
    real = httpx.AsyncClient
    monkeypatch.setattr("app.modules.ai.direct_luna_responses_client.httpx.AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(ExtractionOutcomeUnknownError):
        await run_direct_owned_stage(**options(journal, client, plan, validate))
    assert has_pending(fake.job.result)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await run_direct_owned_stage(**options(journal, client, plan, validate))
    assert requests == ["/v1/responses/input_tokens", "/v1/responses"]


@pytest.mark.asyncio
async def test_uncertain_after_claim_keeps_hold_and_no_second_count(monkeypatch):
    fake, journal, client, plan, validate = setup()
    prepare = AsyncMock(return_value=object())
    invoke = AsyncMock(side_effect=TimeoutError('synthetic'))
    monkeypatch.setattr(client, 'prepare', prepare)
    monkeypatch.setattr(client, 'invoke', invoke)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await run_direct_owned_stage(**options(journal, client, plan, validate))
    assert has_pending(fake.job.result)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await run_direct_owned_stage(**options(journal, client, plan, validate))
    prepare.assert_awaited_once()
    invoke.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['stage', 'extraction'])
async def test_real_checkpoint_direct_path_counts_before_claim_and_cold_replays(monkeypatch, kind):
    import json

    from app.modules.ai.v3.extraction_checkpoint import extract_once
    from app.modules.ai.v3.stage_checkpoint import stage_once
    from tests.unit.test_v3_extraction_checkpoint import identity
    fake, journal, client, _plan, _validate = setup()
    calls = []
    response = {'ok': True} if kind == 'stage' else {'rules': []}
    async def post(endpoint, _payload, **_kwargs):
        calls.append(endpoint)
        if endpoint.endswith('input_tokens'):
            assert not has_pending(fake.job.result)
            return json.dumps({'object': 'response.input_tokens', 'input_tokens': 12})
        assert has_pending(fake.job.result)
        return json.dumps({'model':'gpt-6-luna','status':'completed','output':[{'type':'message','role':'assistant','status':'completed','content':[{'type':'output_text','text':json.dumps(response)}]}]})
    monkeypatch.setattr(client, '_post', post)
    async def forbidden(): raise AssertionError('legacy invoker forbidden')
    messages = [{'role':'user','content':'synthetic'}]
    if kind == 'stage':
        async def run():
            return await stage_once(journal, stage='lesson', group_id='part', source_sha256='a'*64,
                route_fingerprint='b'*64, messages=messages, response_format={'type':'json_object'},
                invoke=forbidden, direct_client=client, direct_max_output_tokens=128)
    else:
        ident = {**identity(), 'tenant_id':journal.tenant_id, 'job_id':journal.job_id}
        async def run():
            return await extract_once(journal, ident, forbidden, direct_client=client, direct_messages=messages,
                                      direct_max_output_tokens=128)
    assert await run() == response
    assert await run() == response
    assert len(calls) == 2 and calls[0].endswith('input_tokens') and calls[1].endswith('/responses')
