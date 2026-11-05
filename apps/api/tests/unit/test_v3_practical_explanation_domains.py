import copy
import json

import pytest

from app.modules.ai.v3.practical_arbitration import (
    EXPLANATION_SELECTOR_NAME,
    adjudicate_practical_findings,
    answer_finding,
    arbitration_format,
    arbitration_messages,
    evidence_inventory,
    is_arbitration_format,
)
from app.modules.ai.v3.practical_atomic_audit import (
    EXPLANATION_AUDIT_NAME,
    atomic_audit_format,
    atomic_audit_messages,
    is_atomic_audit_format,
    validate_atomic_audit,
)
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_review import (
    EXPLANATION_CONSOLIDATED_NAME,
    REVIEW_HOLD_KEY,
    interpret_practical_review,
    is_practical_review_format,
    practical_review_format,
    practical_review_messages,
)
from tests.unit.test_v3_practical_bank_cycle import bank_value
from tests.unit.test_v3_practical_claim_evidence import response as audit_value
from tests.unit.test_v3_practical_materiality import decision, issue, row, value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)
AUDIT = {'typed_findings': True, 'strict_owners': True, 'claim_evidence': True}
ARBITER = {'selectors': True, 'typed_findings': True, 'materiality_review': True}
CONSOLIDATED = {'concise': True, 'allow_empty_narrative': True, 'typed_findings': True, 'counterexamples': True}


def test_atomic_input_separates_explanations_and_versioned_kind(case):
    _, packet, course = case
    old = atomic_audit_messages(packet, course, **AUDIT)
    assert old == atomic_audit_messages(packet, course, **AUDIT, separate_domains=False)
    new = atomic_audit_messages(packet, course, **AUDIT, separate_domains=True)
    body = new[1]['content']
    prose = json.loads(body.split('\n\nLESSON_PROSE_JSON\n')[1].split('\nQUESTION_EXPLANATIONS_JSON\n')[0])
    questions = json.loads(body.split('\nQUESTION_EXPLANATIONS_JSON\n')[1].split('\nPREVIOUS_FINDINGS_JSON\n')[0])
    assert all('answer_explanations' not in lesson for lesson in prose)
    assert questions[0]['question_id'] == 'q1' and questions[0]['explanation'] == course['lessons'][0]['questions'][0]['explanation']
    assert questions[0]['correct_answer_text'] == course['lessons'][0]['questions'][0]['choices'][0]
    fmt = atomic_audit_format(packet, course, **AUDIT, separate_domains=True)
    assert fmt['json_schema']['name'] == EXPLANATION_AUDIT_NAME and is_atomic_audit_format(fmt)
    assert is_atomic_audit_format(PracticalModelView(packet).schema(fmt))
    audit = audit_value(packet, course)
    audit['findings'] = [{'scope': 'question', 'target_id': 'q1', 'review_kind': 'EXPLANATION_VALIDITY',
        'problem': 'Explanation contradicts the source.', 'source_refs': [packet.blocks[0].block_id],
        'expected_rule': 'Source rule.', 'correction': 'Correct explanation.'}]
    assert validate_atomic_audit(audit, packet, course, **AUDIT, separate_domains=True)['findings'] == audit['findings']
    with pytest.raises(ValueError):
        validate_atomic_audit(audit, packet, course, **AUDIT)


def test_explanation_findings_flow_through_new_consolidation_without_unblinding_bank(case):
    _, packet, course = case
    review = bank_value(packet, course)
    review['narrative_sources'] = review.pop('question_sources')
    review['findings'] = [{'scope': 'question', 'target_id': 'q1', 'review_kind': 'EXPLANATION_VALIDITY',
        'problem': 'Wrong explanation.', 'source_refs': [packet.blocks[0].block_id],
        'expected_rule': 'Source rule.', 'correction': 'Correct explanation.'}]
    fmt = practical_review_format(packet, course, **CONSOLIDATED, separate_domains=True)
    assert fmt['json_schema']['name'] == EXPLANATION_CONSOLIDATED_NAME and is_practical_review_format(fmt)
    result = interpret_practical_review(review, packet, course, **CONSOLIDATED, separate_domains=True)
    assert result.feedback[0]['evidence']['review_kind'] == 'EXPLANATION_VALIDITY'
    with pytest.raises(ValueError):
        interpret_practical_review(review, packet, course, **CONSOLIDATED)
    with pytest.raises(ValueError):
        practical_review_format(packet, course, concise=True, strict_targets=True, standalone=True,
            typed_findings=True, counterexamples=True, question_batch=True, separate_domains=True)
    body = practical_review_messages(packet, course, concise=True, strict_targets=True, standalone=True,
        typed_findings=True, counterexamples=True, question_batch=True)[1]['content']
    bank = body.split('\n\nSTANDALONE_QUESTIONS_JSON\n')[1].split('\nPREVIOUS_FINDINGS_JSON\n')[0]
    assert 'explanation' not in bank and 'correct_index' not in bank


