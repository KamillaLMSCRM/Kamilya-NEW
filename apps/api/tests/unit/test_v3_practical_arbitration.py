"""A critic's allegation is not permission to rewrite an otherwise usable course."""
import copy
import json

import pytest

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_review import PracticalReviewDecision

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def allegation(packet, *, scope='assessment', target='l1'):
    feedback = ({'issue_id': 'issue-one', 'scope': scope, 'id': target,
                 'evidence': {'problem': 'Add a dedicated question for every detail.',
                              'source_refs': [packet.blocks[0].block_id]}},)
    return PracticalReviewDecision(False, False, (), (target,) if scope == 'question' else (),
                                   False, feedback, ('l1',) if scope == 'assessment' else ())


def judgment(packet, course, decision, verdict='ALREADY_COVERED', *, field='prompt'):
    return {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course),
            'judgments': [{'issue_id': decision.feedback[0]['issue_id'], 'verdict': verdict,
                'reason': 'The course already tests the complete procedure.',
                'source_refs': [packet.blocks[0].block_id],
                'course_evidence': [{'lesson_id': 'l1', 'question_id': 'q1', 'field': field,
                    'choice_index': -1, 'quote': course['lessons'][0]['questions'][0]['prompt']}],
                'answer_check': {'status': 'NOT_APPLICABLE'}}]}


def test_literal_question_is_valid_evidence_but_wrong_field_is_not(case):
    from app.modules.ai.v3.practical_arbitration import adjudicate_practical_findings

    _, packet, course = case
    decision = allegation(packet)
    value = judgment(packet, course, decision)
    result = adjudicate_practical_findings(value, packet, course, decision, {'l1': [packet.blocks[0].block_id]})
    assert result.accepted and result.feedback == () and result.assessment_lesson_ids == ()
    value['judgments'][0]['course_evidence'][0]['field'] = 'content'
    with pytest.raises(ValueError, match='arbitration'):
        adjudicate_practical_findings(value, packet, course, decision, {'l1': [packet.blocks[0].block_id]})


@pytest.mark.parametrize('mutation', ['foreign', 'duplicate', 'missing', 'wrong_course', 'invented_quote'])
def test_closed_inventory_and_owned_literal_evidence(case, mutation):
    from app.modules.ai.v3.practical_arbitration import adjudicate_practical_findings

    _, packet, course = case
    decision = allegation(packet)
    value = judgment(packet, course, decision)
    if mutation == 'foreign':
        value['judgments'][0]['source_refs'] = ['foreign']
    elif mutation == 'duplicate':
        value['judgments'] *= 2
    elif mutation == 'missing':
        value['judgments'] = []
    elif mutation == 'wrong_course':
        value['course_fingerprint'] = '0' * 64
    else:
        value['judgments'][0]['course_evidence'][0]['quote'] += ' invented'
    with pytest.raises(ValueError, match='arbitration'):
        adjudicate_practical_findings(value, packet, course, decision, {'l1': [packet.blocks[0].block_id]})


def test_ambiguity_holds_without_edit_permission_and_material_keeps_permission(case):
    from app.modules.ai.v3.practical_arbitration import adjudicate_practical_findings

    _, packet, course = case
    decision = allegation(packet)
    narrative = {'l1': [packet.blocks[0].block_id]}
    held = adjudicate_practical_findings(judgment(packet, course, decision, 'SOURCE_AMBIGUITY'),
                                          packet, course, decision, narrative)
    assert held.source_uncertain and not held.accepted
    assert not (held.lesson_ids or held.question_ids or held.assessment_lesson_ids or held.allow_new_lessons)
    assert held.feedback[0]['evidence']['original_finding'] == decision.feedback[0]
    material = adjudicate_practical_findings(judgment(packet, course, decision, 'MATERIAL_ERROR'),
                                              packet, course, decision, narrative)
    assert material.assessment_lesson_ids == ('l1',) and not material.accepted


