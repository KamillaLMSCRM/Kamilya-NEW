"""Existing cycle stages preserve separate explanation and answer review."""
import copy
import json

import pytest

from app.modules.ai.v3.practical_arbitration import EXPLANATION_SELECTOR_NAME, MATERIALITY_SELECTOR_NAME
from app.modules.ai.v3.practical_atomic_audit import CLAIM_EVIDENCE_NAME, EXPLANATION_AUDIT_NAME
from app.modules.ai.v3.practical_audit_units import audit_units
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_curriculum import CURRICULUM_BANK_NAME, CURRICULUM_NAME
from app.modules.ai.v3.practical_lesson_cycle import run_lesson_practical_cycle
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_question_context import NAME as CONTEXT_NAME
from app.modules.ai.v3.stage_checkpoint import stage_once
from tests.unit.test_v3_curriculum_cycle import FLAGS
from tests.unit.test_v3_partitioned_extraction import Journal
from tests.unit.test_v3_practical_bank_cycle import bank_value
from tests.unit.test_v3_practical_claim_evidence import response as audit_response

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


async def run_case(case, *, separated=None, explanation_issue=False, answer_issue=False,
                   assessment_issue=False, source_hold=False):
    _, packet, original = case
    course = copy.deepcopy(original)
    if explanation_issue:
        course['lessons'][0]['questions'][0]['explanation'] = 'No approval signature is needed.'
    view = PracticalModelView(packet)
    calls = []
    journal = Journal()

    async def provider(stage, group, messages, fmt, validate):
        name = fmt['json_schema']['name']
        props = fmt['json_schema']['schema']['properties']
        calls.append((stage, group, name, copy.deepcopy(messages), copy.deepcopy(fmt)))
        if name == CURRICULUM_NAME:
            value = {'source_fingerprint': packet.fingerprint, 'sections': [{'title': 'Procedure',
                'source_units': [key for key, _ in audit_units(packet).groups], 'depends_on_units': [],
                'goals': [{'id': 'draft', 'decision': 'Apply source procedure.', 'essential_case_conditions': [],
                           'source_refs': [packet.blocks[0].block_id]}]}],
                'non_teaching_units': [], 'source_uncertainties': []}
        elif stage == 'lesson':
            value = course
        elif name == CONTEXT_NAME:
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course),
                'supplements': {key: '' for key in props['supplements']['properties']},
                'context_source_refs': [], 'unresolved_question_ids': []}
        elif name == CURRICULUM_BANK_NAME:
            text = messages[1]['content']
            body = text.split('\n\nSTANDALONE_QUESTIONS_JSON\n')[1].split('\nPREVIOUS_FINDINGS_JSON\n')[0]
            assert all(set(q) == {'lesson_id', 'id', 'prompt', 'choices'} for q in json.loads(body))
            assert 'correct_index' not in body and 'explanation' not in body
            value = bank_value(packet, course)
            value['curriculum_fingerprint'] = props['curriculum_fingerprint']['enum'][0]
            value['goal_checks'] = [{'goal_id': 'G1', 'status': 'MISSING' if assessment_issue else 'COVERED',
                'source_refs': [packet.blocks[0].block_id], 'question_ids': [] if assessment_issue else ['q1'],
                'assessment_lesson_id': 'l1' if assessment_issue else '', 'reason': 'Independent goal check.'}]
            if answer_issue:
                value['answer_keys']['q2'] = -1
                item = next(x for x in value['answerability'] if x['question_id'] == 'q2')
                item.update(status='UNKNOWN', possible_options=[], reason='Answer needs independent review.')
        elif name in {CLAIM_EVIDENCE_NAME, EXPLANATION_AUDIT_NAME}:
            value = audit_response(packet, course)
            if explanation_issue:
                assert name == EXPLANATION_AUDIT_NAME
                prose = messages[1]['content'].split('\n\nLESSON_PROSE_JSON\n')[1].split('\nQUESTION_EXPLANATIONS_JSON\n')[0]
                assert 'No approval signature is needed.' not in prose
                assert 'No approval signature is needed.' in messages[1]['content'].split('\nQUESTION_EXPLANATIONS_JSON\n')[1]
                value['findings'] = [{'scope': 'question', 'target_id': 'q1', 'review_kind': 'EXPLANATION_VALIDITY',
                    'problem': 'Explanation contradicts the source.', 'source_refs': [packet.blocks[0].block_id],
                    'expected_rule': 'The approver signs the ticket.', 'correction': 'Correct the explanation.'}]
            if source_hold:
                value['source_checks'][0].update(status='UNCERTAIN', reason='Source remains unclear.', evidence=[])
        elif name in {MATERIALITY_SELECTOR_NAME, EXPLANATION_SELECTOR_NAME}:
            body = view.decode(json.loads(messages[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1]))
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course),
                'judgments': [{'issue_id': item['issue_id'],
                    'verdict': 'SOURCE_AMBIGUITY' if item['scope'] == 'source' else 'MATERIAL_ERROR',
                    'reason': 'Independent source review.', 'source_refs': item['evidence']['source_refs'],
                    'course_evidence': [], 'answer_check': {'status': 'NOT_APPLICABLE'}}
                    for item in body['critic_findings']]}
        else:
            pytest.fail(f'Unexpected stage {stage}, {group}, {name}')
        wire = view.encode(value)
        validate(wire)
        return wire

    def dispatcher(bound_journal):
        async def invoke(stage, group, messages, fmt, validate):
            return await stage_once(journal=bound_journal, stage=stage, group_id=group,
                source_sha256='b' * 64, route_fingerprint='c' * 64, messages=messages, response_format=fmt,
                invoke=lambda: provider(stage, group, messages, fmt, validate), response_validator=validate)
        return invoke

    options = {**FLAGS, **({'separate_domains': separated} if separated is not None else {})}
    result = await run_lesson_practical_cycle(packet, {}, dispatcher(journal), max_revisions=0, **options)
    count = len(calls)
    cold = await run_lesson_practical_cycle(packet, {}, dispatcher(copy.copy(journal)), max_revisions=0, **options)
    assert cold == result and len(calls) == count
    return result, calls


