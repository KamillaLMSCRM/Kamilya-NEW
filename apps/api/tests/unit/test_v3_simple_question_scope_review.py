import copy
import importlib.util
import json
from pathlib import Path

import pytest

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.simple_course_editor import _source_context
from app.modules.ai.v3.simple_question_scope_review import (
    compile_question_scope_review,
    is_simple_question_scope_format,
    matches_simple_question_scope,
    question_scope_request,
)
from tests.unit.test_v3_simple_course_editor import course, fixture
from tests.unit.test_v3_simple_course_editor_v2 import approved_fixture


def setup_review():
    corpus, packet = fixture()
    original = course(ref=packet.blocks[0].block_id, content='HIDDEN_BODY_SENTINEL')
    original['lessons'][0]['title'] = 'VISIBLE_HEADING'
    original['lessons'][0]['questions'][0]['explanation'] = 'HIDDEN_EXPLANATION_SENTINEL'
    _, context = _source_context(packet, corpus, {'audience': 'staff'})
    view = PracticalModelView(packet)
    before = copy.deepcopy(original)
    messages, fmt, visible = question_scope_request(packet, original, context, view)
    assert original == before
    return packet, original, messages, fmt, visible, context, view


def response(packet, visible, *, status='UNIQUE', counterexample='NONE'):
    ref = packet.blocks[0].block_id
    case = {'status': counterexample, 'unstated_condition': '', 'case_description': '', 'possible_options': [], 'source_refs': []}
    if counterexample == 'FOUND':
        case.update(unstated_condition='applicability', case_description='alternative case', possible_options=[1], source_refs=[ref])
    return {'source_fingerprint': packet.fingerprint, 'bank_fingerprint': _digest(visible),
            'source_review': 'source checked', 'source_notes': [], 'findings': [],
            'answerability': [{'question_id': 'question', 'possible_options': [0], 'status': status,
                'source_refs': [ref], 'reason': 'source conditions', 'counterexample': case}],
            'answer_keys': {'question': 0}, 'question_sources': {'lesson': [ref]}}


def test_wire_format_is_registered_before_transport():
    from app.modules.ai.v3.response_contracts import matches_response_contract, response_contract

    packet, _, _, fmt, visible, _, view = setup_review()
    assert response_contract(fmt) == 'simple_question_scope_review'
    assert matches_response_contract(view.encode(response(packet, visible)), fmt)
    stale = response(packet, visible)
    stale['bank_fingerprint'] = '0' * 64
    assert not matches_response_contract(view.encode(stale), fmt)


def test_standalone_payload_uses_visible_title_and_hides_author_state():
    packet, original, messages, fmt, visible, context, view = setup_review()
    text = messages[1]['content']
    bank = json.loads(text.split('\n\nSTANDALONE_QUESTIONS_JSON\n', 1)[1].split('\nPREVIOUS_FINDINGS_JSON\n', 1)[0])
    assert 'Visible quiz title: VISIBLE_HEADING' in bank[0]['prompt']
    assert set(bank[0]) == {'lesson_id', 'id', 'prompt', 'choices'}
    assert all(term not in text for term in ['HIDDEN_BODY_SENTINEL', 'HIDDEN_EXPLANATION_SENTINEL', 'correct_index'])
    assert packet.blocks[0].block_id not in text
    assert 'Interpret as conditional' in text and 'persistently visible' in messages[0]['content']
    assert text.count('If approved: UNIQUE_SENTINEL') == 1
    assert fmt['json_schema']['name'] == 'simple_question_scope_review_v1'
    assert is_simple_question_scope_format(fmt)
    assert matches_simple_question_scope(view.encode(response(packet, visible)), fmt)


def test_wire_schema_is_accepted_by_shipped_producer():
    _, _, _, fmt, _, _, _ = setup_review()
    path = Path(__file__).resolve().parents[4] / 'infra/codex-reserve/runner.py'
    spec = importlib.util.spec_from_file_location('scope_review_runner', path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    assert runner._checked_structured_format(fmt) == fmt['json_schema']['schema']


def test_replacement_reason_survives_without_superseded_quote_or_offsets():
    corpus, packet, _ = approved_fixture()
    original = course(ref=packet.blocks[0].block_id)
    _, context = _source_context(packet, corpus, {})
    messages, _, _ = question_scope_request(packet, original, context, PracticalModelView(packet))
    text = messages[1]['content']
    assert 'replacement interpretation reason' in text and 'keep interpretation reason' in text
    assert 'OLD_PRIVATE_WORD' not in text and 'CURRENT_WORD' in text
    assert '"start"' not in text and '"end"' not in text


def test_context_is_bound_to_current_packet():
    packet, original, _, _, _, context, view = setup_review()
    context['source_fingerprint'] = '0' * 64
    with pytest.raises(ValueError, match='simple_scope_context_invalid'):
        question_scope_request(packet, original, context, view)


@pytest.mark.parametrize(('status', 'counterexample', 'proposal', 'observation'), [
    ('UNIQUE', 'NONE', 0, 0), ('DEPENDS', 'FOUND', 1, 1), ('UNKNOWN', 'UNKNOWN', 1, 1),
    ('UNIQUE', 'FOUND', 1, 1),
])
def test_counterexample_and_unknown_are_question_observations(status, counterexample, proposal, observation):
    packet, original, _, _, visible, _, _ = setup_review()
    value = response(packet, visible, status=status, counterexample=counterexample)
    review, evidence = compile_question_scope_review(value, packet, original, visible)
    assert len(review['proposals']) == proposal and review['source_questions'] == []
    assert len(evidence['unverified_observations']) == observation
    assert evidence['answerability'][0]['counterexample']['status'] == counterexample
    assert not evidence['semantic_approval']


def test_genuine_source_finding_is_separate_from_card_ambiguity():
    packet, original, _, _, visible, _, _ = setup_review()
    value = response(packet, visible)
    ref = packet.blocks[0].block_id
    value['findings'] = [{'scope': 'source', 'target_id': ref, 'problem': 'source unresolved',
                          'source_refs': [ref], 'expected_rule': 'rule', 'correction': 'clarify'}]
    review, _ = compile_question_scope_review(value, packet, original, visible)
    assert review['source_questions'] == [{'question': 'source unresolved', 'source_refs': [ref]}]
    assert review['proposals'] == []


@pytest.mark.parametrize('fault', ['foreign_question', 'foreign_source', 'stale_source', 'stale_bank', 'stale_visible', 'changed_original'])
def test_foreign_and_stale_inputs_are_rejected(fault):
    packet, original, _, _, visible, _, _ = setup_review()
    value = response(packet, visible)
    if fault == 'foreign_question':
        value['answerability'][0]['question_id'] = 'foreign'
    elif fault == 'foreign_source':
        value['answerability'][0]['source_refs'] = ['foreign']
    elif fault == 'stale_source':
        value['source_fingerprint'] = '0' * 64
    elif fault == 'stale_bank':
        value['bank_fingerprint'] = '0' * 64
    elif fault == 'changed_original':
        original['lessons'][0]['questions'][0]['prompt'] = 'changed but same identity'
        visible['lessons'][0]['questions'][0]['prompt'] = 'Visible quiz title: VISIBLE_HEADING\nQuestion: changed but same identity'
    else:
        visible['lessons'][0]['questions'][0]['prompt'] = 'foreign'
    with pytest.raises(ValueError):
        compile_question_scope_review(value, packet, original, visible)