@pytest.mark.parametrize('verdict', ['ALREADY_COVERED', 'STYLE_ONLY', 'NON_MATERIAL'])
def test_key_only_cannot_discharge_explanation_issue_but_owned_explanation_can(case, verdict):
    _, packet, course = case
    item = issue(packet, 'explain', 'question', 'q1', 'EXPLANATION_VALIDITY')
    assert not answer_finding(item)
    inventory = evidence_inventory(course)[0]
    prompt = next(k for k, v in inventory.items() if v['question_id'] == 'q1' and v['field'] == 'prompt')
    explanation = next(k for k, v in inventory.items() if v['question_id'] == 'q1' and v['field'] == 'explanation')
    check = {'status': 'UNIQUE', 'question_id': 'q1', 'possible_options': [0],
             'source_refs': [packet.blocks[0].block_id], 'reason': 'Correct key.'}
    bad = value(packet, course, [row(item, verdict=verdict, evidence=[prompt], answer=check)])
    options = {**ARBITER, 'review_domains': True, 'separate_domains': True}
    held = adjudicate_practical_findings(bad, packet, course, decision(item), {}, **options)
    assert not held.accepted and not held.source_uncertain and not held.question_ids
    assert held.feedback[0][REVIEW_HOLD_KEY] is True
    good = value(packet, course, [row(item, verdict=verdict, evidence=[explanation])])
    assert adjudicate_practical_findings(good, packet, course, decision(item), {}, **options).accepted
    wrong_source = copy.deepcopy(good)
    wrong_source['judgments'][0]['source_refs'] = [packet.blocks[-1].block_id]
    assert not adjudicate_practical_findings(wrong_source, packet, course, decision(item), {}, **options).accepted
    fmt = arbitration_format(packet, course, decision(item), **ARBITER, separate_domains=True)
    assert fmt['json_schema']['name'] == EXPLANATION_SELECTOR_NAME and is_arbitration_format(fmt)
    assert is_arbitration_format(PracticalModelView(packet).schema(fmt))


def test_confirmed_explanation_edit_is_only_owned_question_and_unknown_kind_fails(case):
    _, packet, course = case
    item = issue(packet, 'explain', 'question', 'q1', 'EXPLANATION_VALIDITY')
    result = adjudicate_practical_findings(value(packet, course, [row(item, verdict='MATERIAL_ERROR')]),
        packet, course, decision(item), {}, **ARBITER, review_domains=True, separate_domains=True)
    assert result.question_ids == ('q1',) and not result.lesson_ids and not result.assessment_lesson_ids
    with pytest.raises(ValueError):
        arbitration_format(packet, course, decision(item), **ARBITER, question_only=True, separate_domains=True)
    with pytest.raises(ValueError, match='review_kind_invalid'):
        answer_finding(issue(packet, 'invalid', 'question', 'q1', 'UNRECOGNIZED'))
    assert arbitration_messages(packet, course, decision(item), **ARBITER) == arbitration_messages(
        packet, course, decision(item), **ARBITER, separate_domains=False)


def test_mixed_course_assessment_explanation_and_source_hold_preserve_scopes(case):
    _, packet, course = case
    explain = issue(packet, 'explain', 'question', 'q1', 'EXPLANATION_VALIDITY')
    assessment = issue(packet, 'assessment', 'assessment', 'l1')
    source = issue(packet, 'source', 'source')
    items = [explain, assessment, source]
    rows = [row(explain, verdict='MATERIAL_ERROR'), row(assessment, verdict='NON_MATERIAL'),
            row(source, verdict='SOURCE_AMBIGUITY')]
    result = adjudicate_practical_findings(value(packet, course, rows), packet, course, decision(*items), {},
        **ARBITER, review_domains=True, separate_domains=True)
    assert result.question_ids == ('q1',) and not result.assessment_lesson_ids
    assert result.source_uncertain and not result.accepted
    assert {item['issue_id'] for item in result.feedback} == {'explain', 'assessment', 'source'}
    assert next(item for item in result.feedback if item['issue_id'] == 'assessment')[REVIEW_HOLD_KEY] is True
