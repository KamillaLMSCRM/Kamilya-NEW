"""Exercise false edit authority and unchanged-review custody at the real cycle seam."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.ai.v3.practical_arbitration import (
    NAME,
    adjudicate_practical_findings,
    arbitration_format,
    arbitration_messages,
)
from app.modules.ai.v3.practical_audit_units import audit_units
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_lesson_cycle import run_lesson_practical_cycle
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_review import LESSON_NAME, PracticalReviewDecision
from tests.unit.test_v3_practical_arbitration import allegation, judgment

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def clean_review(packet, course):
    refs = [b.block_id for b in packet.blocks]
    return {'source_fingerprint': packet.fingerprint, 'source_review': 'Checked all applicable rules.',
        'source_notes': [], 'findings': [], 'answer_keys': {q['id']: q.get('correct_index', 0) for lesson in course['lessons'] for q in lesson['questions']},
        'narrative_sources': {lesson['id']: refs for lesson in course['lessons']},
        'answerability': [{'question_id': q['id'], 'status': 'UNIQUE', 'possible_options': [q.get('correct_index', 0)],
            'source_refs': refs, 'reason': 'Exactly this option follows the source.'}
            for lesson in course['lessons'] for q in lesson['questions']]}


def clean_audit(packet, course):
    return {'source_fingerprint': packet.fingerprint, 'source_review': 'All source blocks are taught.',
        'source_notes': [], 'findings': [], 'source_checks': [{'source_refs': [ref], 'status': 'TAUGHT',
            'lesson_ids': [lesson['id'] for lesson in course['lessons']], 'reason': ''}
            for _, refs in audit_units(packet).groups for ref in refs]}


@pytest.mark.asyncio
@pytest.mark.parametrize('verdict', ['ALREADY_COVERED', 'SOURCE_AMBIGUITY', 'NEEDS_REVIEW'])
async def test_whole_course_decision_prevents_false_rewrite_and_preserves_source(case, verdict):
    _, packet, course = case
    original = copy.deepcopy(course)
    view = PracticalModelView(packet)
    calls = []

    async def invoke(stage, group, messages, fmt, validate):
        calls.append((stage, group))
        name = fmt['json_schema']['name']
        if stage == 'lesson':
            value = course
        elif name == LESSON_NAME:
            value = clean_review(packet, course)
            value['findings'] = [{'scope': 'assessment', 'target_id': 'l1', 'problem': 'Add a dedicated question.',
                'source_refs': [packet.blocks[0].block_id], 'expected_rule': 'Ask every detail.', 'correction': 'Add questions.'}]
        elif name == NAME:
            content = messages[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1]
            sent = view.decode(json.loads(content))
            assert 'correct_index' not in content
            prior = PracticalReviewDecision(False, False, (), (), False, tuple(sent['critic_findings']), ('l1',))
            value = judgment(packet, course, prior, verdict)
        elif name == 'v3_practical_atomic_source_audit_v1':
            value = clean_audit(packet, course)
        else:
            pytest.fail('A false or uncertain finding must not authorize repair')
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await run_lesson_practical_cycle(packet, {}, invoke, adjudicate=True)
    assert result.arbitrated_review and result.course == original
    assert len(calls) == 4 and all(stage != 'repair' for stage, _ in calls)
    assert result.decision.accepted is (verdict == 'ALREADY_COVERED')
    assert result.stop_reason == ('accepted' if verdict == 'ALREADY_COVERED' else 'source_uncertain')
    assert result.history[0]['adjudication']['judgments'][0]['verdict'] == verdict


@pytest.mark.asyncio
async def test_unchanged_part_carries_open_issues_without_provider_recheck(case):
    _, packet, course = case
    course = copy.deepcopy(course)
    peer = copy.deepcopy(course['lessons'][0])
    peer['id'] = 'l2'
    for q in peer['questions']:
        q['id'] += '-peer'
    course['lessons'].append(peer)
    view = PracticalModelView(packet)
    calls = {'l1': 0, 'l2': 0}
    audits = 0

    async def invoke(stage, group, messages, fmt, validate):
        nonlocal audits
        name = fmt['json_schema']['name']
        if stage == 'lesson':
            value = course
        elif name == LESSON_NAME:
            content = messages[1]['content'].split('\n\nГОТОВЫЙ КУРС. COURSE_JSON\n')[1]
            part = view.decode(json.loads(content.split('\nPREVIOUS_FINDINGS_JSON\n')[0]))
            lid = part['lessons'][0]['id']
            calls[lid] += 1
            value = clean_review(packet, part)
            value['findings'] = [{'scope': 'question', 'target_id': part['lessons'][0]['questions'][0]['id'],
                'problem': 'A material option error.', 'source_refs': [packet.blocks[0].block_id],
                'expected_rule': 'Sign and record.', 'correction': 'Correct this option.'}]
            props = fmt['json_schema']['schema']['properties']
            if 'issue_checks' in props:
                value['issue_checks'] = {key: {'status': 'RESOLVED', 'reason': 'Checked again.'}
                                         for key in props['issue_checks']['properties']}
                value['findings'] = []
        elif name == 'v3_practical_atomic_source_audit_v1':
            audits += 1
            value = clean_audit(packet, course)
        elif name == NAME:
            content = messages[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1]
            sent = view.decode(json.loads(content))
            if audits == 2:
                assert any(row['id'] == 'q1' for row in sent['critic_findings']), 'Prior issue vanished on critic RESOLVED alone'
            value = {'source_fingerprint': packet.fingerprint,
                'course_fingerprint': fmt['json_schema']['schema']['properties']['course_fingerprint']['enum'][0],
                'judgments': [{'issue_id': row['issue_id'], 'verdict': 'MATERIAL_ERROR' if audits == 1 else 'NEEDS_REVIEW',
                    'reason': 'Material issue remains.', 'source_refs': [packet.blocks[0].block_id],
                    'course_evidence': [], 'answer_check': {'status': 'NOT_APPLICABLE'}} for row in sent['critic_findings']]}
        else:
            assert stage == 'repair'
            changed = copy.deepcopy(course['lessons'][0]['questions'][0])
            changed['explanation'] += ' Updated.'
            value = {'course_fingerprint': _digest(course), 'new_lessons': [], 'new_questions': [],
                'question_updates': {'q1': changed, 'q1-peer': copy.deepcopy(peer['questions'][0])}}
        wire = view.encode(value)
        validate(wire)
        return wire

    result = await run_lesson_practical_cycle(packet, {}, invoke, adjudicate=True)
    assert calls == {'l1': 2, 'l2': 1}
    assert not result.decision.accepted and result.stop_reason == 'source_uncertain'
    carry = result.history[1]['carried_reviews']
    assert len(carry) == 1 and carry[0]['lesson_id'] == 'l2' and carry[0]['open_issue_ids']
    derived = result.history[1]['lesson_reviews'][1]
    assert all(row['status'] == 'OPEN' for row in derived['issue_checks'].values())
    assert 'issue_checks' not in result.history[0]['lesson_reviews'][1]
    assert result.course['lessons'][1] == peer


@pytest.mark.asyncio
@pytest.mark.parametrize('selectors', [False, True])
async def test_arbitration_owned_journal_replays_and_fences_wrong_model(case, monkeypatch, selectors):
    from app.modules.ai.managed_luna_client import ManagedLunaClient
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    from app.modules.ai.v3.practical_arbitration import evidence_inventory
    from app.modules.ai.v3.stage_checkpoint import stage_once
    from tests.unit.test_direct_luna_owned_stage import setup

    _, packet, course = case
    decision = allegation(packet)
    view = PracticalModelView(packet)
    value = judgment(packet, course, decision)
    if selectors:
        value['judgments'][0]['course_evidence'] = [next(key for key, item in evidence_inventory(course)[0].items()
                                                       if item['question_id'] == 'q1' and item['field'] == 'prompt')]
    wire = view.encode(value)
    _, journal, _, _, _ = setup()
    client = ManagedLunaClient(base_url='http://127.0.0.1:18999/v1', api_key='synthetic',
        tenant_id=UUID(journal.tenant_id), user_id=journal.user_id, job_id=journal.job_id,
        credential_revision='r1', model='gpt-6-luna', reasoning_effort='high', deadline_seconds=300)
    prepare = AsyncMock(return_value=object())
    invoke = AsyncMock(return_value=SimpleNamespace(content=wire, model='gpt-6-luna',
        usage=SimpleNamespace(input_tokens=12, output_tokens=6, cached_input_tokens=None, reasoning_tokens=None)))
    monkeypatch.setattr(client, 'prepare', prepare)
    monkeypatch.setattr(client, 'invoke', invoke)
    def validate(value):
        adjudicate_practical_findings(view.decode(value), packet, course, decision, {'l1': [packet.blocks[0].block_id]}, selectors=selectors)
    options = dict(journal=journal, direct_client=client, stage='review', group_id='practical:arbitrate:test',
        source_sha256='b' * 64, route_fingerprint=client.cache_fingerprint(),
        messages=arbitration_messages(packet, course, decision, model_view=view, selectors=selectors),
        response_format=view.schema(arbitration_format(packet, course, decision, selectors=selectors)),
        direct_max_output_tokens=128, response_validator=validate, invoke=AsyncMock())
    assert await stage_once(**options) == wire
    assert await stage_once(**{**options, 'journal': copy.copy(journal)}) == wire
    prepare.assert_awaited_once()
    invoke.assert_awaited_once()
    invoke.return_value.model = 'other-model'
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**{**options, 'group_id': 'practical:arbitrate:other'})


@pytest.mark.asyncio
async def test_arbitration_structural_gate_is_mandatory_without_optional_validator(case):
    from app.modules.ai.v3.stage_checkpoint import stage_once
    from tests.unit.test_v3_partitioned_extraction import Journal

    _, packet, course = case
    with pytest.raises(ValueError, match='shape_invalid'):
        await stage_once(journal=Journal(), stage='review', group_id='practical:arbitrate:shape',
            source_sha256='b' * 64, route_fingerprint='c' * 64,
            messages=arbitration_messages(packet, course, allegation(packet)),
            response_format=arbitration_format(packet, course, allegation(packet)),
            invoke=AsyncMock(return_value={'not': 'an arbitration response'}))


@pytest.mark.asyncio
async def test_fresh_service_persists_adjudication_and_replays_without_model(case):
    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.v3.practical_service import generate_practical_course
    from app.modules.ai.v3.revision_policy import ARBITRATED_PRACTICAL_REVIEW_POLICY
    from tests.unit.test_v3_partitioned_extraction import Journal

    corpus, packet, course = case
    view = PracticalModelView(packet)
    names = []
    async def invoke(messages, fmt):
        name = fmt['json_schema']['name']
        names.append(name)
        if name == 'practical_course':
            value = course
        elif name == LESSON_NAME:
            value = clean_review(packet, course)
            value['findings'] = [{'scope': 'assessment', 'target_id': 'l1', 'problem': 'Add a question.',
                'source_refs': [packet.blocks[0].block_id], 'expected_rule': 'Ask each detail.', 'correction': 'Add.'}]
        elif name == NAME:
            sent = view.decode(json.loads(messages[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1]))
            prior = PracticalReviewDecision(False, False, (), (), False, tuple(sent['critic_findings']), ('l1',))
            value = judgment(packet, course, prior)
        else:
            assert name == 'v3_practical_atomic_source_audit_v1'
            value = clean_audit(packet, course)
        return view.encode(value)

    journal = Journal()
    options = dict(intent=CourseIntent(), invoke=invoke, source_sha256='b' * 64,
                   journal=journal, route_fingerprint='c' * 64, review_policy=ARBITRATED_PRACTICAL_REVIEW_POLICY)
    result = await generate_practical_course(corpus, **options)
    assert result.diagnostics['v3_review_policy'] == ARBITRATED_PRACTICAL_REVIEW_POLICY
    assert result.diagnostics['automated_review_passed'] and result.diagnostics['practical_course'] == course
    restored = await generate_practical_course(corpus, **options)
    assert restored.diagnostics == result.diagnostics
    assert len(names) == 4 and NAME in names


@pytest.mark.asyncio
async def test_source_hold_with_missing_new_lesson_returns_draft_instead_of_invalid_patch(case):
    _, packet, course = case
    view = PracticalModelView(packet)
    refs = [b.block_id for b in packet.blocks]
    async def invoke(stage, group, messages, fmt, validate):
        name = fmt['json_schema']['name']
        if stage == 'lesson':
            value = course
        elif name == LESSON_NAME:
            value = clean_review(packet, course)
            value['narrative_sources']['l1'] = [refs[0]]
        elif name == 'v3_practical_atomic_source_audit_v1':
            value = clean_audit(packet, course)
            for row in value['source_checks']:
                row.update(status='UNCERTAIN' if row['source_refs'] == [refs[0]] else 'MISSING',
                           lesson_ids=[], reason='Source ambiguity.' if row['source_refs'] == [refs[0]] else 'Missing procedure.')
        elif name == NAME:
            sent = view.decode(json.loads(messages[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1]))
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course),
                'judgments': [{'issue_id': row['issue_id'], 'verdict': 'SOURCE_AMBIGUITY' if row['scope'] == 'source' else 'MATERIAL_ERROR',
                    'reason': 'Confirmed.', 'source_refs': row['evidence']['source_refs'], 'course_evidence': [],
                    'answer_check': {'status': 'NOT_APPLICABLE'}} for row in sent['critic_findings']]}
        else:
            pytest.fail('New lesson creation is held while the source remains uncertain')
        wire = view.encode(value)
        validate(wire)
        return wire
    result = await run_lesson_practical_cycle(packet, {}, invoke, adjudicate=True)
    assert result.stop_reason == 'source_uncertain' and result.decision.allow_new_lessons
    assert result.course == course and not result.decision.accepted
