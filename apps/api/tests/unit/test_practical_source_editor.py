import copy
import json

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.practical_contract import _digest, build_practical_source_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView


def empty_source_editor_review(fmt):
    props = fmt['json_schema']['schema']['properties']
    return {'source_fingerprint': props['source_fingerprint']['enum'][0],
        'course_fingerprint': props['course_fingerprint']['enum'][0], 'summary': 'No material findings',
        'findings': [], 'source_notes': [], 'narrative_sources': {
            key: [schema['items']['enum'][0]] for key, schema in props['narrative_sources']['properties'].items()}}


def example():
    text = 'Issue the principal using an expense order. Interest received at issuance uses a receipt order.\n\nAn employee advance is paid only to the employee named as recipient.'
    doc = DirectSourceDocument('doc', 'Source', 'source.txt', 'general', 'r1', (), source_text=text)
    corpus = DirectSourceCorpus('tenant', (doc,), len(text), 0)
    packet = build_practical_source_packet(corpus)
    q = {'id': 'question', 'prompt': 'Which operation is an expense?',
         'choices': ['Any issuance', 'Principal payout', 'Interest received'], 'correct_index': 1,
         'explanation': 'Issuance is always an expense.', 'source_refs': [packet.blocks[0].block_id]}
    course = {'title': 'Course', 'lessons': [
        {'id': 'one', 'title': 'Advance', 'content': 'The client signs an employee advance.', 'questions': [q]},
        {'id': 'two', 'title': 'Preserved', 'content': 'Unchanged useful lesson.',
         'questions': [dict(q, id='other', prompt='Another question?')]},
    ]}
    return corpus, packet, course


@pytest.mark.asyncio
@pytest.mark.parametrize('retained_issue', ['none', 'source', 'untouched'])
async def test_whole_source_editor_repairs_both_domains_preserving_good_neighbors(retained_issue):
    from app.modules.ai.v3.practical_source_editor import run_source_editor
    corpus, packet, course = example()
    untouched = copy.deepcopy(course['lessons'][0]['questions'][0])
    untouched.update(id='untargeted', prompt='Preserve this useful question?')
    course['lessons'][0]['questions'].append(untouched)
    view = PracticalModelView(packet)
    calls = []
    async def stage(name, group, messages, fmt, validate):
        calls.append((name, group))
        props = fmt['json_schema']['schema']['properties']
        if ':editorial-review:' in group:
            findings = [] if len(calls) > 1 else [
                {'domain': 'content', 'severity': 'material', 'target': {'kind': 'lesson', 'id': 'one'},
                 'problem': 'Wrong recipient', 'basis': 'Named employee rule', 'correction': 'Clarify recipient',
                 'source_refs': [packet.blocks[0].block_id]},
                {'domain': 'assessment', 'severity': 'material', 'target': {'kind': 'question', 'id': 'question'},
                 'problem': 'Broad option overlaps principal payout', 'basis': 'Distinct operations',
                 'correction': 'Separate payment and receipt', 'source_refs': [packet.blocks[0].block_id]},
            ]
            if len(calls) == 1 and retained_issue != 'none':
                findings.append({'domain': 'source' if retained_issue == 'source' else 'content',
                    'severity': 'material', 'target': {'kind': 'lesson', 'id': 'two'},
                    'problem': 'Unresolved independent issue', 'basis': 'Not fixed by this revision',
                    'correction': 'Keep visible', 'source_refs': [packet.blocks[0].block_id]})
            value = {'source_fingerprint': packet.fingerprint,
                'course_fingerprint': props['course_fingerprint']['enum'][0], 'summary': 'Review',
                'findings': findings, 'source_notes': [],
                'narrative_sources': {lesson['id']: [packet.blocks[0].block_id] for lesson in course['lessons']}}
        else:
            fixed = copy.deepcopy(course)
            fixed['lessons'][0]['content'] = 'The named employee signs the advance receipt.'
            fixed['lessons'][0]['questions'][0]['choices'][0] = 'Interest receipt at issuance'
            fixed['lessons'][0]['questions'][0]['explanation'] = 'Principal payout and interest receipt are distinct.'
            fixed['lessons'][0]['questions'][1]['explanation'] = 'Unrequested bad neighbor rewrite.'
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course),
                     'course': fixed, 'lesson_sources': [{'lesson_id': lesson['id'], 'source_refs': [packet.blocks[0].block_id]}
                                                       for lesson in fixed['lessons']]}
        wire = view.encode(value)
        validate(wire)
        return wire
    fixed, receipt, pending = await run_source_editor(packet, corpus, course, view, stage)
    assert len(calls) == 3
    assert fixed['lessons'][0]['content'] == 'The named employee signs the advance receipt.'
    assert fixed['lessons'][0]['questions'][0]['choices'][0] == 'Interest receipt at issuance'
    assert fixed['lessons'][1] == course['lessons'][1]
    assert fixed['lessons'][0]['questions'][1] == untouched
    assert receipt['semantic_acceptance'] is False
    assert receipt['revision']['changed_question_ids'] == ['question']
    assert 'untargeted' in receipt['revision']['ignored_unrequested_changes']
    if retained_issue == 'none':
        assert not pending
    else:
        assert len(pending) == 1
        assert pending[0]['scope'] == ('source' if retained_issue == 'source' else 'lesson')
    assert receipt['original_course_fingerprint'] == _digest(course)