@pytest.mark.asyncio
async def test_separate_explanation_and_answer_review_keep_existing_stage_boundaries(case):
    result, calls = await run_case(case, separated=True, explanation_issue=True, answer_issue=True,
                                   assessment_issue=True, source_hold=True)
    names = [call[2] for call in calls]
    assert names.count(CURRICULUM_BANK_NAME) == names.count(EXPLANATION_AUDIT_NAME) == 1
    assert names.count(MATERIALITY_SELECTOR_NAME) == names.count(EXPLANATION_SELECTOR_NAME) == 1
    assert len(calls) == 7
    assert all('source-signoff' not in call[1] for call in calls)
    assert result.decision.source_uncertain and not result.decision.accepted
    assert set(result.decision.question_ids) == {'q1', 'q2'}
    assert result.decision.assessment_lesson_ids == ('l1',)
    assert any(x['evidence'].get('review_kind') == 'EXPLANATION_VALIDITY' and x['id'] == 'q1'
               for x in result.decision.feedback)
    assert any(x['evidence'].get('review_kind') == 'ANSWER_VALIDITY' and x['id'] == 'q2'
               for x in result.decision.feedback)
    assert any(x['scope'] == 'source' for x in result.decision.feedback)


@pytest.mark.asyncio
async def test_old_28_omitted_and_false_have_identical_requests(case):
    old, first = await run_case(case, separated=None)
    explicit, second = await run_case(case, separated=False)
    assert old == explicit and first == second and old.decision.accepted
    assert len(first) == 5 and any(c[2] == CLAIM_EVIDENCE_NAME for c in first)
    assert not any(c[2] in {EXPLANATION_AUDIT_NAME, EXPLANATION_SELECTOR_NAME} for c in first)
