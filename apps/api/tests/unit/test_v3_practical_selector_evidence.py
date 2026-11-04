"""Evidence is selected from owned spans, never reconstructed by model quotation."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from app.modules.ai.v3.practical_arbitration import (
    adjudicate_practical_findings,
    arbitration_format,
    arbitration_messages,
    evidence_inventory,
)
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.response_contracts import matches_response_contract, response_contract
from tests.unit.test_v3_practical_arbitration import allegation, judgment

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def selector_response(packet, course, decision, ids):
    value = judgment(packet, course, decision)
    value['judgments'][0]['course_evidence'] = ids
    return value


def test_disjoint_owned_passages_need_no_model_retyping(case):
    _, packet, original = case
    course = copy.deepcopy(original)
    first, last = course['lessons'][0]['content'].split('\n\n')
    course['lessons'][0]['content'] = first + '\n\nContext note.\n\n' + last
    decision = allegation(packet)
    inventory, displayed = evidence_inventory(course)
    selected = [key for key, value in inventory.items() if value['field'] == 'content' and value['text'] in {first, last}]
    assert len(selected) == 2
    value = selector_response(packet, course, decision, selected)
    result = adjudicate_practical_findings(value, packet, course, decision,
        {'l1': [packet.blocks[0].block_id]}, selectors=True)
    assert result.accepted and result.feedback == ()
    # The historical v1 claim remains rejected, not silently normalized.
    legacy = judgment(packet, course, decision, field='content')
    legacy['judgments'][0]['course_evidence'][0].update(question_id='', quote=first + '\n\n' + last)
    with pytest.raises(ValueError, match='quote_not_literal'):
        adjudicate_practical_findings(legacy, packet, course, decision, {'l1': [packet.blocks[0].block_id]})
    assert displayed['lessons'][0]['content'][1]['text'] == 'Context note.'


@pytest.mark.parametrize('mutation', ['foreign', 'duplicate', 'wrong_revision'])
def test_selector_identity_and_revision_are_closed(case, mutation):
    _, packet, course = case
    decision = allegation(packet)
    value = selector_response(packet, course, decision, ['E1'])
    if mutation == 'foreign':
        value['judgments'][0]['course_evidence'] = ['FOREIGN']
    elif mutation == 'duplicate':
        value['judgments'][0]['course_evidence'] *= 2
    else:
        value['course_fingerprint'] = '0' * 64
    with pytest.raises(ValueError, match='arbitration'):
        adjudicate_practical_findings(value, packet, course, decision, {'l1': [packet.blocks[0].block_id]}, selectors=True)


def test_selected_field_owner_required_to_discharge_question(case):
    _, packet, course = case
    decision = allegation(packet, scope='question', target='q1')
    inventory, _ = evidence_inventory(course)
    q1 = next(key for key, item in inventory.items() if item['question_id'] == 'q1' and item['field'] == 'prompt')
    value = selector_response(packet, course, decision, [q1])
    value['judgments'][0]['answer_check'] = {'question_id': 'q1', 'status': 'UNIQUE', 'possible_options': [0],
        'source_refs': [packet.blocks[0].block_id], 'reason': 'Both actions are required.'}
    assert adjudicate_practical_findings(value, packet, course, decision,
        {'l1': [packet.blocks[0].block_id]}, selectors=True).accepted
    value['judgments'][0]['course_evidence'] = ['E1']
    with pytest.raises(ValueError, match='answer_check_missing'):
        adjudicate_practical_findings(value, packet, course, decision, {'l1': [packet.blocks[0].block_id]}, selectors=True)


def test_provenance_resolves_exact_original_offsets_and_schema_passes_runner(case):
    _, packet, course = case
    decision = allegation(packet)
    inventory, _ = evidence_inventory(course)
    selected = [key for key, item in inventory.items() if item['field'] == 'content']
    value = selector_response(packet, course, decision, selected)
    value['judgments'][0]['verdict'] = 'MATERIAL_ERROR'
    result = adjudicate_practical_findings(value, packet, course, decision,
        {'l1': [packet.blocks[0].block_id]}, selectors=True)
    for span in result.feedback[0]['evidence']['adjudication_spans']:
        content = course['lessons'][0]['content']
        assert span['text_sha256'] == hashlib.sha256(content[span['start']:span['end']].encode('utf-8')).hexdigest()
    fmt = arbitration_format(packet, course, decision, selectors=True)
    assert response_contract(fmt) == 'practical_arbitration'
    view = PracticalModelView(packet)
    assert matches_response_contract(view.encode(value), view.schema(fmt))
    runner = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('selector_evidence_shipped_runner', runner)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._checked_structured_format(view.schema(fmt)) == view.schema(fmt)['json_schema']['schema']


def test_selector_prompt_embeds_course_text_once_and_explains_standalone_question_scope(case):
    _, packet, course = case
    decision = allegation(packet)
    messages = arbitration_messages(packet, course, decision, selectors=True)
    body = json.loads(messages[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1])
    evidence = body['whole_course']['lessons'][0]['content']
    assert all(set(row) == {'evidence_id', 'text'} for row in evidence)
    assert '\n\n'.join(row['text'] for row in evidence) == course['lessons'][0]['content']
    assert 'correct_index' not in messages[1]['content']
    assert 'отдельно от урока' in messages[0]['content']


def test_question_arbitration_never_receives_hidden_lesson_explanation_or_unrelated_question(case):
    _, packet, original = case
    decision = allegation(packet, scope='question', target='q1')
    def projected(course):
        messages = arbitration_messages(packet, course, decision, selectors=True, question_only=True)
        body = json.loads(messages[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1])
        assert 'whole_course' not in body
        assert len(body['standalone_questions']) == 1
        assert body['standalone_questions'][0]['id'] == 'q1'
        assert 'HIDDEN_LOCALITY' not in messages[1]['content']
        question = body['standalone_questions'][0]
        return {'id': question['id'], 'prompt': question['prompt']['text'],
                'choices': [row['text'] for row in question['choices']]}
    before = projected(original)
    changed = copy.deepcopy(original)
    changed['title'] = changed['lessons'][0]['title'] = 'HIDDEN_LOCALITY'
    changed['lessons'][0]['content'] = 'HIDDEN_LOCALITY\n\nMore hidden context.'
    changed['lessons'][0]['questions'][0]['explanation'] = 'HIDDEN_LOCALITY. The intended key is 2.'
    changed['lessons'][0]['questions'][0]['correct_index'] = 2
    changed['lessons'][0]['questions'][1]['prompt'] = 'HIDDEN_LOCALITY sibling premise.'
    assert projected(changed) == before


def test_question_arbitration_cannot_discharge_using_explanation_or_choice_alone(case):
    _, packet, course = case
    decision = allegation(packet, scope='question', target='q1')
    inventory, _ = evidence_inventory(course)
    explanation = next(key for key, item in inventory.items() if item['question_id'] == 'q1' and item['field'] == 'explanation')
    choice = next(key for key, item in inventory.items() if item['question_id'] == 'q1' and item['field'] == 'choice')
    value = selector_response(packet, course, decision, [explanation])
    value['judgments'][0]['answer_check'] = {'question_id': 'q1', 'status': 'UNIQUE', 'possible_options': [0],
        'source_refs': [packet.blocks[0].block_id], 'reason': 'Both actions are required.'}
    with pytest.raises(ValueError, match='arbitration'):
        adjudicate_practical_findings(value, packet, course, decision,
            {'l1': [packet.blocks[0].block_id]}, selectors=True, question_only=True)
    value['judgments'][0]['course_evidence'] = [choice]
    with pytest.raises(ValueError, match='answer_check_missing'):
        adjudicate_practical_findings(value, packet, course, decision,
            {'l1': [packet.blocks[0].block_id]}, selectors=True, question_only=True)