def test_editor_request_has_no_fixture_specific_correction_hints():
    from app.modules.ai.v3.practical_source_editor import source_editor_request
    corpus, packet, course = example()
    messages, _ = source_editor_request(packet, corpus, course, PracticalModelView(packet))
    assert 'source' in messages[0]['content'].lower() or 'источ' in messages[0]['content'].lower()
    assert 'касс' not in messages[0]['content'].lower()
    assert 'CURRENT_COURSE_JSON' in messages[1]['content']
    assert 'Wrong recipient' not in json.dumps(messages)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['clean', 'source_ambiguity', 'advisory'])
async def test_nonrepair_findings_never_trigger_speculative_rewrite(kind):
    from app.modules.ai.v3.practical_source_editor import run_source_editor
    corpus, packet, course = example()
    view = PracticalModelView(packet)
    calls = []
    async def stage(name, group, messages, fmt, validate):
        calls.append(group)
        value = empty_source_editor_review(fmt)
        if kind != 'clean':
            value['findings'] = [{'domain': 'source' if kind == 'source_ambiguity' else 'content',
                'severity': 'material' if kind == 'source_ambiguity' else 'advisory',
                'target': {'kind': 'lesson', 'id': 'one'}, 'problem': 'Two source alternatives',
                'basis': 'Not decided by source', 'correction': 'Ask source owner', 'source_refs': ['SRC1']}]
        validate(value)
        return value
    after, receipt, pending = await run_source_editor(packet, corpus, course, view, stage)
    assert after == course and len(calls) == 1 and receipt['semantic_acceptance'] is False
    if kind == 'source_ambiguity':
        assert len(pending) == 1 and pending[0]['scope'] == 'source'
        assert pending[0]['id'] == packet.blocks[0].block_id
    else:
        assert not pending


@pytest.mark.asyncio
async def test_unknown_editor_outcome_is_not_retried_or_accepted():
    from app.modules.ai.v3.practical_source_editor import run_source_editor
    corpus, packet, course = example()
    calls = []
    async def stage(*args):
        calls.append(args[1])
        raise TimeoutError('unknown')
    with pytest.raises(TimeoutError):
        await run_source_editor(packet, corpus, course, PracticalModelView(packet), stage)
    assert len(calls) == 1


def test_review_cannot_use_foreign_corpus_or_drop_media():
    from dataclasses import replace

    from app.modules.ai.v3.practical_source_editor import _protect, source_editor_request
    corpus, packet, course = example()
    with pytest.raises(ValueError, match='corpus_mismatch'):
        source_editor_request(packet, replace(corpus, tenant_id='foreign'), course, PracticalModelView(packet))
    course['lessons'][0]['content'] += '\n\n![Form](source-asset:asset-example)'
    after = copy.deepcopy(course)
    after['lessons'][0]['content'] = 'Lost image.'
    with pytest.raises(ValueError, match='media_changed'):
        _protect(course, after)


