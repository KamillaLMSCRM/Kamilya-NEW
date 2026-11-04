"""A question target does not determine which context its editor needs."""
import copy
import json
from dataclasses import replace

import pytest

from app.modules.ai.v3.practical_arbitration import (
    adjudicate_practical_findings,
    arbitration_messages,
    evidence_inventory,
)
from tests.unit.test_v3_practical_arbitration import allegation, judgment

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def typed_allegation(packet, kind):
    result = allegation(packet, scope='question', target='q1')
    result.feedback[0]['evidence']['review_kind'] = kind
    return result


def test_course_comparison_has_peer_evidence_without_requiring_hidden_key_comparison(case):
    _, packet, course = case
    decision = typed_allegation(packet, 'COURSE_ASSESSMENT')
    inventory, _ = evidence_inventory(course)
    value = judgment(packet, course, decision)
    value['judgments'][0].update(course_evidence=[key for key, item in inventory.items() if item['field'] == 'prompt'],
                                answer_check={'status': 'NOT_APPLICABLE'}, verdict='STYLE_ONLY')
    final = adjudicate_practical_findings(value, packet, course, decision, {'l1': [packet.blocks[0].block_id]},
        selectors=True, typed_findings=True)
    assert final.accepted
    messages = arbitration_messages(packet, course, decision, selectors=True, typed_findings=True)
    body = json.loads(messages[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1])
    assert len(body['whole_course']['lessons'][0]['questions']) == 2
    assert 'correct_index' not in messages[1]['content']
    with pytest.raises(ValueError):
        arbitration_messages(packet, course, decision, selectors=True, question_only=True, typed_findings=True)


@pytest.mark.parametrize('kind', [None, 'UNKNOWN', 'answer_validity'])
def test_question_purpose_cannot_be_guessed_from_free_text(case, kind):
    _, packet, course = case
    decision = typed_allegation(packet, kind)
    with pytest.raises(ValueError, match='kind|purpose'):
        arbitration_messages(packet, course, decision, selectors=True, typed_findings=True)


def test_held_question_keeps_its_original_purpose_and_owner(case):
    from app.modules.ai.v3.practical_lesson_cycle import partition_previous

    _, packet, course = case
    validity = typed_allegation(packet, 'ANSWER_VALIDITY').feedback[0]
    comparison = copy.deepcopy(validity)
    comparison.update(issue_id='comparison-one')
    comparison['evidence']['review_kind'] = 'COURSE_ASSESSMENT'
    held = {'issue_id': comparison['issue_id'], 'scope': 'source', 'id': packet.blocks[0].block_id,
        'evidence': {'problem': 'NEEDS_REVIEW', 'original_finding': comparison}}
    grouped, global_items = partition_previous(course, packet, (validity, held), standalone=True, typed_findings=True)
    assert grouped['l1'] == (validity,)
    assert global_items == (held,)
    # Neither moving the same question's comparison to the course editor nor
    # closing it may silently remove this separately owned answer allegation.
    decision = replace(typed_allegation(packet, 'ANSWER_VALIDITY'), feedback=(validity, held))
    assert decision.feedback[0]['issue_id'] != decision.feedback[1]['issue_id']


@pytest.mark.parametrize('held', [False, True])
def test_blind_answer_editor_cannot_receive_course_context_through_critic_prose(case, held):
    _, packet, course = case
    decision = typed_allegation(packet, 'ANSWER_VALIDITY')
    item = decision.feedback[0]
    item['evidence'].update(problem='HIDDEN_LESSON_TEXT', expected_rule='HIDDEN_AUTHOR_KEY',
                            correction='HIDDEN_NEIGHBOR_QUESTION',
                            adjudication={'reason': 'HIDDEN_PRIOR_EXPLANATION'})
    if held:
        wrapped = {'issue_id': item['issue_id'], 'scope': 'source', 'id': packet.blocks[0].block_id,
                   'evidence': {'problem': 'NEEDS_REVIEW', 'original_finding': item,
                                'critic_check': {'reason': 'HIDDEN_RECHECK_ADVICE'}}}
        decision = replace(decision, feedback=(wrapped,))
    messages = arbitration_messages(packet, course, decision, selectors=True,
                                     question_only=True, typed_findings=True)
    assert 'HIDDEN_' not in messages[1]['content']
    body = json.loads(messages[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1])
    assert body['critic_findings'] == [{'issue_id': item['issue_id'], 'scope': 'question', 'id': 'q1',
        'evidence': {'review_kind': 'ANSWER_VALIDITY', 'source_refs': item['evidence']['source_refs']}}]
    assert set(body) == {'course_fingerprint', 'critic_findings', 'standalone_questions'}
