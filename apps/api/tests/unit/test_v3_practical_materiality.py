"""Materiality and missing evidence preserve owned issues, not semantic proof."""
import copy

import pytest

from app.modules.ai.v3.practical_arbitration import (
    MATERIALITY_SELECTOR_NAME,
    adjudicate_practical_findings,
    arbitration_format,
    arbitration_messages,
    evidence_inventory,
    is_arbitration_format,
    matches_arbitration,
)
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_review import PracticalReviewDecision

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def issue(packet, identifier, scope='coverage', target=None, kind=None):
    source = packet.blocks[0].block_id
    evidence = {'problem': 'Alleged omission', 'source_refs': [source]}
    if kind:
        evidence['review_kind'] = kind
    return {'issue_id': identifier, 'scope': scope, 'id': target or source, 'evidence': evidence}


def decision(*items):
    return PracticalReviewDecision(False, False, (), (), False, tuple(items))


def row(item, *, verdict='NON_MATERIAL', evidence=None, answer=None):
    return {'issue_id': item['issue_id'], 'verdict': verdict, 'reason': 'Independent rationale.',
            'source_refs': item['evidence']['source_refs'], 'course_evidence': evidence or [],
            'answer_check': answer or {'status': 'NOT_APPLICABLE'}}


def value(packet, course, rows):
    return {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course), 'judgments': rows}


def apply(packet, course, findings, result, **kwargs):
    return adjudicate_practical_findings(result, packet, course, decision(*findings), {'l1': [packet.blocks[0].block_id]},
        selectors=True, typed_findings=True, materiality_review=True, **kwargs)


def test_mixed_93_retains_three_unproven_issues_and_processes_ninety(case):
    _, packet, course = case
    issues = [issue(packet, f'issue-{i}') for i in range(93)]
    rows = [row(item, verdict='MATERIAL_ERROR') for item in issues]
    for i in (21, 47, 91):
        rows[i]['verdict'] = 'STYLE_ONLY'
    response = value(packet, course, rows)
    opts = {'selectors': True, 'typed_findings': True}
    legacy = arbitration_format(packet, course, decision(*issues), **opts)
    current = arbitration_format(packet, course, decision(*issues), materiality_review=True, **opts)
    assert not matches_arbitration(response, legacy)
    assert matches_arbitration(response, current)
    result = apply(packet, course, issues, response)
    held = [item for item in result.feedback if item['scope'] == 'source']
    assert len(result.feedback) == 93 and len(held) == 3 and result.source_uncertain
    assert {item['issue_id'] for item in held} == {issues[i]['issue_id'] for i in (21, 47, 91)}
    for item in held:
        assert item['evidence']['problem'] == 'NEEDS_REVIEW'
        assert item['evidence']['original_finding']['issue_id'] == item['issue_id']
        assert item['evidence']['adjudication']['verdict'] == 'STYLE_ONLY'
    assert sum(item['scope'] == 'coverage' for item in result.feedback) == 90


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'foreign_issue', 'foreign_source', 'duplicate_source', 'foreign_evidence', 'duplicate_evidence'])
def test_hard_inventory_and_owned_evidence_fences(case, mutation):
    _, packet, course = case
    issues = [issue(packet, 'one'), issue(packet, 'two')]
    rows = [row(item, verdict='MATERIAL_ERROR') for item in issues]
    response = value(packet, course, rows)
    if mutation == 'missing':
        rows.pop()
    elif mutation == 'duplicate':
        rows[1]['issue_id'] = rows[0]['issue_id']
    elif mutation == 'foreign_issue':
        rows[0]['issue_id'] = 'foreign'
    elif mutation == 'foreign_source':
        rows[0]['source_refs'] = ['foreign']
    elif mutation == 'duplicate_source':
        rows[0]['source_refs'] *= 2
    elif mutation == 'foreign_evidence':
        rows[0]['course_evidence'] = ['foreign']
    else:
        key = next(iter(evidence_inventory(course)[0]))
        rows[0]['course_evidence'] = [key, key]
    fmt = arbitration_format(packet, course, decision(*issues), selectors=True, typed_findings=True, materiality_review=True)
    assert not matches_arbitration(response, fmt)
    with pytest.raises(ValueError, match='practical_arbitration_response_invalid'):
        apply(packet, course, issues, response)


def test_source_targeted_nonmaterial_requires_matching_original_reference(case):
    _, packet, course = case
    item = issue(packet, 'coverage')
    assert apply(packet, course, [item], value(packet, course, [row(item)])).accepted
    other = copy.deepcopy(item)
    other['evidence']['source_refs'] = [packet.blocks[-1].block_id]
    held = apply(packet, course, [other], value(packet, course, [row(other)]))
    assert held.source_uncertain and held.feedback[0]['issue_id'] == 'coverage'
    unsupported = row(item)
    unsupported['source_refs'] = [packet.blocks[0].block_id, packet.blocks[-1].block_id]
    assert apply(packet, course, [item], value(packet, course, [unsupported])).source_uncertain


