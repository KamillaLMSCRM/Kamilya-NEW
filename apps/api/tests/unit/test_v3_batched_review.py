import json

import pytest

from app.modules.ai.v3.batched_review import BatchedReview
from app.modules.ai.v3.engine import V3GenerationPipeline


@pytest.mark.asyncio
async def test_blind_separation_cache_and_exact_misses():
    calls = []
    async def invoke(messages, _format):
        payload = json.loads(messages[1]['content'])
        calls.append(payload)
        return {'items': [{'id': item['id'], 'review': ({'options': []} if item['method'].startswith('review_question')
            else {'answers': [], 'explanation_review': {}})} for item in payload['items']]}
    blind = ('review_question_options', ('s', 'q', ['yes', 'no'], ['source']), {})
    keyed = ('review_answer_completeness', ('s', 'q', 'SECRET_ANSWER', ['source']),
             {'explanation': 'SECRET_EXPLANATION', 'options': ['yes', 'no']})
    cache = await BatchedReview.prime([blind, keyed], invoke)
    assert len(calls) == 2 and 'SECRET_' not in json.dumps(calls[0])
    assert len(calls[0]['sources']) == 1
    fallback = []
    async def original(messages, _format):
        fallback.append(messages)
        return {'fallback': True}
    proxy = cache.wrap(V3GenerationPipeline(original, scoped_revision=True, explanation_consistency=True))
    first = await proxy.review_question_options(*blind[1])
    first['options'].append('changed')
    assert await proxy.review_question_options(*blind[1]) == {'options': []}
    assert not fallback
    assert await proxy.review_question_options('s', 'changed', ['yes', 'no'], ['source']) == {'fallback': True}
    assert await proxy.review_question_options('s', 'q', ['no', 'yes'], ['source']) == {'fallback': True}
    assert await proxy.review_question_options('s', 'q', ['yes', 'no'], ['other']) == {'fallback': True}
    assert len(fallback) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['missing', 'duplicate', 'foreign', 'axis'])
async def test_malformed_batches_fail_closed(kind):
    async def invoke(messages, _format):
        item = json.loads(messages[1]['content'])['items'][0]
        entry = {'id': item['id'], 'review': {'options': []}}
        if kind == 'missing':
            return {'items': []}
        if kind == 'duplicate':
            return {'items': [entry, entry]}
        if kind == 'foreign':
            entry['id'] = 'foreign'
        if kind == 'axis':
            entry['review'] = {}
        return {'items': [entry]}
    with pytest.raises(ValueError):
        await BatchedReview.prime([('review_question_options', ('s', 'q', ['x'], ['source']), {})], invoke)


@pytest.mark.asyncio
async def test_exact_shared_data_and_review_drift():
    class Entity:
        def __init__(self, value): self.value = value
        def to_dict(self): return self.value.copy()
    class Lesson(Entity):
        @property
        def cases(self): return self.value['cases']
    lesson = Lesson({'content': 'SHARED_BODY', 'cases': [{'case': 'one'}], 'questions': ['parallel']})
    rule = Entity({'rule_id': 'r', 'statement': 'EXACT_RULE'})
    items = [('review_lesson', (lesson, [rule], ['source']), {}),
             ('review_lesson', (lesson, [rule], ['source']), {'partial_case': True})]
    async def invoke(messages, _format):
        payload = json.loads(messages[1]['content'])
        text = json.dumps(payload)
        assert text.count('SHARED_BODY') == 1 and text.count('EXACT_RULE') == 1
        assert 'parallel' not in text
        assert len(payload['instructions']) == 2
        return {'items': [{'id': item['id'], 'review': {'verdict': 'PASS'}} for item in payload['items']]}
    cache = await BatchedReview.prime(items, invoke)
    calls = []
    async def fallback(messages, _format):
        calls.append(messages)
        return {'verdict': 'FALLBACK'}
    proxy = cache.wrap(V3GenerationPipeline(fallback, scoped_revision=True, explanation_consistency=True))
    assert await proxy.review_lesson(lesson, [rule], ['source'], partial_case=False) == {'verdict': 'PASS'}
    lesson.value['content'] = 'changed'
    assert await proxy.review_lesson(lesson, [rule], ['source']) == {'verdict': 'FALLBACK'}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_keyed_answer_explanation_reference_drift_and_scope():
    item = ('review_answer_completeness', ('s', 'q', 'a', ['source']),
            {'explanation': 'e', 'options': ['x', 'y']})
    async def invoke(messages, _format):
        i = json.loads(messages[1]['content'])['items'][0]
        return {'items': [{'id': i['id'], 'review': {'answers': [], 'explanation_review': {}}}]}
    cache = await BatchedReview.prime([item], invoke)
    calls = []
    async def fallback(messages, _format):
        calls.append(messages)
        return {'fallback': True}
    proxy = cache.wrap(V3GenerationPipeline(fallback, scoped_revision=True, explanation_consistency=True))
    assert await proxy.review_answer_completeness(*item[1], **item[2]) == {'answers': [], 'explanation_review': {}}
    for args, kwargs in [((('s', 'q', 'changed', ['source'])), item[2]),
                         (item[1], {'explanation': 'changed', 'options': ['x', 'y']}),
                         (item[1] + (('new-reference',),), item[2])]:
        assert await proxy.review_answer_completeness(*args, **kwargs) == {'fallback': True}
    assert len(calls) == 3
    with pytest.raises(ValueError):
        await BatchedReview.prime([('review_answer', ('s', 'q', 'a', ['source']), {})], invoke)
    with pytest.raises(ValueError):
        await BatchedReview.prime([('review_question_compatibility', ('s', 'q', ['x'], ['source']),
                                    {'consistency_feedback': 'retry'})], invoke)


@pytest.mark.asyncio
async def test_nonfinite_and_foreign_methods_fail_before_invoke():
    calls = []
    async def invoke(*args):
        calls.append(args)
        return {}
    for item in [('review_question_options', ('s', 'q', [float('nan')], ['source']), {}),
                 ('repair_prose', ([], ['source']), {})]:
        with pytest.raises((ValueError, TypeError)):
            await BatchedReview.prime([item], invoke)
    assert not calls
