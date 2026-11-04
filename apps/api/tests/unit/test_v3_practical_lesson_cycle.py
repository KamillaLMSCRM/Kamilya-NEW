import copy
import json

import pytest

from app.modules.ai.v3.practical_audit_units import audit_units
from app.modules.ai.v3.practical_lesson_cycle import partition_previous, run_lesson_practical_cycle
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_review import LESSON_NAME, interpret_practical_review, practical_review_messages

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def two_lesson_course(course):
    value = copy.deepcopy(course)
    first = value['lessons'][0]
    first['questions'] = [first['questions'][0]]
    second = copy.deepcopy(first)
    second['id'] = 'l2'
    second['title'] = 'Other lesson'
    second['questions'][0]['id'] = 'q2'
    value['lessons'].append(second)
    return value


def test_three_question_lesson_receives_later_source_exception_and_blocks_matching_key():
    from tests.unit.test_v3_practical_question_scope import course_for, packet_for

    packet = packet_for('# 1. Consent\n\n2. Consent at 1000 MRP.\n\n'
                        '# 2. Exception\n\n4. An unmarried applicant submits a declaration.')
    general = next(b.block_id for b in packet.blocks if 'Consent at' in b.text)
    exception = next(b.block_id for b in packet.blocks if 'unmarried' in b.text)
    course = course_for([general])
    question = course['lessons'][0]['questions'][0]
    question['prompt'] = 'What is required at 1000 MRP?'
    course['lessons'][0]['questions'] = [dict(question, id=f'q{i}') for i in range(3)]
    messages = practical_review_messages(packet, course, concise=True, lesson_scoped=True)
    assert 'Consent at 1000 MRP' in messages[1]['content']
    assert 'unmarried applicant submits a declaration' in messages[1]['content']
    refs = [general, exception]
    value = {'source_fingerprint': packet.fingerprint, 'source_review': 'Reviewed.', 'source_notes': [],
        'findings': [], 'answer_keys': {f'q{i}': 0 for i in range(3)}, 'narrative_sources': {'lesson': [general]},
        'answerability': [{'question_id': f'q{i}', 'status': 'DEPENDS' if i == 0 else 'UNIQUE',
            'possible_options': [0, 1] if i == 0 else [0], 'source_refs': refs,
            'reason': 'Marital status changes the answer.' if i == 0 else 'Only one answer.'} for i in range(3)]}
    decision = interpret_practical_review(value, packet, course, concise=True, strict_targets=True)
    assert not decision.accepted and decision.question_ids == ('q0',)


def test_previous_issue_partition_is_exact_and_stale_targets_fail(case):
    _, packet, original = case
    course = two_lesson_course(original)
    ref = packet.blocks[0].block_id
    previous = ({'issue_id': 'i1', 'scope': 'question', 'id': 'q1'},
                {'issue_id': 'i2', 'scope': 'assessment', 'id': 'l2'},
                {'issue_id': 'i3', 'scope': 'coverage', 'id': ref},
                {'issue_id': 'i4', 'scope': 'source', 'id': ref})
    by_lesson, global_items = partition_previous(course, packet, previous)
    assert [item['issue_id'] for item in by_lesson['l1']] == ['i1']
    assert [item['issue_id'] for item in by_lesson['l2']] == ['i2']
    assert [item['issue_id'] for item in global_items] == ['i3', 'i4']
    with pytest.raises(ValueError):
        partition_previous(course, packet, previous + (previous[0],))
    with pytest.raises(ValueError):
        partition_previous(course, packet, ({'issue_id': 'i5', 'scope': 'question', 'id': 'missing'},))


@pytest.mark.asyncio
@pytest.mark.parametrize('change_peer', [True, False])
async def test_peer_patch_keeps_unaffected_review_request_and_no_progress_is_held(case, change_peer):
    _, packet, original = case
    course = two_lesson_course(original)
    view = PracticalModelView(packet)
    source_refs = [b.block_id for b in packet.blocks if b.text.strip()]
    lesson_requests = []
    revisions = {'l1': 0, 'l2': 0}

    async def invoke(stage, group, messages, fmt, validate):
        name = fmt['json_schema']['name']
        if stage == 'lesson':
            value = course
        elif name == LESSON_NAME:
            body = messages[1]['content'].split('\n\nГОТОВЫЙ КУРС. COURSE_JSON\n', 1)[1]
            part = json.loads(body.split('\nPREVIOUS_FINDINGS_JSON\n', 1)[0])
            lesson = part['lessons'][0]
            lid, qid = lesson['id'], lesson['questions'][0]['id']
            revisions[lid] += 1
            lesson_requests.append((lid, group, copy.deepcopy(messages), copy.deepcopy(fmt)))
            is_problem = lid == 'l2' and (revisions[lid] == 1 or not change_peer)
            value = {'source_fingerprint': packet.fingerprint, 'source_review': 'Reviewed.', 'source_notes': [],
                     'findings': [], 'answer_keys': {qid: 0}, 'narrative_sources': {lid: source_refs},
                     'answerability': [{'question_id': qid, 'possible_options': [0, 1] if is_problem else [0],
                         'status': 'DEPENDS' if is_problem else 'UNIQUE', 'source_refs': source_refs,
                         'reason': 'An alternative applies.' if is_problem else 'Only one option applies.'}]}
            props = fmt['json_schema']['schema']['properties']
            if 'issue_checks' in props:
                value['issue_checks'] = {key: {'status': 'RESOLVED', 'reason': 'Addressed.'}
                                         for key in props['issue_checks']['properties']}
        elif name == 'v3_practical_atomic_source_audit_v1':
            value = {'source_fingerprint': packet.fingerprint, 'source_review': 'Reviewed.', 'source_notes': [],
                     'findings': [], 'source_checks': [{'source_refs': [ref], 'status': 'TAUGHT',
                         'lesson_ids': ['l1', 'l2'], 'reason': ''} for _, refs in audit_units(packet).groups for ref in refs]}
        else:
            assert stage == 'repair'
            question = copy.deepcopy(course['lessons'][1]['questions'][0])
            if change_peer:
                question['prompt'] += ' Changed.'
            value = {'course_fingerprint': fmt['json_schema']['schema']['properties']['course_fingerprint']['enum'][0],
                     'new_lessons': [], 'new_questions': [], 'question_updates': {'q2': question}}
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await run_lesson_practical_cycle(packet, {}, invoke, max_revisions=2)
    assert result.lesson_scoped_review and result.concise_review and not result.source_readings
    if change_peer:
        assert result.decision.accepted and result.stop_reason == 'accepted'
        first, second = [row for row in lesson_requests if row[0] == 'l1']
        assert first[1:] == second[1:]
        assert result.course['lessons'][1]['questions'][0]['prompt'].endswith(' Changed.')
    else:
        assert not result.decision.accepted and result.stop_reason == 'no_progress'
        assert result.course == course and len(result.history) == 1