@pytest.mark.parametrize('scope', ['source', 'lesson', 'answer', 'wrapped'])
def test_nonmaterial_cannot_discharge_source_ambiguity_or_other_authority(case, scope):
    _, packet, course = case
    base = issue(packet, 'owned')
    if scope == 'source':
        base['scope'] = 'source'
    elif scope == 'lesson':
        base.update(scope='lesson', id='l1')
    elif scope == 'answer':
        base.update(scope='question', id='q1')
        base['evidence']['review_kind'] = 'ANSWER_VALIDITY'
    else:
        base = {'issue_id': base['issue_id'], 'scope': 'source', 'id': packet.blocks[0].block_id,
                'evidence': {'problem': 'SOURCE_AMBIGUITY', 'source_refs': [packet.blocks[0].block_id],
                             'original_finding': copy.deepcopy(base)}}
    result = apply(packet, course, [base], value(packet, course, [row(base)]), question_only=scope == 'answer')
    assert result.source_uncertain and len(result.feedback) == 1
    assert result.feedback[0]['issue_id'] == 'owned' and not result.question_ids and not result.lesson_ids
    if scope == 'wrapped':
        assert result.feedback[0]['evidence']['problem'] == 'SOURCE_AMBIGUITY'


@pytest.mark.parametrize('scope', ['assessment', 'comparison'])
def test_assessment_nonmaterial_needs_question_and_choice_evidence(case, scope):
    _, packet, course = case
    item = issue(packet, 'assessment', 'assessment', 'l1') if scope == 'assessment' else issue(
        packet, 'assessment', 'question', 'q1', 'COURSE_ASSESSMENT')
    inventory = evidence_inventory(course)[0]
    prompt = next(k for k, v in inventory.items() if v['question_id'] == 'q1' and v['field'] == 'prompt')
    choice = next(k for k, v in inventory.items() if v['question_id'] == 'q1' and v['field'] == 'choice')
    for evidence in ([], [prompt]):
        result = apply(packet, course, [item], value(packet, course, [row(item, evidence=evidence)]))
        assert result.source_uncertain and result.feedback[0]['issue_id'] == 'assessment'
    assert apply(packet, course, [item], value(packet, course, [row(item, evidence=[prompt, choice])])).accepted
    result = apply(packet, course, [item], value(packet, course, [row(item, verdict='MATERIAL_ERROR')]))
    assert not result.accepted and not result.source_uncertain


@pytest.mark.parametrize('check', ['missing', 'unknown', 'wrong_question', 'wrong_key'])
def test_answer_discharge_requires_independent_correct_answer(case, check):
    _, packet, course = case
    item = issue(packet, 'answer', 'question', 'q1', 'ANSWER_VALIDITY')
    inventory = evidence_inventory(course)[0]
    prompt = next(k for k, v in inventory.items() if v['question_id'] == 'q1' and v['field'] == 'prompt')
    answer = {'status': 'UNIQUE', 'question_id': 'q1', 'possible_options': [0],
              'source_refs': [packet.blocks[0].block_id], 'reason': 'Independent check.'}
    if check == 'missing':
        answer = {'status': 'NOT_APPLICABLE'}
    elif check == 'unknown':
        answer['status'] = 'UNKNOWN'
    elif check == 'wrong_question':
        answer['question_id'] = 'q2'
    else:
        answer['possible_options'] = [1]
    opts = {'question_only': check != 'wrong_question'}
    if check == 'wrong_question':
        # The schema's blind question inventory itself rejects a foreign question.
        with pytest.raises(ValueError):
            apply(packet, course, [item], value(packet, course, [row(item, verdict='STYLE_ONLY', evidence=[prompt], answer=answer)]), question_only=True)
        return
    result = apply(packet, course, [item], value(packet, course, [row(item, verdict='STYLE_ONLY', evidence=[prompt], answer=answer)]), **opts)
    assert not result.accepted
    assert result.source_uncertain if check in {'missing', 'unknown'} else result.question_ids == ('q1',)


