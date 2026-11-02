import json
from collections import Counter
from dataclasses import replace

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.batched_review import BatchedReview
from app.modules.ai.v3.engine import V3GenerationPipeline
from app.modules.ai.v3.models import RuleEntity, V3Lesson, V3Option, V3QuestionVariant, V3ScenarioCase
from app.modules.ai.v3.review_work_items import lesson_review_items
from app.modules.ai.v3.service import (
    _question_option_inputs,
    _validate_answer_completeness,
    _validate_answer_entailment,
    _validate_question_entailment,
)


def fixture():
    source = 'The clerk checks the document before approval.'
    document = DirectSourceDocument('doc', 'title', 'file', 'general', 'rev', (), source_text=source)
    corpus = DirectSourceCorpus('tenant', (document,), len(source), 0)
    rule = RuleEntity('r1', 's', 'title', source, doc_id='doc', source_revision='rev',
                      source_start=0, source_end=len(source), source_quote=source)
    variant = V3QuestionVariant('v1', 'branch', 'clerk at desk', 'What happens?', V3Option('check', True),
        (V3Option('skip', False), V3Option('delay', False), V3Option('ignore', False)),
        'The document must be checked.', source)
    case = V3ScenarioCase('c1', 'r1', 'Apply the rule', (variant,))
    lesson = V3Lesson('l1', 'title', 'module', '## First\nFirst factual sentence.\n\n## Second\nSecond factual sentence.', ('r1',), (case,))
    return lesson, rule, corpus


@pytest.mark.asyncio
async def test_actual_work_items_batch_and_independent_validators():
    lesson, rule, corpus = fixture()
    items = lesson_review_items(lesson, [lesson], [rule], corpus, ['source'], ['exact source'], (),
                                explanation_consistency=True)
    counts = Counter(item[0] for item in items)
    assert counts == {'review_lesson': 1, 'review_answer': 2, 'review_question_options': 1,
                      'review_question_compatibility': 1, 'review_answer_completeness': 1}
    answer = {'verdict': 'SUPPORTED', 'claims': [{'claim': 'check', 'status': 'SUPPORTED', 'reason': 'source'}],
              'summary': 'supported'}
    result_by_method = {'review_lesson': {'verdict': 'PASS'}, 'review_answer': answer,
        'review_question_options': {'options': []}, 'review_question_compatibility': {'options': []},
        'review_answer_completeness': {'answers': [{'index': 0, 'omissions': []}], 'explanation_review': answer}}
    calls = []
    async def invoke(messages, _format):
        data = json.loads(messages[1]['content'])
        calls.append(data)
        return {'items': [{'id': i['id'], 'review': result_by_method[i['method']]} for i in data['items']]}
    cache = await BatchedReview.prime(items, invoke)
    assert len(calls) == 2
    blind = json.dumps(calls[0])
    assert 'is_correct' not in blind and 'explanation' not in blind and 'source_rules' not in blind
    fallback = []
    async def single(messages, _format):
        fallback.append(messages)
        return {'fallback': True}
    proxy = cache.wrap(V3GenerationPipeline(single, scoped_revision=True, explanation_consistency=True))
    for method, args, kwargs in items:
        assert await getattr(proxy, method)(*args, **kwargs) == result_by_method[method]
    assert not fallback
    assert _validate_answer_entailment(answer)[0]
    assert _validate_answer_completeness(result_by_method['review_answer_completeness'])[0]
    options = next(args[2] for name, args, _ in items if name == 'review_question_options')
    flags = [text == 'check' for text in options]
    option_reviews = []
    for index, correct in enumerate(flags):
        status = 'SUPPORTED' if correct else 'CONTRADICTED'
        option_reviews.append({'index': index, 'verdict': status, 'omitted_required_elements': [],
            'claims': [{'claim': 'action', 'status': status, 'reason': 'source'}], 'summary': 'reviewed'})
    assert _validate_question_entailment({'options': option_reviews}, flags)[0]
    contradicted = {**answer, 'verdict': 'CONTRADICTED',
                    'claims': [{'claim': 'check', 'status': 'CONTRADICTED', 'reason': 'source'}]}
    assert not _validate_answer_completeness({'answers': [{'index': 0, 'omissions': []}],
                                              'explanation_review': contradicted})[0]
    assert not _validate_question_entailment({'options': []}, [True, False, False, False])[0]
    option_reviews[flags.index(True)]['verdict'] = 'CONTRADICTED'
    assert not _validate_question_entailment({'options': option_reviews}, flags)[0]
    method, args, kwargs = next(item for item in items if item[0] == 'review_answer_completeness')
    assert await getattr(proxy, method)(*args, **(kwargs | {'explanation': 'changed'})) == {'fallback': True}
    method, args, kwargs = next(item for item in items if item[0] == 'review_lesson')
    assert await getattr(proxy, method)(replace(args[0], content='changed'), *args[1:], **kwargs) == {'fallback': True}
    assert len(fallback) == 2


