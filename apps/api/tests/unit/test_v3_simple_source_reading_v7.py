import copy
import json

import pytest

from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.simple_course_editor_v7 import run_simple_course_editor_v7
from tests.unit.test_v3_simple_owned_transport_v3 import synthetic_corpus, unit_course
from tests.unit.test_v3_simple_source_unit import corpus_for


@pytest.mark.asyncio
async def test_v7_source_reader_scoped_authors_editors_and_cold_replay():
    corpus = synthetic_corpus('tenant', mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    checkpoint, calls, total = {}, [], []
    image = '![Caption a](source-asset:asset-' + 'a' * 64 + ')'

    async def progress(count):
        total.append(count)

    async def stage(name, group, messages, fmt, validator):
        if group in checkpoint:
            value = copy.deepcopy(checkpoint[group])
            validator(value)
            return value
        payload = json.loads(messages[1]['content'])
        kind = fmt['json_schema']['name']
        role = ('plan' if ':plan:' in group else 'read' if ':source-read:' in group else
                'author' if ':author-unit:' in group else 'body' if ':editor-body:' in group else 'cards')
        calls.append((name, role))
        assert ':v7:' in group
        if role == 'plan':
            def ids(ref):
                return [s['id'] for s in payload['source_slices'] if s['source_ref'] == ref and s['text'].strip()]
            value = {'source_fingerprint': packet.fingerprint, 'slices_fingerprint': payload['slices_fingerprint'],
                'title': 'Course', 'units': [
                    {'id': 'first', 'title': 'First', 'primary_slices': ids('SRC1'), 'supporting_slices': []},
                    {'id': 'second', 'title': 'Second', 'primary_slices': ids('SRC2'), 'supporting_slices': []}],
                'non_teaching': [{'slice_ids': ids('SRC3'), 'reason': 'Context'}]}
        elif role == 'read':
            assert kind == 'v3_practical_source_semantics_v1'
            assert 'current_learning_units' not in payload and 'teaching_units' not in payload
            assert 'HIDDEN_QUESTION' not in messages[1]['content']
            assert any(s['origin'] == 'visual_ocr' for b in payload['source_blocks'] for s in b['segments'])
            def rule(ref, quote):
                return {'source_refs': [ref], 'source_quote': quote, 'actor': 'Staff', 'action': 'Act',
                        'object': 'Item', 'conditions': [], 'modality': 'required', 'alternatives': [], 'limits': []}
            value = {'source_fingerprint': packet.fingerprint,
                'sections': [{'section': 'Tasks', 'rules': [rule('SRC1', 'First topic instructs action.'),
                                                             rule('SRC2', 'Not a literal quote')]}],
                'uncertainties': [{'source_refs': ['SRC1'], 'source_quote': '', 'question': 'UNDECIDED_READER_ONLY'}]}
        elif role == 'author':
            ref = payload['primary_slices'][0]['source_ref']
            reading = payload['independent_source_reading']
            assert 'uncertainties' not in reading and 'UNDECIDED_READER_ONLY' not in messages[1]['content']
            rules = [r for s in reading['sections'] for r in s['rules']]
            assert len(rules) == 1 and rules[0]['source_refs'] == [ref]
            assert rules[0]['custody_valid'] is (ref == 'SRC1')
            value = unit_course(ref, 'Original lesson' + ('\n' + image if ref == 'SRC1' else ''))
            for q in value['lessons'][0]['questions']:
                q['prompt'] = 'HIDDEN_QUESTION ' + q['id']
        else:
            assert 'source_slices' not in payload and payload['source_slice_index'] and payload['source_blocks']
            assert all('text' not in row and 'origins' not in row for row in payload['source_slice_index'])
            assert payload['independent_source_reading']['uncertainties'][0]['question'] == 'UNDECIDED_READER_ONLY'
            assert 'original' not in payload['independent_source_reading']
            assert 'custody_valid' not in json.dumps(payload['independent_source_reading'])
            assert [x['custody_valid'] for x in payload['independent_reading_custody']['rule_flags']] == [True, False]
            assert messages[1]['content'].count('Not a literal quote') == 1
            assert 'original source' in messages[0]['content'].lower()
            assert 'literal quote alone does not prove semantic agreement' in messages[0]['content']
            if role == 'body':
                assert 'HIDDEN_QUESTION' not in messages[1]['content']
                lessons = payload['teaching_units']
            else:
                lessons = payload['current_learning_units']['lessons']
                assert 'Preserve good cards even when similar' in messages[0]['content']
                assert 'revise such repetitions' not in messages[0]['content']
            value = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': payload['draft_fingerprint'],
                'body_edits': [], 'title_edits': [], 'question_edits': [], 'added_lessons': [],
                'lesson_sources': [{'lesson_id': lesson['id'], 'source_refs': ['SRC1' if i == 0 else 'SRC2']}
                                   for i, lesson in enumerate(lessons)], 'source_questions': []}
        validator(value)
        checkpoint[group] = copy.deepcopy(value)
        return value

    first = await run_simple_course_editor_v7(packet, corpus, {}, stage, planned_callback=progress)
    assert calls == [('review', 'plan'), ('review', 'read'), ('lesson', 'author'), ('lesson', 'author'),
                     ('repair', 'body'), ('repair', 'cards')]
    assert total == [6] and first.source_questions == []
    assert first.review['source_only_reading']['uncertainties'][0]['question'] == 'UNDECIDED_READER_ONLY'
    assert first.draft == first.course and image in first.course['lessons'][0]['content']
    assert len({q['id'] for lesson in first.course['lessons'] for q in lesson['questions']}) == 6
    before = copy.deepcopy(calls)
    second = await run_simple_course_editor_v7(packet, corpus, {}, stage, planned_callback=progress)
    assert calls == before and second == first and total == [6, 6]


@pytest.mark.asyncio
async def test_reader_and_editors_exclude_blank_blocks_from_typed_source():
    corpus = corpus_for(' \n\n# 1. Task\nPerform the task.')
    packet = build_practical_source_packet(corpus)
    assert any(not block.text.strip() for block in packet.blocks)
    checked = []

    async def stage(name, group, messages, fmt, validator):
        payload = json.loads(messages[1]['content'])
        if ':plan:' in group:
            ids = [s['id'] for s in payload['source_slices'] if s['text'].strip()]
            value = {'source_fingerprint': packet.fingerprint, 'slices_fingerprint': payload['slices_fingerprint'],
                'title': 'Course', 'units': [{'id': 'u', 'title': 'Task', 'primary_slices': ids,
                                               'supporting_slices': []}], 'non_teaching': []}
        elif ':source-read:' in group:
            checked.append('read')
            assert all(isinstance(block['id'], str) for block in payload['source_blocks'])
            value = {'source_fingerprint': packet.fingerprint, 'sections': [{'section': 'Task', 'rules': []}],
                     'uncertainties': []}
        elif ':author-unit:' in group:
            value = unit_course('SRC1', 'Lesson')
        else:
            checked.append('body' if ':editor-body:' in group else 'cards')
            assert all(isinstance(block['id'], str) for block in payload['source_blocks'])
            lessons = payload.get('teaching_units') or payload['current_learning_units']['lessons']
            value = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': payload['draft_fingerprint'],
                     'body_edits': [], 'title_edits': [], 'question_edits': [], 'added_lessons': [],
                     'lesson_sources': [{'lesson_id': lesson['id'], 'source_refs': ['SRC1']} for lesson in lessons],
                     'source_questions': []}
        validator(value)
        return value

    await run_simple_course_editor_v7(packet, corpus, {}, stage)
    assert checked == ['read', 'body', 'cards']