def test_fresh_schema_prompt_and_legacy_bytes(case):
    _, packet, course = case
    item = issue(packet, 'one')
    options = {'selectors': True, 'typed_findings': True, 'assessment_coverage': True}
    old = arbitration_messages(packet, course, decision(item), **options)
    assert old == arbitration_messages(packet, course, decision(item), materiality_review=False, **options)
    fresh = arbitration_messages(packet, course, decision(item), materiality_review=True, **options)
    assert fresh[1] == old[1] and 'NON_MATERIAL' in fresh[0]['content']
    fmt = arbitration_format(packet, course, decision(item), selectors=True, typed_findings=True, materiality_review=True)
    assert fmt['json_schema']['name'] == MATERIALITY_SELECTOR_NAME and is_arbitration_format(fmt)
    with pytest.raises(ValueError):
        arbitration_format(packet, course, decision(item), selectors=True, materiality_review=True)


@pytest.mark.parametrize('verdict', ['SOURCE_AMBIGUITY', 'NEEDS_REVIEW'])
def test_explicit_source_holds_remain_visible(case, verdict):
    _, packet, course = case
    item = issue(packet, 'source', 'source')
    result = apply(packet, course, [item], value(packet, course, [row(item, verdict=verdict)]))
    assert result.source_uncertain and result.feedback[0]['issue_id'] == 'source'
    assert result.feedback[0]['evidence']['problem'] == verdict


def test_valid_answer_check_can_discharge_but_wrong_owned_question_is_held(case):
    _, packet, course = case
    first = issue(packet, 'first', 'question', 'q1', 'ANSWER_VALIDITY')
    second = issue(packet, 'second', 'question', 'q2', 'ANSWER_VALIDITY')
    inv = evidence_inventory(course)[0]
    prompts = {qid: next(key for key, part in inv.items() if part['question_id'] == qid and part['field'] == 'prompt')
               for qid in ('q1', 'q2')}
    check = {'status': 'UNIQUE', 'question_id': 'q1', 'possible_options': [0],
             'source_refs': [packet.blocks[0].block_id], 'reason': 'Independent check.'}
    rows = [row(first, verdict='ALREADY_COVERED', evidence=[prompts['q1']], answer=check),
            row(second, verdict='ALREADY_COVERED', evidence=[prompts['q2']], answer=check)]
    result = apply(packet, course, [first, second], value(packet, course, rows), question_only=True)
    assert len(result.feedback) == 1 and result.feedback[0]['issue_id'] == 'second'
    assert result.feedback[0]['evidence']['problem'] == 'NEEDS_REVIEW' and result.source_uncertain


def test_rechecked_question_hold_can_clear_without_clearing_unrelated_source_ambiguity(case):
    _, packet, course = case
    answer = issue(packet, 'answer', 'question', 'q1', 'ANSWER_VALIDITY')
    first = apply(packet, course, [answer], value(packet, course, [row(answer, verdict='STYLE_ONLY')]), question_only=True)
    assert first.source_uncertain and first.feedback[0]['evidence']['problem'] == 'NEEDS_REVIEW'
    held_answer = first.feedback[0]
    prompt = next(key for key, item in evidence_inventory(course)[0].items()
                  if item['question_id'] == 'q1' and item['field'] == 'prompt')
    check = {'status': 'UNIQUE', 'question_id': 'q1', 'possible_options': [0],
             'source_refs': [packet.blocks[0].block_id], 'reason': 'Rechecked independently.'}
    cleared = apply(packet, course, [held_answer], value(packet, course, [
        row(held_answer, verdict='ALREADY_COVERED', evidence=[prompt], answer=check)]), question_only=True)
    assert cleared.accepted and not cleared.feedback
    wrong = {**check, 'possible_options': [1]}
    still_held = apply(packet, course, [held_answer], value(packet, course, [
        row(held_answer, verdict='ALREADY_COVERED', evidence=[prompt], answer=wrong)]), question_only=True)
    assert still_held.source_uncertain and still_held.feedback[0]['issue_id'] == 'answer'
    choice = next(key for key, item in evidence_inventory(course)[0].items()
                  if item['question_id'] == 'q1' and item['field'] == 'choice')
    wrong_evidence = apply(packet, course, [held_answer], value(packet, course, [
        row(held_answer, verdict='ALREADY_COVERED', evidence=[choice], answer=check)]), question_only=True)
    assert wrong_evidence.source_uncertain and wrong_evidence.feedback[0]['issue_id'] == 'answer'
    original = issue(packet, 'ambiguity')
    outer = {'issue_id': original['issue_id'], 'scope': 'source', 'id': packet.blocks[0].block_id,
             'evidence': {'problem': 'SOURCE_AMBIGUITY', 'source_refs': [packet.blocks[0].block_id],
                          'original_finding': original}}
    held_source = apply(packet, course, [outer], value(packet, course, [row(outer, verdict='NON_MATERIAL')]))
    assert held_source.source_uncertain and held_source.feedback[0]['issue_id'] == 'ambiguity'
    assert held_source.feedback[0]['evidence']['problem'] == 'SOURCE_AMBIGUITY'


