"""Unconfirmed findings stay visible without acquiring repair authority."""
import copy
import json

import pytest

from app.modules.ai.v3.practical_arbitration import MATERIALITY_SELECTOR_NAME
from app.modules.ai.v3.practical_atomic_audit import CLAIM_EVIDENCE_NAME
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_lesson_cycle import run_lesson_practical_cycle
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_question_context import NAME as CONTEXT_NAME
from app.modules.ai.v3.practical_review import QUESTION_BATCH_NAME, REVIEW_HOLD_KEY
from tests.unit.test_v3_practical_bank_cycle import bank_value
from tests.unit.test_v3_practical_claim_evidence import response as audit_response

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)
FLAGS = dict(adjudicate=True, standalone=True, typed_findings=True, counterexamples=True,
             explicit_cases=True, question_batch=True, strict_audit_owners=True, exclusive_options=True,
             context_supplemented=True, assessment_coverage=True, materiality_review=True,
             claim_evidence=True, review_domains=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('mixed', [False, True])
async def test_cycle_holds_unproven_issue_without_editing_it(case, mixed):
    _, packet, course = case
    view = PracticalModelView(packet)
    revised = copy.deepcopy(course)
    revised['lessons'][0]['content'] += '\nA confirmed correction.'
    repair_calls = 0
    events = []

    async def invoke(stage, group, messages, fmt, validate):
        nonlocal repair_calls
        name = fmt['json_schema']['name']
        events.append(name)
        current = revised if repair_calls else course
        if stage == 'lesson':
            value = course
        elif name == CONTEXT_NAME:
            props = fmt['json_schema']['schema']['properties']
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(current),
                     'supplements': {key: '' for key in props['supplements']['properties']},
                     'context_source_refs': [], 'unresolved_question_ids': []}
        elif name == QUESTION_BATCH_NAME:
            value = bank_value(packet, current)
        elif name == CLAIM_EVIDENCE_NAME:
            value = audit_response(packet, current)
            if not repair_calls:
                value['findings'] = [{'scope': 'lesson', 'target_id': 'l1', 'problem': 'HELD unproven allegation',
                    'source_refs': [packet.blocks[0].block_id], 'expected_rule': 'Unconfirmed assertion.',
                    'correction': 'Do not silently apply this.'}]
                if mixed:
                    value['findings'].append({'scope': 'lesson', 'target_id': 'l1',
                        'problem': 'CONFIRMED independent issue', 'source_refs': [packet.blocks[-1].block_id],
                        'expected_rule': 'Confirmed requirement.', 'correction': 'Correct the lesson.'})
            props = fmt['json_schema']['schema']['properties']
            if 'issue_checks' in props:
                value['issue_checks'] = {key: {'status': 'OPEN', 'reason': 'Prior issue needs arbitration.'}
                                         for key in props['issue_checks']['properties']}
        elif name == MATERIALITY_SELECTOR_NAME:
            sent = view.decode(json.loads(messages[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1]))
            selected = sent['whole_course']['lessons'][0]['content'][0]['evidence_id']
            rows = []
            for item in sent['critic_findings']:
                problem = item['evidence']['problem']
                verdict = ('NEEDS_REVIEW' if 'HELD' in problem else
                           'ALREADY_COVERED' if repair_calls else 'MATERIAL_ERROR')
                rows.append({'issue_id': item['issue_id'], 'verdict': verdict, 'reason': 'Independent review.',
                    'source_refs': item['evidence']['source_refs'], 'course_evidence': [selected],
                    'answer_check': {'status': 'NOT_APPLICABLE'}})
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(current), 'judgments': rows}
        else:
            assert stage == 'repair' and mixed and not repair_calls
            findings = json.loads(messages[1]['content'].split('\nCHECKED_FINDINGS_JSON\n')[1])
            assert len(findings) == 1 and 'CONFIRMED independent issue' in findings[0]['evidence']['problem']
            assert 'HELD unproven allegation' not in json.dumps(findings)
            props = fmt['json_schema']['schema']['properties']
            assert set(props['lesson_updates']['properties']) == {'l1'}
            assert props['new_lessons']['maxItems'] == 0 and props['new_questions']['maxItems'] == 0
            repair_calls += 1
            value = {'course_fingerprint': _digest(course), 'new_lessons': [], 'new_questions': [],
                     'lesson_updates': {'l1': {'title': course['lessons'][0]['title'], 'replacements': [
                         {'fragment_id': 'F2', 'new_text': revised['lessons'][0]['content'].split('\n\n')[1]}]}}}
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await run_lesson_practical_cycle(packet, {}, invoke, **FLAGS)
    assert repair_calls == int(mixed)
    assert result.stop_reason == 'review_required' and not result.decision.accepted
    assert not result.decision.source_uncertain and result.course == (revised if mixed else course)
    assert len(result.history) == (2 if mixed else 1)
    assert any(item.get(REVIEW_HOLD_KEY) is True and 'HELD' in item['evidence']['problem']
               for item in result.decision.feedback)
    assert any('HELD' in row['problem'] for row in result.history[0]['consolidated_review']['findings'])
