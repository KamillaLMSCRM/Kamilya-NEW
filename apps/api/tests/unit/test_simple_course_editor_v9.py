import copy
import json

import pytest

from app.modules.ai.v3.practical_contract import _digest, build_practical_source_packet
from app.modules.ai.v3.simple_course_editor_v9 import (
    apply_reviewed_course_v9,
    edit_reviewed_course_v9,
    review_source_unit_v9,
    run_simple_course_editor_v9,
)
from app.modules.ai.v3.simple_semantic_source_plan import build_semantic_slices, semantic_plan_format
from tests.unit.test_v3_simple_owned_transport_v3 import synthetic_corpus, unit_course


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['ok', 'global_gap', 'source_findings', 'duplicate_joint', 'foreign_unit_ref',
                                   'wrong_question', 'drop_image', 'address', 'unresolved', 'provider_error', 'added_five'])
async def test_author_unit_reviews_global_review_and_joint_block_editor(case):
    corpus = synthetic_corpus('tenant', mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    image = '![Caption a](source-asset:asset-' + 'a' * 64 + ')'
    calls, progress, joint_fingerprints = [], [], []

    async def planned(total):
        progress.append(total)

    async def stage(name, group, messages, fmt, validator):
        payload = json.loads(messages[1]['content'])
        assert ':v9:' in group and 'independent_source_reading' not in payload
        role = ('plan' if ':plan:v9:' in group else 'author' if ':author-unit:' in group else
                'unit' if ':review-unit:' in group else 'global' if ':review-content:' in group else
                'address' if ':repair-address:' in group else 'joint')
        calls.append(role)
        if role == 'plan':
            assert 'binds only the specific issue' in messages[0]['content']
            def ids(ref):
                return [s['id'] for s in payload['source_slices'] if s['source_ref'] == ref and s['text'].strip()]
            value = {'source_fingerprint': packet.fingerprint, 'slices_fingerprint': payload['slices_fingerprint'],
                'title': 'Course', 'units': [{'id': 'one', 'title': 'First', 'primary_slices': ids('SRC1'), 'supporting_slices': []},
                    {'id': 'two', 'title': 'Second', 'primary_slices': ids('SRC2'), 'supporting_slices': []}],
                'non_teaching': [{'slice_ids': ids('SRC3'), 'reason': 'Context'}]}
        elif role == 'author':
            ref = payload['primary_slices'][0]['source_ref']
            assert 'independent_source_reading' not in payload
            value = unit_course(ref, 'Repeated.\n\nRepeated.' + ('\n\n' + image if ref == 'SRC1' else ''))
            for question in value['lessons'][0]['questions']:
                question['prompt'] = 'HIDDEN_QUESTION ' + question['id']
                question['explanation'] = 'HIDDEN_EXPLANATION'
        elif role in ('unit', 'global'):
            assert fmt['json_schema']['name'] == 'v3_practical_editorial_review_v2'
            assert 'HIDDEN_QUESTION' not in messages[1]['content'] and 'HIDDEN_EXPLANATION' not in messages[1]['content']
            assert all(set(lesson) == {'id', 'title', 'content'} for lesson in payload['lessons'])
            if role == 'unit':
                assert 'source-unit review, not a whole-document coverage review' in messages[0]['content']
                assert 'selected primary source slices' in messages[0]['content']
                assert ':plan=' in group and ':unit=' in group
                ref = payload['primary_slices'][0]['source_ref']
                allowed = fmt['json_schema']['schema']['properties']['source_notes']['items']['properties']['source_refs']['items']['enum']
                assert ref in allowed and 'SRC3' not in allowed
                if case == 'foreign_unit_ref':
                    ref = 'SRC3'
            else:
                ref = 'SRC1'
                assert len(payload['lessons']) == 2
            props = fmt['json_schema']['schema']['properties']
            findings = []
            if case in ('source_findings', 'duplicate_joint') and (role == 'global' or ref == 'SRC1'):
                findings = [{'domain': 'source', 'severity': 'material', 'target': {'kind': 'source', 'id': 'SRC1'},
                    'problem': 'Unresolved source meaning', 'basis': 'Source uncertainty',
                    'correction': 'Request interpretation', 'source_refs': ['SRC1']}]
            if case == 'global_gap' and role == 'global':
                findings = [{'domain': 'content', 'severity': 'material',
                    'target': {'kind': 'lesson', 'id': payload['lessons'][1]['id']},
                    'problem': 'Cross-unit source rule missing', 'basis': 'Source and draft comparison',
                    'correction': 'Teach the applicable rule', 'source_refs': ['SRC1']}]
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': props['course_fingerprint']['enum'][0],
                     'summary': 'Source comparison', 'findings': findings, 'source_notes': [],
                     'narrative_sources': {lesson['id']: [ref] for lesson in payload['lessons']}}
        elif role == 'address':
            assert progress == [7, 8]
            assert 'source_blocks' not in payload and 'questions' not in payload
            assert ':proposal=' + payload['proposal_fingerprint'] in group
            assert payload['proposal_fingerprint'] == joint_fingerprints[0]
            if case == 'provider_error':
                raise RuntimeError('provider unavailable')
            value = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': payload['draft_fingerprint'],
                     'proposal_fingerprint': payload['proposal_fingerprint'],
                     'assignments': [{'edit_id': 'EDIT1', 'block_id': 'BODY1'},
                                     {'edit_id': 'EDIT2', 'block_id': 'UNRESOLVED' if case == 'unresolved' else 'BODY2'}]}
        else:
            assert fmt['json_schema']['name'] in {'simple_course_block_editor_v1', 'simple_course_block_editor_v2'}
            assert 'HIDDEN_QUESTION' in messages[1]['content'] and len(payload['unit_reviews']) == 2
            if case == 'global_gap':
                assert payload['independent_content_review']['findings'][0]['problem'] == 'Cross-unit source rule missing'
            assert all('body_blocks' in row and 'content' not in row for row in payload['original_course']['lessons'])
            lessons = payload['original_course']['lessons']
            assert [block['text'] for block in lessons[0]['body_blocks'][:2]] == ['Repeated.', 'Repeated.']
            question = copy.deepcopy(lessons[1]['questions'][0])
            question['prompt'] = 'Corrected question'
            if case == 'wrong_question':
                question['id'] = 'foreign-question'
            block = lessons[0]['body_blocks'][2 if case == 'drop_image' else 1]['id']
            value = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': payload['draft_fingerprint'],
                'body_edits': [{'block_id': block, 'after': '' if case == 'drop_image' else 'Improved paragraph.'}],
                'title_edits': [], 'question_edits': [question], 'added_lessons': [],
                'lesson_sources': [{'lesson_id': row['id'], 'source_refs': ['SRC1' if i == 0 else 'SRC2']}
                                   for i, row in enumerate(lessons)],
                'source_questions': ([{'question': 'Unresolved source meaning', 'source_refs': ['SRC1']}]
                                     if case == 'duplicate_joint' else [])}
            if case in ('address', 'unresolved', 'provider_error'):
                value['body_edits'] = [{'block_id': 'BODY1', 'after': 'First correction.'},
                                       {'block_id': 'BODY1', 'after': 'Second correction.'}]
                if case == 'unresolved':
                    value['source_questions'] = [{'question': 'Source question', 'source_refs': ['SRC1']}]
            if 'finding_dispositions' in fmt['json_schema']['schema']['properties']:
                value['finding_dispositions'] = []
            if case == 'added_five':
                added = copy.deepcopy(lessons[1])
                added.pop('body_blocks')
                added.update({'id': 'new-lesson', 'title': 'Missing practical topic', 'content': 'Source-based added teaching.'})
                added['questions'] = [dict(copy.deepcopy(lessons[1]['questions'][0]), id=f'added-{index}')
                                      for index in range(5)]
                value['added_lessons'] = [added]
                value['lesson_sources'].append({'lesson_id': 'new-lesson', 'source_refs': ['SRC2']})
        validated = validator(value)
        if role == 'joint':
            joint_fingerprints.append(_digest(validated))
        return value

    if case == 'foreign_unit_ref':
        with pytest.raises(ValueError):
            await run_simple_course_editor_v9(packet, corpus, {}, stage, planned_callback=planned)
        return
    if case == 'provider_error':
        with pytest.raises(RuntimeError, match='provider unavailable'):
            await run_simple_course_editor_v9(packet, corpus, {}, stage, planned_callback=planned)
        return
    result = await run_simple_course_editor_v9(packet, corpus, {}, stage, planned_callback=planned)
    if case in ('wrong_question', 'drop_image', 'unresolved'):
        assert result.course == result.draft
        assert result.review['editor_delta_receipts']['body']['application_status'] == 'unapplied'
        assert result.review['revision_receipt']['unapplied_review_findings']
        if case == 'unresolved':
            assert result.source_questions[0]['question'] == 'Source question'
            assert calls[-1] == 'address' and progress == [7, 8]
        else:
            assert calls[-1] == 'joint' and progress == [7]
        return
    if case == 'address':
        assert calls[-1] == 'address' and progress == [7, 8]
        assert result.course['lessons'][0]['content'] == 'First correction.\n\nSecond correction.\n\n' + image
        assert result.review['editor_delta_receipts']['body']['address_receipt']['semantic_text_preserved']
        return
    if case == 'added_five':
        assert len(result.course['lessons']) == 3
        assert len(result.course['lessons'][-1]['questions']) == 5
        assert result.review['editor_delta_receipts']['body']['application_status'] == 'applied'
        return
    assert calls == ['plan', 'author', 'unit', 'author', 'unit', 'global', 'joint'] and progress == [7]
    assert result.course['lessons'][0]['content'] == 'Repeated.\n\nImproved paragraph.\n\n' + image
    assert result.course['lessons'][1]['content'] == 'Repeated.\n\nRepeated.'
    assert result.course['lessons'][1]['questions'][0]['prompt'] == 'Corrected question'
    assert result.course['lessons'][1]['questions'][1:] == result.draft['lessons'][1]['questions'][1:]
    receipt = result.review['editor_delta_receipts']['body']
    assert len(receipt['unit_reviews']) == 2 and receipt['joint_delta_receipt']['body_spans'][0]['block_id'] == 'BODY2'
    assert result.review['editor_delta_receipts']['cards']['no_extra_model_call'] is True
    source_receipt = result.review['revision_receipt']
    assert source_receipt['draft_fingerprint'] == _digest(result.draft)
    assert len(source_receipt['source_findings']) == (2 if case in ('source_findings', 'duplicate_joint') else 0)
    assert len(source_receipt['unverified_source_questions']) == (1 if case == 'source_findings' else 0)
    if case == 'global_gap':
        assert source_receipt['unapplied_review_findings'][0]['finding']['problem'] == 'Cross-unit source rule missing'
        assert source_receipt['review_finding_dispositions'][0]['model_resolved'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['source', 'plan', 'selection', 'lesson', 'snapshot', 'refs', 'extra_lesson'])
