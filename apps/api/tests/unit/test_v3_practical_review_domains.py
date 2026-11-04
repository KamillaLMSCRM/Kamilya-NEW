import copy

import pytest

from app.modules.ai.v3.practical_arbitration import (
    adjudicate_practical_findings,
    original_finding,
    retain_prior_findings,
)
from app.modules.ai.v3.practical_patch import practical_patch_format
from app.modules.ai.v3.practical_review import REVIEW_HOLD_KEY, PracticalReviewDecision
from tests.unit.test_v3_practical_materiality import decision, issue, row, value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def apply(packet, course, items, rows, **kwargs):
    return adjudicate_practical_findings(value(packet, course, rows), packet, course, decision(*items),
        {'l1': [packet.blocks[0].block_id]}, selectors=True, typed_findings=True,
        materiality_review=True, **kwargs)


def test_saved_shape_answer_nonmaterial_is_held_in_question_domain(case):
    _, packet, course = case
    item = issue(packet, 'answer-issue', 'question', 'q1', 'ANSWER_VALIDITY')
    check = {'status': 'UNIQUE', 'question_id': 'q1', 'possible_options': [0],
             'source_refs': [packet.blocks[0].block_id], 'reason': 'Independent check.'}
    judgment = row(item, verdict='NON_MATERIAL', answer=check)
    old = apply(packet, course, [item], [judgment], question_only=True)
    assert old.source_uncertain and old.feedback[0]['scope'] == 'source'
    assert old == apply(packet, course, [item], [judgment], question_only=True, review_domains=False)
    new = apply(packet, course, [item], [judgment], question_only=True, review_domains=True)
    assert not new.accepted and not new.source_uncertain and not new.question_ids
    assert new.feedback[0][REVIEW_HOLD_KEY] is True
    assert new.feedback[0]['issue_id'] == item['issue_id']
    assert new.feedback[0]['evidence']['problem'] == item['evidence']['problem']
    assert new.feedback[0]['evidence']['review_kind'] == 'ANSWER_VALIDITY'
    assert new.feedback[0]['evidence']['adjudication'] == judgment
    assert new.feedback[0]['evidence']['adjudication_spans'] == []


def test_mixed_unproven_scopes_keep_original_owned_repairs(case):
    _, packet, course = case
    items = [issue(packet, 'lesson', 'lesson', 'l1'), issue(packet, 'coverage'),
             issue(packet, 'assessment', 'assessment', 'l1'), issue(packet, 'source', 'source')]
    rows = [row(item, verdict='STYLE_ONLY') for item in items]
    result = apply(packet, course, items, rows, review_domains=True)
    assert [f['issue_id'] for f in result.feedback] == [f['issue_id'] for f in items]
    assert [f['scope'] for f in result.feedback] == ['lesson', 'coverage', 'assessment', 'source']
    assert not result.lesson_ids and not result.assessment_lesson_ids and not result.allow_new_lessons
    assert result.source_uncertain and not result.accepted


@pytest.mark.parametrize('wrapper', ['NEEDS_REVIEW', 'SOURCE_AMBIGUITY'])
def test_existing_wrapper_preserves_uncertainty_only_for_real_source_ambiguity(case, wrapper):
    _, packet, course = case
    item = issue(packet, 'held', 'question', 'q1', 'ANSWER_VALIDITY')
    outer = {'issue_id': item['issue_id'], 'scope': 'source', 'id': packet.blocks[0].block_id,
             'evidence': {'problem': wrapper, 'source_refs': [packet.blocks[0].block_id],
                          'original_finding': copy.deepcopy(item)}}
    judgment = row(outer, verdict='NON_MATERIAL')
    result = apply(packet, course, [outer], [judgment], question_only=True, review_domains=True)
    assert result.feedback[0]['issue_id'] == item['issue_id']
    if wrapper == 'SOURCE_AMBIGUITY':
        assert result.source_uncertain and result.feedback[0]['scope'] == 'source'
        assert original_finding(result.feedback[0])['id'] == 'q1'
    else:
        assert not result.source_uncertain and not result.question_ids
        assert result.feedback[0]['scope'] == 'question'
        assert result.feedback[0][REVIEW_HOLD_KEY] is True