@pytest.mark.parametrize('scope', ['coverage', 'lesson', 'question'])
@pytest.mark.parametrize('verdict', ['MATERIAL_ERROR', 'ALREADY_COVERED', 'STYLE_ONLY',
                                     'NON_MATERIAL', 'SOURCE_AMBIGUITY', 'NEEDS_REVIEW'])
def test_prior_source_ambiguity_cannot_become_editable_from_material_verdict(case, scope, verdict):
    _, packet, course = case
    original = issue(packet, 'ambiguous', scope,
                     'l1' if scope == 'lesson' else 'q1' if scope == 'question' else None,
                     'ANSWER_VALIDITY' if scope == 'question' else None)
    outer = {'issue_id': original['issue_id'], 'scope': 'source', 'id': packet.blocks[0].block_id,
             'evidence': {'problem': 'SOURCE_AMBIGUITY', 'source_refs': [packet.blocks[0].block_id],
                          'original_finding': original}}
    result = apply(packet, course, [outer], value(packet, course, [row(outer, verdict=verdict)]),
                   question_only=scope == 'question')
    assert result.source_uncertain and result.feedback[0]['issue_id'] == 'ambiguous'
    assert result.feedback[0]['evidence']['problem'] == 'SOURCE_AMBIGUITY'
    assert not result.lesson_ids and not result.question_ids and not result.assessment_lesson_ids
    assert not result.allow_new_lessons


def test_nested_source_ambiguity_remains_held(case):
    _, packet, course = case
    original = issue(packet, 'nested')
    prior = {'issue_id': 'nested', 'scope': 'source', 'id': packet.blocks[0].block_id,
             'evidence': {'problem': 'SOURCE_AMBIGUITY', 'source_refs': [packet.blocks[0].block_id],
                          'original_finding': original}}
    outer = {'issue_id': 'nested', 'scope': 'source', 'id': packet.blocks[0].block_id,
             'evidence': {'problem': 'NEEDS_REVIEW', 'source_refs': [packet.blocks[0].block_id],
                          'original_finding': prior}}
    result = apply(packet, course, [outer], value(packet, course, [row(outer, verdict='MATERIAL_ERROR')]))
    assert result.source_uncertain and result.feedback[0]['issue_id'] == 'nested'
    assert result.feedback[0]['evidence']['original_finding']['evidence']['problem'] == 'SOURCE_AMBIGUITY'
    assert not result.lesson_ids and not result.question_ids and not result.allow_new_lessons


@pytest.mark.parametrize('verdict', ['MATERIAL_ERROR', 'ALREADY_COVERED', 'STYLE_ONLY', 'NON_MATERIAL'])
def test_raw_source_issue_never_gains_edit_authority(case, verdict):
    _, packet, course = case
    item = issue(packet, 'raw-source', 'source')
    result = apply(packet, course, [item], value(packet, course, [row(item, verdict=verdict)]))
    assert result.source_uncertain and result.feedback[0]['issue_id'] == 'raw-source'
    assert not result.lesson_ids and not result.question_ids and not result.allow_new_lessons


def test_evidence_deficient_coverage_can_resolve_nonmaterial_without_clearing_ambiguity(case):
    _, packet, course = case
    original = issue(packet, 'coverage')
    first = apply(packet, course, [original], value(packet, course, [row(original, verdict='STYLE_ONLY')]))
    assert first.source_uncertain and first.feedback[0]['evidence']['problem'] == 'NEEDS_REVIEW'
    held = first.feedback[0]
    corrected = apply(packet, course, [held], value(packet, course, [row(held, verdict='NON_MATERIAL')]))
    assert corrected.accepted and not corrected.feedback
    invalid = row(held, verdict='NON_MATERIAL')
    invalid['source_refs'] = [packet.blocks[-1].block_id]
    still_held = apply(packet, course, [held], value(packet, course, [invalid]))
    assert still_held.source_uncertain and still_held.feedback[0]['issue_id'] == 'coverage'
    ambiguity = issue(packet, 'unrelated')
    outer = {'issue_id': ambiguity['issue_id'], 'scope': 'source', 'id': packet.blocks[0].block_id,
             'evidence': {'problem': 'SOURCE_AMBIGUITY', 'source_refs': [packet.blocks[0].block_id],
                          'original_finding': ambiguity}}
    held_ambiguity = apply(packet, course, [outer], value(packet, course, [row(outer, verdict='NON_MATERIAL')]))
    assert held_ambiguity.source_uncertain and held_ambiguity.feedback[0]['issue_id'] == 'unrelated'
