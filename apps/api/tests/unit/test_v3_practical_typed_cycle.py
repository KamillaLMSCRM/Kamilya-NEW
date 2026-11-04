"""P17 routes answer validity and course comparisons to distinct reviewers."""
import copy
import json

import pytest

from app.modules.ai.v3.practical_arbitration import TYPED_SELECTOR_NAME
from app.modules.ai.v3.practical_atomic_audit import TYPED_NAME as AUDIT_NAME
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_lesson_cycle import run_lesson_practical_cycle
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_review import TYPED_STANDALONE_NAME
from tests.unit.test_v3_practical_arbitrated_cycle import clean_audit
from tests.unit.test_v3_practical_standalone_cycle import standalone_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def finding(packet, kind):
    return {'scope': 'question', 'target_id': 'q1', 'review_kind': kind,
            'problem': 'Critic advice: the second choice is correct.',
            'source_refs': [packet.blocks[0].block_id], 'expected_rule': 'Private critic rationale.',
            'correction': 'Private critic correction.'}


@pytest.mark.asyncio
@pytest.mark.parametrize('global_answer', [False, True])
async def test_typed_cycle_separates_same_question_findings_and_rechecks_repair(case, global_answer):
    _, packet, original = case
    original = copy.deepcopy(original)
    original['lessons'][0]['questions'][0]['choices'][:2] = ['Sign only', 'Sign and record']
    view = PracticalModelView(packet)
    repaired = copy.deepcopy(original)
    repaired['lessons'][0]['questions'][0]['correct_index'] = 1
    events = []
    repairs = 0

    async def invoke(stage, group, messages, fmt, validate):
        nonlocal repairs
        name = fmt['json_schema']['name']
        events.append((stage, name))
        current = repaired if repairs else original
        if stage == 'lesson':
            value = original
        elif name == TYPED_STANDALONE_NAME:
            value = standalone_value(packet, current)
            if not repairs and not global_answer:
                value['answerability'][0].update(status='UNIQUE', possible_options=[1])
                value['answer_keys']['q1'] = 1
            props = fmt['json_schema']['schema']['properties']
            if 'issue_checks' in props:
                value['issue_checks'] = {key: {'status': 'RESOLVED', 'reason': 'Rechecked the corrected question.'}
                                         for key in props['issue_checks']['properties']}
        elif name == AUDIT_NAME:
            value = clean_audit(packet, current)
            if not repairs:
                value['findings'] = [finding(packet, 'COURSE_ASSESSMENT')]
                if global_answer:
                    value['findings'].append(finding(packet, 'ANSWER_VALIDITY'))
            props = fmt['json_schema']['schema']['properties']
            if 'issue_checks' in props:
                value['issue_checks'] = {key: {'status': 'RESOLVED', 'reason': 'Rechecked.'}
                                         for key in props['issue_checks']['properties']}
        elif name == TYPED_SELECTOR_NAME:
            sent = view.decode(json.loads(messages[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1]))
            blind = 'standalone_questions' in sent
            if blind:
                assert 'whole_course' not in sent
                assert [q['id'] for q in sent['standalone_questions']] == ['q1']
                for row in sent['critic_findings']:
                    assert set(row) == {'issue_id', 'scope', 'id', 'evidence'}
                    assert row['scope'] == 'question' and row['id'] == 'q1'
                    assert set(row['evidence']) == {'review_kind', 'source_refs'}
                    assert row['evidence']['review_kind'] == 'ANSWER_VALIDITY'
                text = json.dumps(sent)
                assert 'Critic advice' not in text and 'adjudication' not in text and 'correct_index' not in text
                selected = sent['standalone_questions'][0]['prompt']['evidence_id']
            else:
                assert 'whole_course' in sent
                assert all(row['evidence']['review_kind'] == 'COURSE_ASSESSMENT' for row in sent['critic_findings'])
                selected = sent['whole_course']['lessons'][0]['questions'][0]['prompt']['evidence_id']
            rows = []
            for item in sent['critic_findings']:
                verdict = ('ALREADY_COVERED' if repairs else 'MATERIAL_ERROR') if blind else 'STYLE_ONLY'
                rows.append({'issue_id': item['issue_id'], 'verdict': verdict, 'reason': 'Independently checked.',
                             'source_refs': [packet.blocks[0].block_id], 'course_evidence': [selected],
                             'answer_check': {'status': 'UNIQUE', 'question_id': 'q1', 'possible_options': [1],
                                              'source_refs': [packet.blocks[0].block_id], 'reason': 'Both actions are required.'}
                             if blind and repairs else {'status': 'NOT_APPLICABLE'}})
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(current), 'judgments': rows}
        else:
            assert stage == 'repair'
            repairs += 1
            value = {'course_fingerprint': _digest(original), 'new_lessons': [], 'new_questions': [],
                     'question_updates': {'q1': copy.deepcopy(repaired['lessons'][0]['questions'][0])}}
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await run_lesson_practical_cycle(packet, {}, invoke, adjudicate=True, standalone=True, typed_findings=True)
    assert result.decision.accepted and result.stop_reason == 'accepted'
    assert result.course == repaired and repairs == 1 and len(result.history) == 2
    assert not result.history[0]['accepted']
    assert set(result.history[0]['adjudication']) == {'questions', 'course'}
    assert result.history[1]['adjudication']['questions']['judgments'][0]['verdict'] == 'ALREADY_COVERED'
    assert sum(name == TYPED_SELECTOR_NAME for _, name in events) == 3


