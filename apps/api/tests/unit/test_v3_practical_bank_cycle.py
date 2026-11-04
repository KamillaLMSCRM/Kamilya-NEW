"""Question-bank review through the real service and practical cycle."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.managed_luna_client import ManagedLunaClient
from app.modules.ai.v3.practical_arbitration import TYPED_SELECTOR_NAME
from app.modules.ai.v3.practical_atomic_audit import TYPED_NAME as AUDIT_NAME
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_lesson_cycle import run_lesson_practical_cycle
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_review import (
    QUESTION_BATCH_NAME,
    interpret_practical_review,
    practical_review_format,
    practical_review_messages,
)
from app.modules.ai.v3.practical_service import generate_practical_course
from app.modules.ai.v3.stage_checkpoint import stage_once
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_v3_partitioned_extraction import Journal
from tests.unit.test_v3_practical_arbitrated_cycle import clean_audit
from tests.unit.test_v3_practical_counterexamples import counterexample
from tests.unit.test_v3_practical_standalone_cycle import standalone_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)
POLICY = 'v3-practical-source-review-v20'


@pytest.fixture
def two_lessons(case):
    corpus, packet, original = case
    course = copy.deepcopy(original)
    peer = copy.deepcopy(course['lessons'][0])
    peer['id'] = 'l2'
    peer['title'] = 'Other lesson title is hidden'
    peer['content'] = 'Hidden lesson prose.'
    for question in peer['questions']:
        question['id'] += '-peer'
    course['lessons'].append(peer)
    return corpus, packet, course


def bank_value(packet, course):
    value = standalone_value(packet, course)
    for row in value['answerability']:
        row['counterexample'] = counterexample()
    return value


def assert_blind_bank(messages):
    body = messages[1]['content'].split('\n\nSTANDALONE_QUESTIONS_JSON\n')[1].split('\nPREVIOUS_FINDINGS_JSON\n')[0]
    bank = json.loads(body)
    assert len(bank) == 4
    assert {q['lesson_id'] for q in bank} == {'l1', 'l2'}
    assert all(set(q) == {'lesson_id', 'id', 'prompt', 'choices'} for q in bank)
    assert 'Hidden lesson prose' not in body and 'correct_index' not in body and 'explanation' not in body


@pytest.mark.asyncio
async def test_service_reviews_two_lessons_in_one_bank_and_replays_journal(two_lessons):
    corpus, packet, course = two_lessons
    view = PracticalModelView(packet)
    names = []

    async def invoke(messages, fmt):
        name = fmt['json_schema']['name']
        names.append(name)
        if name == 'practical_course':
            value = course
        elif name == QUESTION_BATCH_NAME:
            assert_blind_bank(messages)
            value = bank_value(packet, course)
        else:
            assert name == AUDIT_NAME
            value = clean_audit(packet, course)
        return view.encode(value)

    options = dict(intent=CourseIntent(), invoke=invoke, source_sha256='b' * 64,
                   journal=Journal(), route_fingerprint='c' * 64, review_policy=POLICY)
    first = await generate_practical_course(corpus, **options)
    replay = await generate_practical_course(corpus, **options)
    assert first.diagnostics == replay.diagnostics
    assert first.diagnostics['v3_review_policy'] == POLICY
    assert first.diagnostics['automated_review_passed'] and first.diagnostics['practical_course'] == course
    assert names == ['practical_course', QUESTION_BATCH_NAME, AUDIT_NAME]


@pytest.mark.asyncio
@pytest.mark.parametrize('repair_type', ['prose', 'key'])
async def test_hidden_only_repair_reuses_bank_but_requires_fresh_arbitration(two_lessons, repair_type):
    _, packet, original = two_lessons
    view = PracticalModelView(packet)
    course = copy.deepcopy(original)
    if repair_type == 'key':
        course['lessons'][0]['questions'][0]['choices'][:2] = ['Sign only', 'Sign and record']
    repaired = copy.deepcopy(course)
    if repair_type == 'key':
        repaired['lessons'][0]['questions'][0]['correct_index'] = 1
    else:
        repaired['lessons'][0]['content'] += '\nRestore the recording requirement.'
    events = []
    repairs = 0
    adjudications = 0

    async def invoke(stage, group, messages, fmt, validate):
        nonlocal repairs, adjudications
        name = fmt['json_schema']['name']
        events.append(name)
        current = repaired if repairs else course
        if stage == 'lesson':
            value = course
        elif name == QUESTION_BATCH_NAME:
            assert_blind_bank(messages)
            assert group.startswith('practical:review:bank:')
            value = bank_value(packet, course)
            if repair_type == 'key':
                value['answer_keys']['q1'] = 1
                value['answerability'][0]['possible_options'] = [1]
        elif name == AUDIT_NAME:
            value = clean_audit(packet, current)
            if not repairs and repair_type == 'prose':
                value['findings'] = [{'scope': 'lesson', 'target_id': 'l1', 'problem': 'Recording omitted.',
                    'source_refs': [packet.blocks[-1].block_id], 'expected_rule': 'Record approval.',
                    'correction': 'Restore recording.'}]
            props = fmt['json_schema']['schema']['properties']
            if 'issue_checks' in props:
                value['issue_checks'] = {key: {'status': 'RESOLVED', 'reason': 'Checked after repair.'}
                                         for key in props['issue_checks']['properties']}
        elif name == TYPED_SELECTOR_NAME:
            adjudications += 1
            sent = view.decode(json.loads(messages[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1]))
            blind = 'standalone_questions' in sent
            assert blind is (repair_type == 'key')
            selected = (sent['standalone_questions'][0]['prompt']['evidence_id'] if blind else
                        sent['whole_course']['lessons'][0]['content'][0]['evidence_id'])
            rows = []
            for item in sent['critic_findings']:
                check = ({'question_id': 'q1', 'status': 'UNIQUE', 'possible_options': [1],
                          'source_refs': [packet.blocks[0].block_id], 'reason': 'Both actions are required.'}
                         if repairs and blind else {'status': 'NOT_APPLICABLE'})
                rows.append({'issue_id': item['issue_id'], 'verdict': 'ALREADY_COVERED' if repairs else 'MATERIAL_ERROR',
                             'reason': 'Independently checked.', 'source_refs': [packet.blocks[0].block_id],
                             'course_evidence': [selected], 'answer_check': check})
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(current), 'judgments': rows}
        else:
            assert stage == 'repair'
            repairs += 1
            value = {'course_fingerprint': _digest(course), 'new_lessons': [], 'new_questions': []}
            if repair_type == 'key':
                value['question_updates'] = {'q1': copy.deepcopy(repaired['lessons'][0]['questions'][0])}
            else:
                value['lesson_updates'] = {'l1': {'title': course['lessons'][0]['title'], 'replacements': [
                    {'fragment_id': 'F2', 'new_text': repaired['lessons'][0]['content'].split('\n\n')[1]}]}}
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await run_lesson_practical_cycle(packet, {}, invoke, adjudicate=True, standalone=True,
                                               typed_findings=True, counterexamples=True, explicit_cases=True, question_batch=True)
    assert result.course == repaired and result.decision.accepted and repairs == 1
    assert events.count(QUESTION_BATCH_NAME) == 1 and adjudications == 2
    assert not result.history[0]['accepted'] and result.history[1]['accepted']
    if repair_type == 'key':
        carried = result.history[1]['carried_reviews'][0]['open_issue_ids']
        checks = result.history[1]['consolidated_review']['issue_checks']
        assert len(carried) == 1 and checks[carried[0]]['status'] == 'OPEN'
        assert result.history[1]['adjudication']['questions']['judgments'][0]['issue_id'] == carried[0]


@pytest.mark.asyncio
async def test_bank_findings_once_and_question_sources_do_not_prove_prose(two_lessons):
    _, packet, course = two_lessons
    view = PracticalModelView(packet)

    async def invoke(stage, group, messages, fmt, validate):
        name = fmt['json_schema']['name']
        if stage == 'lesson':
            value = course
        elif name == QUESTION_BATCH_NAME:
            assert_blind_bank(messages)
            value = bank_value(packet, course)
            value['source_notes'] = [{'note': 'Single source note.', 'source_refs': [packet.blocks[0].block_id]}]
            value['findings'] = [
                {'scope': 'question', 'target_id': 'q1-peer', 'review_kind': 'ANSWER_VALIDITY',
                 'problem': 'Peer question has an issue.', 'source_refs': [packet.blocks[0].block_id],
                 'expected_rule': 'Check independently.', 'correction': 'Clarify the question.'},
                {'scope': 'source', 'target_id': packet.blocks[0].block_id, 'problem': 'Single source allegation.',
                 'source_refs': [packet.blocks[0].block_id], 'expected_rule': 'Clear source.',
                 'correction': 'Request clarification.'},
            ]
        elif name == AUDIT_NAME:
            value = clean_audit(packet, course)
            for row in value['source_checks']:
                row.update(status='UNCERTAIN', lesson_ids=[], reason='Prose coverage is not verified.')
        else:
            assert name == TYPED_SELECTOR_NAME
            sent = view.decode(json.loads(messages[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1]))
            blind = 'standalone_questions' in sent
            if blind:
                assert [q['id'] for q in sent['standalone_questions']] == ['q1-peer']
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course),
                     'judgments': [{'issue_id': row['issue_id'], 'verdict': 'MATERIAL_ERROR' if blind else 'NEEDS_REVIEW',
                        'reason': 'Independently checked.', 'source_refs': [packet.blocks[0].block_id],
                        'course_evidence': [], 'answer_check': {'status': 'NOT_APPLICABLE'}}
                        for row in sent['critic_findings']]}
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await run_lesson_practical_cycle(packet, {}, invoke, adjudicate=True, standalone=True,
                                               typed_findings=True, counterexamples=True, explicit_cases=True, question_batch=True,
                                               max_revisions=0)
    review = result.history[0]['consolidated_review']
    assert sum(item['problem'] == 'Peer question has an issue.' for item in review['findings']) == 1
    assert sum(item['problem'] == 'Single source allegation.' for item in review['findings']) == 1
    assert sum(item['note'] == 'Single source note.' for item in review['source_notes']) == 1
    assert review['source_review'].count('Checked all applicable rules.') == 1
    parts = result.history[0]['lesson_reviews']
    assert not any(row['scope'] == 'question' for row in parts[0]['findings'])
    assert [row['target_id'] for row in parts[1]['findings'] if row['scope'] == 'question'] == ['q1-peer']
    assert review['narrative_sources'] == {'l1': [], 'l2': []}
    assert result.decision.source_uncertain and not result.decision.accepted


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['direct', 'managed'])
async def test_bank_owned_checkpoint_replays_and_rejects_unowned_prefix(two_lessons, monkeypatch, provider):
    _, packet, course = two_lessons
    fake, journal, client, _, _ = setup()
    model = 'gpt-6-luna'
    if provider == 'managed':
        client = ManagedLunaClient(base_url='http://127.0.0.1:18999/v1', api_key='synthetic',
            tenant_id=UUID(journal.tenant_id), user_id=journal.user_id, job_id=journal.job_id,
            credential_revision='synthetic')
        model = 'gpt-5.6-luna'
    view = PracticalModelView(packet)
    flags = dict(concise=True, strict_targets=True, standalone=True, typed_findings=True,
                 counterexamples=True, question_batch=True)
    fmt = view.schema(practical_review_format(packet, course, **flags))
    messages = practical_review_messages(packet, course, model_view=view, **flags)
    wire = view.encode(bank_value(packet, course))
    assert fmt['json_schema']['name'] == QUESTION_BATCH_NAME
    prepare = AsyncMock(return_value=object())
    invoke = AsyncMock(return_value=SimpleNamespace(content=wire, model=model,
        usage=SimpleNamespace(input_tokens=12, output_tokens=6, cached_input_tokens=None, reasoning_tokens=None)))
    monkeypatch.setattr(client, 'prepare', prepare)
    monkeypatch.setattr(client, 'invoke', invoke)
    def validate(value):
        interpret_practical_review(view.decode(value), packet, course, **flags)
    options = dict(journal=journal, direct_client=client, stage='review',
                   group_id='practical:review:bank:' + 'a' * 64, source_sha256='b' * 64,
                   route_fingerprint=client.cache_fingerprint(), messages=messages, response_format=fmt,
                   direct_max_output_tokens=128, response_validator=validate, invoke=AsyncMock())
    with pytest.raises(ValueError, match='direct_owned_format_invalid'):
        await stage_once(**{**options, 'group_id': 'practical:question-bank:' + 'a' * 64})
    prepare.assert_not_awaited()
    assert not fake.plans
    assert await stage_once(**options) == wire
    assert await stage_once(**{**options, 'journal': copy.copy(journal)}) == wire
    prepare.assert_awaited_once()
    invoke.assert_awaited_once()
    stored = next(value for value in fake.values.values() if isinstance(value, dict) and value.get('response') == wire)
    assert stored['direct_metadata']['model'] == model
    assert stored['direct_metadata']['usage']['input_tokens'] == 12
    assert stored['direct_metadata']['usage']['output_tokens'] == 6
    assert stored['direct_metadata_sha256']
