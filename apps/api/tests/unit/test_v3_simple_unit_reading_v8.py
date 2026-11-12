import copy
import json

import pytest

from app.modules.ai.v3.practical_contract import _digest, build_practical_source_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.simple_course_editor_v8 import (
    _COMPARE,
    _GRAMMAR,
    _MINIMAL_SPANS,
    _READ,
    _REFERENTS,
    _SCOPE,
    run_simple_course_editor_v8,
)
from tests.unit.test_v3_simple_owned_transport_v3 import synthetic_corpus, unit_course


def rule(ref, quote):
    return {'source_refs': [ref], 'source_quote': quote, 'actor': 'Staff', 'action': 'Act', 'object': 'Item',
            'conditions': [], 'modality': 'required', 'alternatives': [], 'limits': []}


@pytest.mark.asyncio
async def test_v8_independent_unit_readings_author_editors_and_replay():
    corpus = synthetic_corpus('tenant', mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    view = PracticalModelView(packet)
    calls, cache, progress = [], {}, []
    image = '![Caption a](source-asset:asset-' + 'a' * 64 + ')'
    seen_plan = None

    async def planned(count):
        progress.append(count)

    async def stage(name, group, messages, fmt, validator):
        nonlocal seen_plan
        if group in cache:
            cached = copy.deepcopy(cache[group])
            validator(cached)
            return cached
        payload = json.loads(messages[1]['content'])
        role = ('plan' if ':plan:v8:' in group else 'read' if ':source-read:' in group else
                'author' if ':author-unit:' in group else 'body' if ':editor-body:' in group else 'cards')
        calls.append((name, role))
        if role == 'plan':
            def ids(ref):
                return [s['id'] for s in payload['source_slices'] if s['source_ref'] == ref and s['text'].strip()]
            value = {'source_fingerprint': packet.fingerprint, 'slices_fingerprint': payload['slices_fingerprint'],
                'title': 'Course', 'units': [
                    {'id': 'first', 'title': 'First', 'primary_slices': ids('SRC1'), 'supporting_slices': []},
                    {'id': 'second', 'title': 'Second', 'primary_slices': ids('SRC2'), 'supporting_slices': []}],
                'non_teaching': [{'slice_ids': ids('SRC3'), 'reason': 'Context'}]}
            seen_plan = _digest(value)
        elif role == 'read':
            assert ':plan=' + seen_plan + ':unit=' in group
            assert messages[0]['content'] == _READ + _REFERENTS + _MINIMAL_SPANS + _GRAMMAR + _SCOPE
            assert 'current_learning_units' not in payload and 'teaching_units' not in payload
            assert 'HIDDEN_QUESTION' not in messages[1]['content']
            ref = payload['primary_slices'][0]['source_ref']
            allowed = fmt['json_schema']['schema']['properties']['uncertainties']['items']['properties']['source_refs']['items']['enum']
            assert ref in allowed
            if ref == 'SRC1':
                assert any(s['origin'] == 'visual_ocr' for b in payload['source_blocks'] for s in b['segments'])
                assert any(s['origin'] == 'visual_description' for b in payload['source_blocks'] for s in b['segments'])
            foreign = 'SRC3'
            assert foreign not in allowed
            invalid = {'source_fingerprint': packet.fingerprint,
                       'sections': [{'section': 'Task', 'rules': [rule(foreign, '')]}], 'uncertainties': []}
            with pytest.raises(ValueError, match='reading_scope'):
                validator(invalid)
            value = {'source_fingerprint': packet.fingerprint,
                'sections': [{'section': 'Task', 'rules': [rule(ref, 'First topic instructs action.' if ref == 'SRC1' else 'bad quote')]}],
                'uncertainties': [{'source_refs': [ref], 'source_quote': '', 'question': 'READER_UNCERTAINTY'}]}
        elif role == 'author':
            assert ':plan=' + seen_plan + ':unit=' in group
            ref = payload['primary_slices'][0]['source_ref']
            reading = payload['independent_source_reading']
            rules = [r for section in reading['sections'] for r in section['rules']]
            assert len(rules) == 1 and rules[0]['source_refs'] == [ref]
            assert rules[0]['custody_valid'] is (ref == 'SRC1') and 'uncertainties' not in reading
            value = unit_course(ref, 'Old intro.\n\nKeep content.' + ('\n' + image if ref == 'SRC1' else ''))
            for q in value['lessons'][0]['questions']:
                q['prompt'] = 'HIDDEN_QUESTION ' + q['id']
        else:
            assert group.endswith(':unit=' + seen_plan)
            assert _COMPARE in messages[0]['content'] and 'source_blocks' in payload
            assert 'source_slices' not in payload and payload['source_slice_index']
            assert len(payload['independent_source_reading']['sections']) == 2
            assert [r['rule_id'] for r in payload['independent_reading_custody']['rule_flags']] == ['R1', 'R2']
            assert [r['custody_valid'] for r in payload['independent_reading_custody']['rule_flags']] == [True, False]
            if role == 'body':
                assert 'HIDDEN_QUESTION' not in messages[1]['content']
                lessons = payload['teaching_units']
            else:
                assert 'Preserve good cards even when similar' in messages[0]['content']
                lessons = payload['current_learning_units']['lessons']
                assert payload['draft_fingerprint'] == _digest(view.decode(payload['current_learning_units']))
                assert lessons[0]['content'].startswith('New intro.')
            value = {'source_fingerprint': packet.fingerprint, 'draft_fingerprint': payload['draft_fingerprint'],
                'body_edits': [], 'title_edits': [], 'question_edits': [], 'added_lessons': [],
                'lesson_sources': [{'lesson_id': item['id'], 'source_refs': ['SRC1' if i == 0 else 'SRC2']}
                                   for i, item in enumerate(lessons)], 'source_questions': []}
            if role == 'body':
                value['body_edits'] = [{'lesson_id': lessons[0]['id'], 'before': 'Old intro.', 'after': 'New intro.'}]
            else:
                question = copy.deepcopy(lessons[0]['questions'][0])
                question['prompt'] = 'Corrected card'
                value['question_edits'] = [{'lesson_id': lessons[0]['id'], 'question': question}]
        validator(value)
        cache[group] = copy.deepcopy(value)
        return value

    first = await run_simple_course_editor_v8(packet, corpus, {}, stage, planned_callback=planned)
    assert calls == [('review', 'plan'), ('review', 'read'), ('lesson', 'author'), ('review', 'read'),
                     ('lesson', 'author'), ('repair', 'body'), ('repair', 'cards')]
    assert progress == [7] and first.source_questions == []
    assert first.course['lessons'][0]['content'] == 'New intro.\n\nKeep content.\n' + image
    assert first.course['lessons'][0]['questions'][0]['prompt'] == 'Corrected card'
    assert first.course['lessons'][0]['questions'][1:] == first.draft['lessons'][0]['questions'][1:]
    assert len(first.review['unit_source_readings']) == 2
    assert len(first.review['source_only_reading']['uncertainties']) == 2
    initial = copy.deepcopy(calls)
    second = await run_simple_course_editor_v8(packet, corpus, {}, stage, planned_callback=planned)
    assert calls == initial and second == first and progress == [7, 7]


@pytest.mark.asyncio
async def test_failed_unit_read_never_invokes_author():
    corpus = synthetic_corpus('tenant', mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    calls = []
    async def stage(name, group, messages, fmt, validator):
        calls.append(name)
        payload = json.loads(messages[1]['content'])
        if ':plan:' in group:
            ids = [s['id'] for s in payload['source_slices'] if s['text'].strip()]
            value = {'source_fingerprint': packet.fingerprint, 'slices_fingerprint': payload['slices_fingerprint'],
                     'title': 'Course', 'units': [{'id': 'one', 'title': 'Task', 'primary_slices': ids,
                                                    'supporting_slices': []}], 'non_teaching': []}
            validator(value)
            return value
        raise ValueError('synthetic_reader_failure')
    with pytest.raises(ValueError, match='synthetic_reader_failure'):
        await run_simple_course_editor_v8(packet, corpus, {}, stage)
    assert calls == ['review', 'review']


@pytest.mark.asyncio
async def test_reader_and_author_checkpoints_are_bound_to_complete_plan():
    corpus = synthetic_corpus('tenant', mixed_origin=True)
    packet = build_practical_source_packet(corpus)
    async def run(title):
        groups = []
        async def stage(name, group, messages, fmt, validator):
            payload = json.loads(messages[1]['content'])
            if ':plan:' in group:
                ids = [s['id'] for s in payload['source_slices'] if s['text'].strip()]
                value = {'source_fingerprint': packet.fingerprint, 'slices_fingerprint': payload['slices_fingerprint'],
                         'title': title, 'units': [{'id': 'one', 'title': 'Task', 'primary_slices': ids,
                                                     'supporting_slices': []}], 'non_teaching': []}
            elif ':source-read:' in group:
                groups.append(group)
                value = {'source_fingerprint': packet.fingerprint,
                         'sections': [{'section': 'Task', 'rules': []}], 'uncertainties': []}
            elif ':author-unit:' in group:
                groups.append(group)
                value = unit_course('SRC1', 'Lesson')
            else:
                raise RuntimeError('stop_before_editors')
            validator(value)
            return value
        with pytest.raises(RuntimeError, match='stop_before_editors'):
            await run_simple_course_editor_v8(packet, corpus, {}, stage)
        return groups
    first, second = await run('Original plan'), await run('Changed plan')
    assert len(first) == len(second) == 2
    assert all(a != b and a.rsplit(':unit=', 1)[-1] == b.rsplit(':unit=', 1)[-1]
               for a, b in zip(first, second, strict=True))
