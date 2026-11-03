import base64
import json
from uuid import UUID

import httpx
import pytest

from app.modules.ai.direct_luna_responses_client import DirectLunaResponsesClient
from app.modules.ai.v3.batched_review import BatchedReview
from app.modules.ai.v3.engine import V3GenerationPipeline
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
from app.modules.ai.v3.pending_stage_transactions import has_pending
from app.modules.ai.v3.stage_checkpoint import stage_once
from app.modules.ai.v3.typed_review_buckets import BUCKETS
from tests.unit.test_v3_direct_bucket_checkpoint import answer_review, direct_setup, lesson_review, response_body


@pytest.mark.asyncio
@pytest.mark.parametrize('wrong', [True, False])
async def test_v4_cache_miss_uses_owned_journal_and_cold_replay(monkeypatch, wrong):
    fake, journal, client, _plan, _validate = direct_setup()
    requests = []
    bodies = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith('input_tokens'):
            return httpx.Response(200, stream=httpx.ByteStream(b'{"object":"response.input_tokens","input_tokens":12}'))
        payload = json.loads(request.content)
        batch = json.loads(payload['input'][-1]['content'])
        item = batch['items'][0]
        response = {bucket: [] for bucket in BUCKETS.values()}
        response['answer_reviews'] = [{'id': item['id'], 'review': lesson_review() if wrong else answer_review()}]
        raw = response_body(response)
        bodies.append(raw)
        return httpx.Response(200, stream=httpx.ByteStream(raw))
    real = httpx.AsyncClient
    monkeypatch.setattr('app.modules.ai.direct_luna_responses_client.httpx.AsyncClient',
                        lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    async def forbidden(*_args):
        raise AssertionError('untyped_fallback_called')
    async def cold():
        cold_journal = PendingStageJournal(journal.tenant_id, journal.user_id, journal.job_id,
                                           journal.sessions, verify_source=journal.verify_source)
        cold_journal.repository = journal.repository
        cold_journal._lock_delivery = journal._lock_delivery
        cold_journal._owned_key = journal._owned_key
        cold_journal.read_owned_value_in_session = journal.read_owned_value_in_session
        cold_client = DirectLunaResponsesClient(api_key='synthetic', tenant_id=UUID(journal.tenant_id),
                                                user_id=journal.user_id, job_id=journal.job_id)
        async def callback(messages, fmt):
            return await stage_once(cold_journal, stage='review', group_id='batched-review:fixture', source_sha256='b' * 64,
                route_fingerprint=cold_client.cache_fingerprint(), messages=messages, response_format=fmt,
                direct_client=cold_client, direct_max_output_tokens=128, invoke=forbidden)
        cache = await BatchedReview.prime([], callback, typed_buckets=True, typed_fallback=True)
        proxy = cache.wrap(V3GenerationPipeline(forbidden, scoped_revision=True, explanation_consistency=True))
        return await proxy.review_answer('s', 'q', 'answer', ['source'])
    if wrong:
        with pytest.raises(ExtractionOutcomeUnknownError):
            await cold()
        assert has_pending(fake.job.result)
        receipts = [value for value in fake.values.values()
                    if isinstance(value, dict) and value.get('configured_model') == 'gpt-6-luna']
        assert len(receipts) == 1 and base64.b64decode(receipts[0]['raw_base64']) == bodies[0]
        with pytest.raises(ExtractionOutcomeUnknownError):
            await cold()
    else:
        assert await cold() == answer_review()
        assert await cold() == answer_review()
        assert not has_pending(fake.job.result)
    assert len(requests) == 2