def test_question_key_allegation_cannot_be_dismissed_by_prose_alone(case):
    from app.modules.ai.v3.practical_arbitration import adjudicate_practical_findings

    _, packet, course = case
    decision = allegation(packet, scope='question', target='q1')
    value = judgment(packet, course, decision)
    narrative = {'l1': [packet.blocks[0].block_id]}
    with pytest.raises(ValueError, match='arbitration'):
        adjudicate_practical_findings(value, packet, course, decision, narrative)
    value['judgments'][0]['answer_check'] = {'question_id': 'q1', 'status': 'UNIQUE',
        'possible_options': [0], 'source_refs': [packet.blocks[0].block_id], 'reason': 'Both actions are required.'}
    assert adjudicate_practical_findings(value, packet, course, decision, narrative).accepted
    value['judgments'][0]['answer_check']['possible_options'] = [0, 1]
    result = adjudicate_practical_findings(value, packet, course, decision, narrative)
    assert not result.accepted and result.question_ids == ('q1',)


def test_request_is_whole_course_and_hides_author_keys(case):
    from app.modules.ai.v3.practical_arbitration import arbitration_messages

    _, packet, course = case
    course = copy.deepcopy(course)
    peer = copy.deepcopy(course['lessons'][0])
    peer['id'] = 'peer'
    peer['content'] = 'The related procedure is taught here.'
    for q in peer['questions']:
        q['id'] += '-peer'
    course['lessons'].append(peer)
    decision = allegation(packet)
    decision.feedback[0]['evidence']['author_key'] = 0
    decision.feedback[0]['evidence']['reviewer_key'] = 1
    decision.feedback[0]['evidence']['possible_options'] = [1]
    messages = arbitration_messages(packet, course, decision)
    assert peer['content'] in messages[1]['content']
    assert 'correct_index' not in messages[1]['content'] and 'author_key' not in messages[1]['content']
    assert 'reviewer_key' not in messages[1]['content'] and 'possible_options' not in messages[1]['content']
    assert 'REFERENCE_CONTEXT' in messages[1]['content'] or packet.blocks[0].text in messages[1]['content']


def test_arbiter_format_is_typed_reconstructable_and_tamper_closed(case):
    from app.modules.ai.v3.practical_arbitration import arbitration_format
    from app.modules.ai.v3.response_contracts import matches_response_contract, response_contract

    _, packet, course = case
    decision = allegation(packet)
    fmt = arbitration_format(packet, course, decision)
    assert response_contract(fmt) == 'practical_arbitration'
    assert matches_response_contract(judgment(packet, course, decision), fmt)
    altered = json.loads(json.dumps(fmt))
    altered['json_schema']['schema']['properties']['judgments']['items']['properties']['verdict']['enum'].append('PASS')
    assert response_contract(altered) is None


def test_later_material_decision_restores_held_question_target(case):
    from app.modules.ai.v3.practical_arbitration import adjudicate_practical_findings

    _, packet, course = case
    original = allegation(packet, scope='question', target='q1')
    narrative = {'l1': [packet.blocks[0].block_id]}
    held = adjudicate_practical_findings(judgment(packet, course, original, 'NEEDS_REVIEW'),
                                          packet, course, original, narrative)
    assert held.source_uncertain and not held.question_ids
    restored = adjudicate_practical_findings(judgment(packet, course, held, 'MATERIAL_ERROR'),
                                              packet, course, held, narrative)
    assert not restored.source_uncertain and restored.question_ids == ('q1',)
    assert restored.feedback[0]['issue_id'] == original.feedback[0]['issue_id']


def test_1000_source_100_question_format_passes_real_shipped_runner(case):
    import importlib.util
    from pathlib import Path

    from app.modules.ai.v3.practical_arbitration import _format

    _, packet, course = case
    fmt = _format(packet.fingerprint, _digest(course), [f'SRC{i}' for i in range(1000)],
                  [f'L{i}' for i in range(25)], [f'Q{i}' for i in range(100)], [f'issue-{i}' for i in range(50)])
    path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('practical_arbitration_shipped_runner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._checked_structured_format(fmt) == fmt['json_schema']['schema']
