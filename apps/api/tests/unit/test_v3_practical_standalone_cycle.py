"""Standalone exams and prose coverage remain different inputs to edit authority."""
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.practical_arbitration import SELECTOR_NAME
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_review import STANDALONE_NAME, practical_review_format, practical_review_messages
from app.modules.ai.v3.practical_service import generate_practical_course
from app.modules.ai.v3.revision_policy import STANDALONE_PRACTICAL_REVIEW_POLICY
from tests.unit.test_v3_practical_arbitrated_cycle import clean_audit, clean_review

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def standalone_value(packet, course):
    value = clean_review(packet, course)
    value['question_sources'] = value.pop('narrative_sources')
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize('source_uncertain', [False, True])
async def test_fresh_service_uses_standalone_input_and_honest_prose_links(case, source_uncertain):
    from tests.unit.test_v3_partitioned_extraction import Journal

    corpus, packet, course = case
    names = []
    view = PracticalModelView(packet)
    async def invoke(messages, fmt):
        name = fmt['json_schema']['name']
        names.append(name)
        if name == 'practical_course':
            value = course
        elif name == STANDALONE_NAME:
            body = messages[1]['content'].split('\n\nSTANDALONE_QUESTIONS_JSON\n')[1].split('\nPREVIOUS_FINDINGS_JSON\n')[0]
            projected = json.loads(body)
            assert set(projected) == {'lesson_id', 'questions'}
            assert all(set(q) == {'id', 'prompt', 'choices'} for q in projected['questions'])
            value = standalone_value(packet, course)
        elif name == 'v3_practical_atomic_source_audit_v1':
            value = clean_audit(packet, course)
            if source_uncertain:
                for row in value['source_checks']:
                    row.update(status='UNCERTAIN', lesson_ids=[], reason='Source interpretation remains unresolved.')
        else:
            assert source_uncertain and name == SELECTOR_NAME
            sent = view.decode(json.loads(messages[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1]))
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course),
                'judgments': [{'issue_id': row['issue_id'], 'verdict': 'SOURCE_AMBIGUITY',
                    'reason': 'Cannot resolve the source by rewriting.', 'source_refs': row['evidence']['source_refs'],
                    'course_evidence': [], 'answer_check': {'status': 'NOT_APPLICABLE'}} for row in sent['critic_findings']]}
        return view.encode(value)
    options = dict(intent=CourseIntent(), invoke=invoke, source_sha256='b' * 64, journal=Journal(), route_fingerprint='c' * 64)
    result = await generate_practical_course(corpus, **options)
    assert result.diagnostics['v3_review_policy'] == STANDALONE_PRACTICAL_REVIEW_POLICY
    assert result.diagnostics['automated_review_passed'] is not source_uncertain
    assert result.diagnostics['practical_course'] == course
    replay = await generate_practical_course(corpus, **options)
    assert replay.diagnostics == result.diagnostics
    assert len(names) == (4 if source_uncertain else 3)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['MISSING', 'CONTRADICTED', 'UNCERTAIN'])
async def test_question_basis_is_never_used_as_prose_coverage(case, status):
    from app.modules.ai.v3.practical_lesson_cycle import run_lesson_practical_cycle
    from app.modules.ai.v3.practical_service import practical_artifacts

    corpus, packet, course = case
    view = PracticalModelView(packet)
    async def invoke(stage, group, messages, fmt, validate):
        name = fmt['json_schema']['name']
        if stage == 'lesson':
            value = course
        elif name == STANDALONE_NAME:
            value = standalone_value(packet, course)
        elif name == 'v3_practical_atomic_source_audit_v1':
            value = clean_audit(packet, course)
            for row in value['source_checks']:
                row.update(status=status, lesson_ids=['l1'], reason='No prose mapping verified.')
        else:
            assert name == SELECTOR_NAME
            sent = view.decode(json.loads(messages[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1]))
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course),
                'judgments': [{'issue_id': row['issue_id'], 'verdict': 'NEEDS_REVIEW', 'reason': 'Not verified.',
                    'source_refs': row['evidence']['source_refs'], 'course_evidence': [],
                    'answer_check': {'status': 'NOT_APPLICABLE'}} for row in sent['critic_findings']]}
        wire = view.encode(value)
        validate(wire)
        return wire
    result = await run_lesson_practical_cycle(packet, {}, invoke, adjudicate=True, standalone=True)
    assert result.review['narrative_sources'] == {'l1': []}
    assert result.history[0]['lesson_reviews'][0]['question_sources']['l1']
    assert result.standalone_review and not result.decision.accepted and result.decision.source_uncertain
    # Even an editor discharging a coverage allegation cannot fabricate a
    # positive teaching citation from affected-owner IDs or question sources.
    discharged = replace(result, decision=replace(result.decision, accepted=True, feedback=(), source_uncertain=False))
    artifacts = practical_artifacts(discharged, corpus, packet, 'f' * 64)
    lesson = artifacts.content.modules[0].lessons[0]
    assert lesson.source_references == [] and lesson.source_validation_status == 'needs_review'
    assert artifacts.diagnostics['unresolved_source_provenance_lesson_ids'] == ['l1']
    assert not artifacts.diagnostics['automated_review_passed']
    assert artifacts.diagnostics['practical_question_source_refs']['q1']


