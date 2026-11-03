import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_review import (
    CONCISE_NAME,
    CONCISE_REVIEW_SYSTEM,
    interpret_practical_review,
    is_practical_review_format,
    matches_practical_review,
    practical_review_format,
    practical_review_messages,
)
from app.modules.ai.v3.response_contracts import (
    matches_response_contract,
    response_contract,
)
from tests.unit.test_v3_practical_cycle import checked

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def concise_review(packet, course):
    result = checked(packet, course)
    del result['question_rules']
    del result['option_checks']
    result['answerability'] = [
        {'question_id': q['id'], 'possible_options': [q['correct_index']], 'status': 'UNIQUE',
                  'source_refs': q['source_refs'], 'reason': 'Only this answer applies.'}
        for lesson in course['lessons'] for q in lesson['questions']
    ]
    return result


def test_concise_schema_is_closed_and_registered(case):
    _, packet, course = case
    fmt = practical_review_format(packet, course, concise=True)
    props = fmt['json_schema']['schema']['properties']
    assert fmt['json_schema']['name'] == CONCISE_NAME
    assert set(props) == {'source_fingerprint', 'source_review', 'source_notes', 'findings',
                          'answer_keys', 'answerability', 'narrative_sources'}
    assert is_practical_review_format(fmt)
    assert response_contract(fmt) == 'practical_review'
    value = concise_review(packet, course)
    assert matches_response_contract(value, fmt)
    for mutate in ('extra_property', 'extra_enum', 'wrong_name', 'foreign_reference', 'missing_key'):
        tampered_fmt, tampered_value = copy.deepcopy(fmt), copy.deepcopy(value)
        if mutate == 'extra_property':
            tampered_fmt['json_schema']['schema']['properties']['extra'] = {'type': 'string'}
        elif mutate == 'extra_enum':
            tampered_fmt['json_schema']['schema']['properties']['answer_keys']['properties']['q1']['enum'].append(9)
        elif mutate == 'wrong_name':
            tampered_fmt['json_schema']['name'] = 'not-the-versioned-contract'
        elif mutate == 'foreign_reference':
            tampered_value['narrative_sources']['l1'] = ['foreign']
        else:
            del tampered_value['answer_keys']['q1']
        assert not matches_response_contract(tampered_value, tampered_fmt)


