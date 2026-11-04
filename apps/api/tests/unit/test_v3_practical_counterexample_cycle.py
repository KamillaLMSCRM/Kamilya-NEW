"""A counterexample claim creates review work, never automatic edit authority."""
import json

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.practical_arbitration import TYPED_SELECTOR_NAME
from app.modules.ai.v3.practical_atomic_audit import TYPED_NAME as AUDIT_NAME
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_service import generate_practical_course
from app.modules.ai.v3.revision_policy import COUNTEREXAMPLE_PRACTICAL_REVIEW_POLICY
from tests.unit.test_v3_partitioned_extraction import Journal
from tests.unit.test_v3_practical_arbitrated_cycle import clean_audit
from tests.unit.test_v3_practical_standalone_cycle import standalone_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['FOUND', 'UNKNOWN'])
async def test_fresh_service_arbitrates_counterexample_without_critic_prose_or_automatic_repair(case, status):
    corpus, packet, course = case
    view = PracticalModelView(packet)
    calls = []
    async def invoke(messages, fmt):
        name = fmt['json_schema']['name']
        calls.append(name)
        if name == 'practical_course':
            value = course
        elif name == 'v3_practical_question_review_v14':
            value = standalone_value(packet, course)
            for row in value['answerability']:
                row['counterexample'] = {'status': 'NONE', 'unstated_condition': '',
                    'case_description': '', 'possible_options': [], 'source_refs': []}
            value['answerability'][0]['counterexample'] = {'status': status,
                'unstated_condition': 'UNTRUSTED_CASE' if status == 'FOUND' else '',
                'case_description': 'UNTRUSTED_SCENARIO' if status == 'FOUND' else '',
                'possible_options': [1] if status == 'FOUND' else [],
                'source_refs': [packet.blocks[0].block_id] if status == 'FOUND' else []}
            # Even a raw UNIQUE / matching key cannot erase the counterexample
            # allegation. Conversely its unsupported content must not edit a
            # correct question without the separate independent adjudication.
        elif name == AUDIT_NAME:
            value = clean_audit(packet, course)
        else:
            assert name == TYPED_SELECTOR_NAME
            assert 'Различай дефект вопроса и неясность нормы' in messages[0]['content']
            sent = view.decode(json.loads(messages[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1]))
            assert 'whole_course' not in sent
            assert 'UNTRUSTED_' not in messages[1]['content']
            assert [row['id'] for row in sent['standalone_questions']] == ['q1']
            assert len(sent['critic_findings']) == 1
            prompt = sent['standalone_questions'][0]['prompt']['evidence_id']
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course),
                'judgments': [{'issue_id': sent['critic_findings'][0]['issue_id'], 'verdict': 'ALREADY_COVERED',
                    'reason': 'Independently checked the actual source and question; alleged case does not apply.',
                    'source_refs': [packet.blocks[0].block_id], 'course_evidence': [prompt],
                    'answer_check': {'status': 'UNIQUE', 'question_id': 'q1', 'possible_options': [0],
                        'source_refs': [packet.blocks[0].block_id], 'reason': 'Both actions are explicitly required.'}}]}
        return view.encode(value)

    options = dict(intent=CourseIntent(), invoke=invoke, journal=Journal(), source_sha256='b' * 64,
        route_fingerprint='c' * 64, review_policy=COUNTEREXAMPLE_PRACTICAL_REVIEW_POLICY)
    first = await generate_practical_course(corpus, **options)
    second = await generate_practical_course(corpus, **options)
    assert first.diagnostics == second.diagnostics
    assert first.diagnostics['automated_review_passed']
    assert first.diagnostics['v3_review_policy'] == COUNTEREXAMPLE_PRACTICAL_REVIEW_POLICY
    assert first.diagnostics['practical_course'] == course
    assert calls == ['practical_course', 'v3_practical_question_review_v14', AUDIT_NAME, TYPED_SELECTOR_NAME]


def test_old_arbitration_prompt_is_unchanged_and_unknown_rule_never_becomes_local_edit_authority(case):
    from app.modules.ai.v3.practical_arbitration import arbitration_messages
    from tests.unit.test_v3_practical_review_purpose import typed_allegation

    _, packet, course = case
    decision = typed_allegation(packet, 'ANSWER_VALIDITY')
    options = dict(selectors=True, question_only=True, typed_findings=True)
    old = arbitration_messages(packet, course, decision, **options)
    assert old == arbitration_messages(packet, course, decision, counterexamples=False, **options)
    new = arbitration_messages(packet, course, decision, counterexamples=True, **options)
    assert new[1] == old[1]
    assert 'не разрешает выбрать толкование спорной нормы' in new[0]['content']