@pytest.mark.asyncio
async def test_standalone_review_reaches_managed_owned_stage_and_replays(case, monkeypatch):
    from app.modules.ai.managed_luna_client import ManagedLunaClient
    from app.modules.ai.v3.practical_review import interpret_practical_review
    from app.modules.ai.v3.stage_checkpoint import stage_once
    from tests.unit.test_direct_luna_owned_stage import setup

    _, packet, course = case
    view = PracticalModelView(packet)
    response = view.encode(standalone_value(packet, course))
    _, journal, _, _, _ = setup()
    client = ManagedLunaClient(base_url='http://127.0.0.1:18999/v1', api_key='synthetic', tenant_id=UUID(journal.tenant_id),
        user_id=journal.user_id, job_id=journal.job_id, credential_revision='r1', model='gpt-6-luna', reasoning_effort='high', deadline_seconds=300)
    prepare = AsyncMock(return_value=object())
    invoke = AsyncMock(return_value=SimpleNamespace(content=response, model='gpt-6-luna',
        usage=SimpleNamespace(input_tokens=12, output_tokens=6, reasoning_tokens=None, cached_input_tokens=None)))
    monkeypatch.setattr(client, 'prepare', prepare)
    monkeypatch.setattr(client, 'invoke', invoke)
    def validate(value):
        interpret_practical_review(view.decode(value), packet, course, concise=True, strict_targets=True, standalone=True)
    options = dict(journal=journal, direct_client=client, stage='review', group_id='practical:review:standalone',
        source_sha256='b' * 64, route_fingerprint=client.cache_fingerprint(),
        messages=practical_review_messages(packet, course, concise=True, strict_targets=True, standalone=True, model_view=view),
        response_format=view.schema(practical_review_format(packet, course, concise=True, strict_targets=True, standalone=True)),
        direct_max_output_tokens=128, response_validator=validate, invoke=AsyncMock())
    assert await stage_once(**options) == response
    assert await stage_once(**options) == response
    prepare.assert_awaited_once()
    invoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_mixed_feedback_uses_separate_views_and_merges_only_confirmed_authority(case):
    from app.modules.ai.v3.practical_lesson_cycle import run_lesson_practical_cycle

    _, packet, course = case
    view = PracticalModelView(packet)
    scopes = []
    async def invoke(stage, group, messages, fmt, validate):
        name = fmt['json_schema']['name']
        if stage == 'lesson':
            value = course
        elif name == STANDALONE_NAME:
            value = standalone_value(packet, course)
            value['answerability'][0].update(status='DEPENDS', possible_options=[0, 1])
            value['answer_keys']['q1'] = -1
        elif name == 'v3_practical_atomic_source_audit_v1':
            value = clean_audit(packet, course)
            value['findings'] = [{'scope': 'lesson', 'target_id': 'l1', 'problem': 'Use must rather than present tense.',
                'source_refs': [packet.blocks[0].block_id], 'expected_rule': 'It is a duty.', 'correction': 'Rewrite the sentence.'}]
        else:
            assert name == SELECTOR_NAME
            sent = view.decode(json.loads(messages[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1]))
            question_scope = 'standalone_questions' in sent
            scopes.append(question_scope)
            if question_scope:
                assert 'whole_course' not in sent and [q['id'] for q in sent['standalone_questions']] == ['q1']
                assert all(row['scope'] == 'question' for row in sent['critic_findings'])
                selected = sent['standalone_questions'][0]['prompt']['evidence_id']
            else:
                assert 'whole_course' in sent and all(row['scope'] == 'lesson' for row in sent['critic_findings'])
                selected = sent['whole_course']['lessons'][0]['content'][0]['evidence_id']
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course),
                'judgments': [{'issue_id': row['issue_id'], 'verdict': 'MATERIAL_ERROR' if question_scope else 'STYLE_ONLY',
                    'reason': 'The question omits a condition.' if question_scope else 'The duty is already taught.',
                    'source_refs': [packet.blocks[0].block_id], 'course_evidence': [selected],
                    'answer_check': {'status': 'NOT_APPLICABLE'}} for row in sent['critic_findings']]}
        wire = view.encode(value)
        validate(wire)
        return wire
    result = await run_lesson_practical_cycle(packet, {}, invoke, max_revisions=0, adjudicate=True, standalone=True)
    assert scopes == [True, False]
    assert result.stop_reason == 'revision_limit' and not result.decision.accepted
    assert result.decision.question_ids == ('q1',) and result.decision.lesson_ids == ()
    assert not result.decision.source_uncertain
    assert set(result.history[0]['adjudication']) == {'questions', 'course'}
