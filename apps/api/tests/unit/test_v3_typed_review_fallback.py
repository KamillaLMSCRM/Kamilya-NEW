import asyncio
import json

import pytest

from app.modules.ai.v3.batched_review import BatchedReview
from app.modules.ai.v3.engine import V3GenerationPipeline
from app.modules.ai.v3.typed_review_buckets import BUCKETS
from tests.unit.test_v3_batch_review_response_schema import reviews
from tests.unit.test_v3_review_work_items import fixture


@pytest.mark.asyncio
async def test_v4_every_miss_typed_memoized_and_blind_separated():
    lesson, rule, _ = fixture()
    calls = []
    methods = list(BUCKETS)
    async def invoke(messages, fmt):
        payload = json.loads(messages[1]['content'])
        calls.append((payload, fmt))
        result = {bucket: [] for bucket in BUCKETS.values()}
        for item in payload['items']:
            result[BUCKETS[item['method']]].append({'id': item['id'], 'review': reviews()[methods.index(item['method'])]})
        return result
    cache = await BatchedReview.prime([], invoke, typed_buckets=True, typed_fallback=True)
    async def forbidden(*_args):
        raise AssertionError('raw_fallback_called')
    proxy = cache.wrap(V3GenerationPipeline(forbidden, scoped_revision=True, explanation_consistency=True))
    inputs = [('review_lesson', (lesson, [rule], ['source']), {}),
              ('review_answer', ('s', 'q', 'answer', ['source']), {}),
              ('review_answer', ('s', 'q', 'prose', ['source']), {'source_prose': True}),
              ('review_question_options', ('s', 'q', ['x', 'y'], ['source']), {}),
              ('review_question_compatibility', ('s', 'q', ['x', 'y'], ['source']), {'consistency_feedback': 'recheck'}),
              ('review_answer_completeness', ('s', 'q', 'answer', ['source']), {'explanation': 'secret', 'options': ['x', 'y']})]
    for name, args, kwargs in inputs:
        first = await getattr(proxy, name)(*args, **kwargs)
        first['mutated'] = True
        assert 'mutated' not in await getattr(proxy, name)(*args, **kwargs)
    assert len(calls) == len(inputs)
    assert all(fmt['json_schema']['name'] == 'v3_batch_review_v2' for _, fmt in calls)
    for payload, _ in calls:
        if payload['items'][0]['method'].startswith('review_question'):
            assert 'secret' not in json.dumps(payload) and 'is_correct' not in json.dumps(payload)
    assert await proxy.review_question_options('s', 'changed', ['x', 'y'], ['source']) == reviews()[2]
    assert len(calls) == len(inputs) + 1
    with pytest.raises((TypeError, ValueError)):
        await proxy.review_question_options('s')
    assert len(calls) == len(inputs) + 1


@pytest.mark.asyncio
async def test_v4_wrong_bucket_held_without_raw_fallback_or_memoization():
    calls = []
    async def bad(messages, _fmt):
        calls.append(1)
        payload = json.loads(messages[1]['content'])
        result = {bucket: [] for bucket in BUCKETS.values()}
        item = payload['items'][0]
        result['answer_reviews'] = [{'id': item['id'], 'review': reviews()[0]}]
        return result
    async def forbidden(*_args):
        raise AssertionError('raw_fallback_called')
    cache = await BatchedReview.prime([], bad, typed_buckets=True, typed_fallback=True)
    proxy = cache.wrap(V3GenerationPipeline(forbidden, scoped_revision=True, explanation_consistency=True))
    with pytest.raises(ValueError):
        await proxy.review_answer('s', 'q', 'a', ['source'])
    assert calls == [1]


@pytest.mark.asyncio
async def test_concurrent_identical_misses_issue_one_invoke_and_return_isolated_copies():
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def invoke(messages, _fmt):
        calls.append(1)
        entered.set()
        await release.wait()
        item = json.loads(messages[1]['content'])['items'][0]
        result = {bucket: [] for bucket in BUCKETS.values()}
        result['option_reviews'] = [{'id': item['id'], 'review': reviews()[2]}]
        return result
    cache = await BatchedReview.prime([], invoke, typed_buckets=True, typed_fallback=True)
    proxy = cache.wrap(V3GenerationPipeline(invoke, scoped_revision=True, explanation_consistency=True))
    first = asyncio.create_task(proxy.review_question_options('s', 'q', ['a'], ['source']))
    await entered.wait()
    second = asyncio.create_task(proxy.review_question_options('s', 'q', ['a'], ['source']))
    await asyncio.sleep(0)
    release.set()
    left, right = await asyncio.gather(first, second)
    left['options'].clear()
    assert right == reviews()[2] and calls == [1]