def test_unsupported_answer_and_prior_issue_remain_visible_next_round(case):
    _, packet, course = case
    item = issue(packet, 'answer', 'question', 'q1', 'ANSWER_VALIDITY')
    judgment = row(item, verdict='ALREADY_COVERED')
    first = apply(packet, course, [item], [judgment], question_only=True, review_domains=True)
    assert not first.accepted and not first.question_ids
    carried = retain_prior_findings(PracticalReviewDecision(True, False, (), (), False, ()), first.feedback,
                                    {'answer': {'status': 'OPEN', 'reason': 'Still under review.'}})
    assert carried.feedback[0]['issue_id'] == 'answer'
    assert carried.feedback[0]['scope'] == 'question' and not carried.accepted
    second = apply(packet, course, list(carried.feedback), [row(carried.feedback[0], verdict='NEEDS_REVIEW')],
                   question_only=True, review_domains=True)
    assert not second.question_ids and not second.source_uncertain and not second.accepted
    assert second.feedback[0][REVIEW_HOLD_KEY] is True
    confirmed = apply(packet, course, list(second.feedback), [row(second.feedback[0], verdict='MATERIAL_ERROR')],
                      question_only=True, review_domains=True)
    assert confirmed.question_ids == ('q1',) and REVIEW_HOLD_KEY not in confirmed.feedback[0]


def test_invalid_answer_check_cannot_discharge_or_create_source_ambiguity(case):
    _, packet, course = case
    item = issue(packet, 'answer', 'question', 'q1', 'ANSWER_VALIDITY')
    check = {'status': 'UNIQUE', 'question_id': 'q1', 'possible_options': [3],
             'source_refs': [packet.blocks[0].block_id], 'reason': 'Invalid option.'}
    result = apply(packet, course, [item], [row(item, verdict='ALREADY_COVERED', answer=check)],
                   question_only=True, review_domains=True)
    assert not result.accepted and not result.source_uncertain and not result.question_ids
    assert result.feedback[0]['evidence']['adjudication']['answer_check'] == check


def test_patch_scope_excludes_unconfirmed_coverage_and_question(case):
    _, packet, course = case
    held = issue(packet, 'held-coverage', 'coverage', packet.blocks[-1].block_id)
    held['evidence']['source_refs'] = [packet.blocks[-1].block_id]
    unproved = apply(packet, course, [held], [row(held, verdict='NEEDS_REVIEW')], review_domains=True)
    assert not unproved.allow_new_lessons and not unproved.lesson_ids
    with pytest.raises(ValueError, match='practical_patch_scope_invalid'):
        practical_patch_format(packet, course, unproved)
    confirmed = issue(packet, 'confirmed', 'lesson', 'l1')
    mixed = apply(packet, course, [held, confirmed],
                  [row(held, verdict='NEEDS_REVIEW'), row(confirmed, verdict='MATERIAL_ERROR')], review_domains=True)
    props = practical_patch_format(packet, course, mixed)['json_schema']['schema']['properties']
    assert set(props['lesson_updates']['properties']) == {'l1'}
    assert props['new_lessons']['maxItems'] == 0 and props['new_questions']['maxItems'] == 0
    assert 'question_updates' not in props
    held_q = issue(packet, 'held-question', 'question', 'q1', 'ANSWER_VALIDITY')
    confirmed_q = issue(packet, 'confirmed-question', 'question', 'q2', 'ANSWER_VALIDITY')
    mixed_q = apply(packet, course, [held_q, confirmed_q],
        [row(held_q, verdict='NEEDS_REVIEW'), row(confirmed_q, verdict='MATERIAL_ERROR')],
        question_only=True, review_domains=True)
    qprops = practical_patch_format(packet, course, mixed_q)['json_schema']['schema']['properties']
    assert set(qprops['question_updates']['properties']) == {'q2'}
    assert qprops['new_lessons']['maxItems'] == 0


def test_policy_requires_typed_materiality_selectors(case):
    _, packet, course = case
    item = issue(packet, 'answer', 'question', 'q1', 'ANSWER_VALIDITY')
    response = value(packet, course, [row(item)])
    for kwargs in ({'selectors': False, 'typed_findings': True, 'materiality_review': True},
                   {'selectors': True, 'typed_findings': False, 'materiality_review': True},
                   {'selectors': True, 'typed_findings': True, 'materiality_review': False}):
        with pytest.raises(ValueError, match='review_domains_invalid'):
            adjudicate_practical_findings(response, packet, course, decision(item), {}, review_domains=True, **kwargs)