def test_missing_source_or_no_questions_never_builds_answer_reviews():
    lesson, rule, corpus = fixture()
    for candidate, rules in [(replace(lesson, cases=()), [rule]), (lesson, [replace(rule, source_revision='wrong')])]:
        items = lesson_review_items(candidate, [candidate], rules, corpus, ['source'], ['source'], (),
                                    explanation_consistency=True)
        assert not any(name.startswith('review_question') or name == 'review_answer_completeness'
                       for name, _, _ in items)


@pytest.mark.asyncio
@pytest.mark.parametrize('held', [frozenset({'v1', 'v2'}), frozenset({'v2'})])
async def test_held_variants_keep_original_question_order_and_cache_scope(held):
    lesson, rule, corpus = fixture()
    first = lesson.cases[0].variants[0]
    second = replace(first, variant_id='v2', prompt='SECOND_QUESTION', explanation='SECOND_EXPLANATION')
    third = replace(first, variant_id='v3', prompt='THIRD_QUESTION', explanation='THIRD_EXPLANATION')
    first_case = replace(lesson.cases[0], variants=(first, second))
    second_case = replace(lesson.cases[0], case_id='c2', variants=(third,))
    original = replace(lesson, cases=(first_case, second_case))
    visible_cases = tuple(replace(case, variants=tuple(v for v in case.variants if v.variant_id not in held))
                          for case in original.cases)
    visible = replace(original, cases=tuple(case for case in visible_cases if case.variants))
    expected = {qid: [text for text, _ in options]
                for qid, _, _, options, _ in _question_option_inputs(original) if qid not in held}
    items = lesson_review_items(original, [visible], [rule], corpus, ['source'], ['exact source'], (),
                                explanation_consistency=True, held_question_ids=held)
    questions = [(args[1], args[2]) for name, args, _ in items if name == 'review_question_options']
    assert len(questions) == len(expected)
    prompts = {'v1': first.prompt, 'v2': second.prompt, 'v3': third.prompt}
    assert dict(questions) == {prompts[qid]: order for qid, order in expected.items()}
    assert all(prompts[qid] not in dict(questions) for qid in held)
    calls = []
    async def batch(messages, _format):
        payload = json.loads(messages[1]['content'])
        calls.append(payload)
        return {'items': [{'id': item['id'], 'review': ({'options': []} if item['method'].startswith('review_question')
            else {'answers': [], 'explanation_review': {}} if item['method'] == 'review_answer_completeness'
            else {'verdict': 'SUPPORTED', 'claims': [], 'summary': 'x'} if item['method'] == 'review_answer'
            else {'verdict': 'PASS'})} for item in payload['items']]}
    cache = await BatchedReview.prime(items, batch)
    serialized = json.dumps(calls)
    assert all(prompts[qid] not in serialized for qid in held)
    fallback = []
    async def single(messages, _format):
        fallback.append(messages)
        return {'fallback': True}
    proxy = cache.wrap(V3GenerationPipeline(single, scoped_revision=True, explanation_consistency=True))
    reviews = [(args, kwargs) for name, args, kwargs in items if name == 'review_question_options']
    a, kw = reviews[0]
    assert await proxy.review_question_options(*a, **kw) == {'options': []}
    assert await proxy.review_question_options(a[0], a[1] + ' changed', *a[2:], **kw) == {'fallback': True}
    assert await proxy.review_question_options(a[0], a[1], list(reversed(a[2])), *a[3:], **kw) == {'fallback': True}
    review_args, review_kw = next((args, kwargs) for name, args, kwargs in items if name == 'review_lesson')
    changed_case = replace(visible.cases[0], learning_objective='changed objective')
    changed_lesson = replace(visible, cases=(changed_case, *visible.cases[1:]))
    assert await proxy.review_lesson(changed_lesson, *review_args[1:], **review_kw) == {'fallback': True}
    if len(reviews) > 1:
        b, kw2 = reviews[1]
        assert await proxy.review_question_options(*b, **kw2) == {'options': []}
    assert len(fallback) == 3