@pytest.mark.asyncio
@pytest.mark.parametrize('identity', ['current', 'stale_course', 'foreign_source', 'foreign_corpus'])
async def test_retained_observations_bind_revision_and_are_not_rediscovered(identity):
    from app.modules.ai.v3.practical_editorial_contract import editorial_review_format
    from app.modules.ai.v3.practical_source_editor import run_source_editor
    corpus, packet, course = example()
    retained = empty_source_editor_review(editorial_review_format(packet, course))
    retained['findings'] = [{'domain': 'source', 'severity': 'material',
        'target': {'kind': 'lesson', 'id': 'one'}, 'problem': 'Unresolved source decision',
        'basis': 'Recorded before restart', 'correction': 'Keep visible',
        'source_refs': [packet.blocks[0].block_id]}]
    if identity == 'foreign_corpus':
        from dataclasses import replace
        corpus = replace(corpus, tenant_id='foreign')
    elif identity != 'current':
        retained['course_fingerprint' if identity == 'stale_course' else 'source_fingerprint'] = '0' * 64
    async def stage(*args):
        pytest.fail('Retained source-only observations must not generate or rediscover content')
    if identity != 'current':
        with pytest.raises(ValueError, match=('corpus_mismatch' if identity == 'foreign_corpus'
                                              else 'editorial_review_response_invalid')):
            await run_source_editor(packet, corpus, course, PracticalModelView(packet), stage,
                                    retained_review=retained)
    else:
        after, receipt, pending = await run_source_editor(packet, corpus, course, PracticalModelView(packet),
                                                        stage, retained_review=retained)
        assert after == course and len(pending) == 1
        assert receipt['initial_review_origin'] == 'retained_observations'
        assert receipt['semantic_acceptance'] is False


@pytest.mark.asyncio
async def test_partial_last_question_revision_retains_peer_order_and_reports_only_applied_changes():
    from app.modules.ai.v3.practical_source_editor import run_source_editor
    corpus, packet, course = example()
    course['lessons'][0]['questions'].append(dict(course['lessons'][0]['questions'][0],
        id='last-question', prompt='A separately targeted question?'))
    before = copy.deepcopy(course)
    view = PracticalModelView(packet)
    calls = []
    async def stage(name, group, messages, fmt, validate):
        calls.append(name)
        if name == 'review':
            value = empty_source_editor_review(fmt)
            if len(calls) == 1:
                value['findings'] = [{'domain': 'assessment', 'severity': 'material',
                    'target': {'kind': 'question', 'id': 'last-question'},
                    'problem': 'Broad answer', 'basis': 'Two source-supported conditions',
                    'correction': 'Clarify the action', 'source_refs': ['SRC1']}]
        else:
            targets = json.loads(messages[1]['content'].split('\nCURRENT_TARGETS_JSON\n')[1]
                                 .split('\nUNVERIFIED_EDITORIAL_FINDINGS_JSON\n')[0])
            assert len(targets['lessons']) == 1
            assert [q['id'] for q in targets['lessons'][0]['questions']] == ['last-question']
            targets['lessons'][0]['questions'][0]['explanation'] = 'The scoped action has one correct answer.'
            props = fmt['json_schema']['schema']['properties']
            value = {'source_fingerprint': props['source_fingerprint']['enum'][0],
                'course_fingerprint': props['course_fingerprint']['enum'][0], 'course': targets,
                'lesson_sources': [{'lesson_id': 'one', 'source_refs': ['SRC1']}]}
        validate(value)
        return value
    final, receipt, pending = await run_source_editor(packet, corpus, course, view, stage)
    assert calls == ['review', 'repair', 'review'] and not pending
    assert [q['id'] for q in final['lessons'][0]['questions']] == ['question', 'last-question']
    assert final['lessons'][0]['questions'][0] == before['lessons'][0]['questions'][0]
    assert final['lessons'][0]['content'] == before['lessons'][0]['content']
    assert final['lessons'][1] == before['lessons'][1]
    assert receipt['revision']['changed_question_ids'] == ['last-question']
    assert receipt['revision']['changed_lesson_ids'] == ['one']