async def test_stale_unit_review_is_rejected_before_global_review(fault):
    corpus = synthetic_corpus('tenant', mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    slices = [row['id'] for row in build_semantic_slices(packet, corpus) if row['text'].strip()]
    fmt = semantic_plan_format(packet, corpus)
    plan = {'source_fingerprint': packet.fingerprint,
        'slices_fingerprint': fmt['json_schema']['schema']['properties']['slices_fingerprint']['enum'][0],
        'title': 'Course', 'units': [{'id': 'one', 'title': 'Task', 'primary_slices': slices,
                                     'supporting_slices': []}], 'non_teaching': []}
    lesson_id = 'lesson-' + _digest([_digest(plan), 'one'])[:24]
    original = unit_course(packet.blocks[0].block_id, 'Source-based lesson')
    original['title'] = plan['title']
    original['lessons'][0]['id'] = lesson_id

    async def unit_stage(_name, _group, messages, wire_fmt, validator):
        payload = json.loads(messages[1]['content'])
        props = wire_fmt['json_schema']['schema']['properties']
        value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': props['course_fingerprint']['enum'][0],
                 'summary': 'Review', 'findings': [], 'source_notes': [],
                 'narrative_sources': {payload['lessons'][0]['id']: ['SRC1']}}
        validator(value)
        return value

    record = await review_source_unit_v9(packet, corpus, {}, plan, plan['units'][0], original, unit_stage)
    if fault == 'extra_lesson':
        extra = copy.deepcopy(original['lessons'][0])
        extra['id'] = 'unreviewed-lesson'
        for question in extra['questions']:
            question['id'] += '-extra'
        original['lessons'].append(extra)
    else:
        key = {'source': 'source_fingerprint', 'plan': 'plan_fingerprint', 'selection': 'selection_fingerprint',
               'lesson': 'lesson_id', 'snapshot': 'reviewed_unit_fingerprint', 'refs': 'primary_refs'}[fault]
        record[key] = [] if fault == 'refs' else 'forged'
    async def forbidden(*_args, **_kwargs):
        pytest.fail('global review must not be invoked')
    with pytest.raises(ValueError, match='simple_v9_unit_reviews_invalid'):
        await edit_reviewed_course_v9(packet, corpus, {}, original, plan, [], forbidden, unit_reviews=[record])


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['zero', 'one', 'stale_global', 'foreign_global', 'stale_unit', 'foreign_unit', 'incomplete_full'])
async def test_lowlevel_joint_accepts_only_valid_actual_partial_reviews(case):
    corpus = synthetic_corpus('tenant', mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    slices = build_semantic_slices(packet, corpus)
    fmt = semantic_plan_format(packet, corpus)
    def ids(index):
        return [row['id'] for row in slices if row['source_ref'] == packet.blocks[index].block_id and row['text'].strip()]
    plan = {'source_fingerprint': packet.fingerprint,
        'slices_fingerprint': fmt['json_schema']['schema']['properties']['slices_fingerprint']['enum'][0], 'title': 'Course',
        'units': [{'id': 'one', 'title': 'First', 'primary_slices': ids(0), 'supporting_slices': []},
                  {'id': 'two', 'title': 'Second', 'primary_slices': ids(1), 'supporting_slices': []}],
        'non_teaching': [{'slice_ids': ids(2), 'reason': 'Context'}]}
    lessons = []
    for index, unit in enumerate(plan['units']):
        lesson = unit_course(packet.blocks[index].block_id, 'Source lesson')['lessons'][0]
        lesson['id'] = 'lesson-' + _digest([_digest(plan), unit['id']])[:24]
        for question in lesson['questions']:
            question['id'] = 'question-' + _digest([lesson['id'], question['id']])[:24]
        lessons.append(lesson)
    original = {'title': plan['title'], 'lessons': lessons}

    async def unit_stage(_name, _group, messages, wire_fmt, validator):
        payload = json.loads(messages[1]['content'])
        props = wire_fmt['json_schema']['schema']['properties']
        value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': props['course_fingerprint']['enum'][0],
                 'summary': 'Unit review', 'findings': [], 'source_notes': [],
                 'narrative_sources': {payload['lessons'][0]['id']: ['SRC1']}}
        validator(value)
        return value
    record = await review_source_unit_v9(packet, corpus, {}, plan, plan['units'][0],
                                         {'title': plan['title'], 'lessons': [copy.deepcopy(lessons[0])]}, unit_stage)
    global_review = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(original),
        'summary': 'Global review', 'findings': [], 'source_notes': [],
        'narrative_sources': {lesson['id']: [packet.blocks[0].block_id] for lesson in lessons}}
    records = [] if case == 'zero' else [copy.deepcopy(record)]
    if case == 'stale_global':
        global_review['course_fingerprint'] = '0' * 64
    elif case == 'foreign_global':
        global_review['narrative_sources'][lessons[0]['id']] = ['foreign']
    elif case == 'stale_unit':
        records[0]['reviewed_unit_fingerprint'] = '0' * 64
    elif case == 'foreign_unit':
        records[0]['review']['narrative_sources'][lessons[0]['id']] = [packet.blocks[2].block_id]
    calls = []
    async def joint(name, group, messages, wire_fmt, validator):
        calls.append((name, group))
        payload = json.loads(messages[1]['content'])
        assert len(payload['unit_reviews']) == len(records)
        value = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': payload['draft_fingerprint'],
            'body_edits': [], 'title_edits': [], 'question_edits': [], 'added_lessons': [],
            'lesson_sources': [{'lesson_id': lesson['id'], 'source_refs': ['SRC1']} for lesson in lessons],
            'source_questions': []}
        validator(value)
        return value
    if case == 'incomplete_full':
        with pytest.raises(ValueError, match='simple_v9_unit_reviews_invalid'):
            await edit_reviewed_course_v9(packet, corpus, {}, original, plan, [], joint, unit_reviews=records)
        assert not calls
    elif case in ('stale_global', 'foreign_global', 'stale_unit', 'foreign_unit'):
        with pytest.raises(ValueError):
            await apply_reviewed_course_v9(packet, corpus, {}, original, plan, joint,
                                           content_review=global_review, unit_reviews=records)
        assert not calls
    else:
        body, cards, receipt, passthrough = await apply_reviewed_course_v9(
            packet, corpus, {}, original, plan, joint, content_review=global_review, unit_reviews=records)
        assert body == cards and body['course'] == original and len(calls) == 1
        assert receipt['unit_reviews'] == records and passthrough['no_extra_model_call'] is True