@pytest.mark.parametrize(('question_count', 'source_count'), [(50, 276), (100, 300)])
def test_large_concise_schema_passes_shipped_runner_and_canonical_matcher(question_count, source_count):
    source = ''.join(f'Operational source paragraph {i}.\n\n' for i in range(source_count))
    revision = 'document:' + hashlib.sha256(source.encode()).hexdigest()
    doc = DirectSourceDocument('doc', 'Title', 'source.md', 'general', revision, (), source_text=source)
    packet = build_practical_source_packet(DirectSourceCorpus('tenant', (doc,), len(source), 0))
    assert len(packet.blocks) == source_count
    questions = [{'id': f'q{i}', 'prompt': f'Question {i}?', 'choices': ['A', 'B', 'C'],
                  'correct_index': 0, 'explanation': 'Explanation.',
                  'source_refs': [packet.blocks[i].block_id]} for i in range(question_count)]
    lessons = [{'id': f'l{i}', 'title': f'Lesson {i}', 'content': 'Text.', 'questions': questions[i:i + 4]}
               for i in range(0, question_count, 4)]
    course = {'title': 'Course', 'lessons': lessons}
    fmt = practical_review_format(packet, course, concise=True)
    view = PracticalModelView(packet)
    wire_format = view.schema(fmt)
    runner = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('p13_scaled_practical_runner', runner)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._checked_structured_format(wire_format) == wire_format['json_schema']['schema']
    value = concise_review(packet, course)
    assert matches_practical_review(value, fmt)
    assert matches_response_contract(view.encode(value), wire_format)
    assert len(json.dumps(wire_format, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) <= module.MAX_SCHEMA_BYTES


def test_unresolved_key_is_a_question_issue_and_open_prior_survives(case):
    _, packet, course = case
    value = concise_review(packet, course)
    value['answer_keys']['q1'] = -1
    decision = interpret_practical_review(value, packet, course, concise=True)
    assert not decision.accepted and 'q1' in decision.question_ids
    assert any(row['evidence']['problem'] == 'independent_answer_key_mismatch' for row in decision.feedback)
    prior = decision.feedback
    followup = concise_review(packet, course)
    followup['issue_checks'] = {row['issue_id']: {'status': 'OPEN', 'reason': 'Still open.'} for row in prior}
    retained = interpret_practical_review(followup, packet, course, prior, concise=True)
    assert not retained.accepted and retained.feedback == prior
    followup['issue_checks'][prior[0]['issue_id']]['reason'] = ' '
    assert not matches_practical_review(followup, practical_review_format(packet, course, prior, concise=True))


@pytest.mark.parametrize(('status', 'options'), [
    ('UNIQUE', [0, 1]), ('UNIQUE', []), ('UNIQUE', [1]),
    ('DEPENDS', [0]), ('AMBIGUOUS', [0]), ('UNKNOWN', [0]),
])
def test_matching_key_does_not_hide_unresolved_answerability(case, status, options):
    _, packet, course = case
    value = concise_review(packet, course)
    value['answerability'][0].update(status=status, possible_options=options)
    assert value['answer_keys']['q1'] == course['lessons'][0]['questions'][0]['correct_index']
    decision = interpret_practical_review(value, packet, course, concise=True)
    assert not decision.accepted and 'q1' in decision.question_ids
    assert any(row['evidence']['problem'] == 'option_answerability_unresolved' for row in decision.feedback)


@pytest.mark.parametrize('defect', [
    'missing_qid', 'extra_qid', 'duplicate_qid', 'duplicate_options', 'out_of_range', 'foreign_ref',
    'duplicate_refs', 'empty_refs', 'blank_reason', 'invalid_status',
])
def test_answerability_inventory_fails_closed(case, defect):
    _, packet, course = case
    value = concise_review(packet, course)
    item = value['answerability'][0]
    if defect == 'missing_qid':
        del value['answerability'][0]
    elif defect == 'extra_qid':
        item['question_id'] = 'foreign'
    elif defect == 'duplicate_qid':
        value['answerability'][1]['question_id'] = item['question_id']
    elif defect == 'duplicate_options':
        item['possible_options'] = [0, 0]
    elif defect == 'out_of_range':
        item['possible_options'] = [len(course['lessons'][0]['questions'][0]['choices'])]
    elif defect == 'foreign_ref':
        item['source_refs'] = ['foreign']
    elif defect == 'duplicate_refs':
        item['source_refs'] = item['source_refs'] * 2
    elif defect == 'empty_refs':
        item['source_refs'] = []
    elif defect == 'blank_reason':
        item['reason'] = '  '
    else:
        item['status'] = 'MAYBE'
    assert not matches_practical_review(value, practical_review_format(packet, course, concise=True))


def test_concise_prompt_uses_full_blind_input(case):
    _, packet, course = case
    messages = practical_review_messages(packet, course, concise=True)
    assert messages[0]['content'] == CONCISE_REVIEW_SYSTEM
    assert course['lessons'][0]['questions'][0]['prompt'] in messages[1]['content']
    assert 'correct_index' not in messages[1]['content']
    assert 'question_rules' not in practical_review_format(packet, course, concise=True)['json_schema']['schema']['properties']
    assert 'По указанным положениям источника (' not in messages[1]['content']


def test_previous_feedback_is_blind_on_wire_but_remains_authoritative_for_closure(case):
    _, packet, course = case
    value = concise_review(packet, course)
    value['answer_keys']['q1'] = -1
    prior = interpret_practical_review(value, packet, course, concise=True).feedback
    prior[0]['evidence']['nested'] = [{'author_key': 2, 'detail': 'retain', 'reviewer_key': 1,
                                      'possible_options': [0, 1]}]
    original = copy.deepcopy(prior)
    messages = practical_review_messages(packet, course, prior, concise=True)
    wire = json.loads(messages[1]['content'].split('\nPREVIOUS_FINDINGS_JSON\n', 1)[1])
    assert all(key not in messages[1]['content'] for key in ('author_key', 'reviewer_key', 'possible_options'))
    assert wire[0]['issue_id'] == prior[0]['issue_id']
    assert wire[0]['evidence']['source_refs'] == prior[0]['evidence']['source_refs']
    assert wire[0]['evidence']['nested'] == [{'detail': 'retain'}]
    assert all(status in messages[0]['content'] for status in ('RESOLVED', 'OPEN', 'RETRACTED'))
    assert 'недостаточно' in messages[0]['content'] and prior == original
    aliased = practical_review_messages(packet, course, prior, concise=True, model_view=PracticalModelView(packet))
    alias_wire = json.loads(aliased[1]['content'].split('\nPREVIOUS_FINDINGS_JSON\n', 1)[1])
    assert all(key not in aliased[1]['content'] for key in ('author_key', 'reviewer_key', 'possible_options'))
    assert alias_wire[0]['issue_id'] == prior[0]['issue_id']
    assert alias_wire[0]['evidence']['source_refs'][0].startswith('SRC')
    followup = concise_review(packet, course)
    followup['issue_checks'] = {row['issue_id']: {'status': 'OPEN', 'reason': 'Need more context.'} for row in prior}
    decision = interpret_practical_review(followup, packet, course, prior, concise=True)
    assert not decision.accepted and decision.feedback == prior
    assert practical_review_messages(packet, course, prior)[1]['content'].count('author_key') > 0
    assert practical_review_messages(packet, course, prior, legacy_source_rule_scope=True)[1]['content'].count('author_key') > 0