def test_wrapped_prior_issue_returns_to_its_original_typed_owner(case):
    from app.modules.ai.v3.practical_lesson_cycle import partition_previous

    _, packet, course = case
    def held(issue_id, kind):
        original = {'issue_id': issue_id, 'scope': 'question', 'id': 'q1',
                    'evidence': {'review_kind': kind, 'source_refs': [packet.blocks[0].block_id]}}
        return {'issue_id': issue_id, 'scope': 'source', 'id': packet.blocks[0].block_id,
                'evidence': {'problem': 'NEEDS_REVIEW', 'original_finding': original}}
    answer, comparison = held('answer', 'ANSWER_VALIDITY'), held('comparison', 'COURSE_ASSESSMENT')
    local, global_items = partition_previous(course, packet, (answer, comparison), standalone=True, typed_findings=True)
    assert local == {'l1': (answer,)} and global_items == (comparison,)


@pytest.mark.asyncio
@pytest.mark.parametrize('crash', [False, True])
async def test_p17_service_journal_replay_and_unknown_outcome(case, crash):
    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    from app.modules.ai.v3.practical_service import generate_practical_course
    from app.modules.ai.v3.revision_policy import TYPED_PRACTICAL_REVIEW_POLICY
    from tests.unit.test_v3_partitioned_extraction import Journal

    corpus, packet, course = case
    view = PracticalModelView(packet)
    names = []
    async def invoke(messages, fmt):
        name = fmt['json_schema']['name']
        names.append(name)
        if name == 'practical_course':
            value = course
        elif name == TYPED_STANDALONE_NAME:
            if crash:
                raise TimeoutError('Unknown review outcome')
            value = standalone_value(packet, course)
        else:
            assert name == AUDIT_NAME
            value = clean_audit(packet, course)
        return view.encode(value)

    options = dict(intent=CourseIntent(), invoke=invoke, source_sha256='b' * 64,
                   journal=Journal(), route_fingerprint='c' * 64,
                   review_policy=TYPED_PRACTICAL_REVIEW_POLICY)
    if crash:
        with pytest.raises(TimeoutError):
            await generate_practical_course(corpus, **options)
        with pytest.raises(ExtractionOutcomeUnknownError):
            await generate_practical_course(corpus, **options)
        assert names == ['practical_course', TYPED_STANDALONE_NAME]
    else:
        first = await generate_practical_course(corpus, **options)
        second = await generate_practical_course(corpus, **options)
        assert first.diagnostics == second.diagnostics
        assert first.diagnostics['v3_review_policy'] == TYPED_PRACTICAL_REVIEW_POLICY
        assert first.diagnostics['automated_review_passed']
        assert names == ['practical_course', TYPED_STANDALONE_NAME, AUDIT_NAME]
