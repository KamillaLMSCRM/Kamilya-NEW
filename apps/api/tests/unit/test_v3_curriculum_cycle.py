"""Source-only curriculum and blind assessment coverage through the real cycle."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.ai.managed_luna_client import ManagedLunaClient
from app.modules.ai.v3.practical_arbitration import MATERIALITY_SELECTOR_NAME
from app.modules.ai.v3.practical_atomic_audit import CLAIM_EVIDENCE_NAME
from app.modules.ai.v3.practical_audit_units import audit_units
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_curriculum import (
    CURRICULUM_BANK_NAME,
    CURRICULUM_NAME,
    curriculum_bank_format,
    curriculum_bank_messages,
    curriculum_format,
    curriculum_messages,
    validate_curriculum,
)
from app.modules.ai.v3.practical_lesson_cycle import run_lesson_practical_cycle
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_question_context import NAME as CONTEXT_NAME
from app.modules.ai.v3.practical_review import QUESTION_BATCH_NAME
from app.modules.ai.v3.stage_checkpoint import stage_once
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_v3_partitioned_extraction import Journal
from tests.unit.test_v3_practical_arbitrated_cycle import clean_audit
from tests.unit.test_v3_practical_bank_cycle import bank_value
from tests.unit.test_v3_practical_claim_evidence import response as audit_response

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)
FLAGS = dict(adjudicate=True, standalone=True, typed_findings=True, counterexamples=True,
             explicit_cases=True, question_batch=True, strict_audit_owners=True, exclusive_options=True,
             context_supplemented=True, assessment_coverage=True, materiality_review=True,
             claim_evidence=True, review_domains=True, source_scope_complete=True, curriculum_review=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('owner', ['l1', ''])
async def test_source_curriculum_precedes_author_and_missing_goal_is_not_silent(case, owner):
    _, packet, course = case
    view = PracticalModelView(packet)
    names = []
    arbiter_inputs = []

    async def provider(stage, group, messages, fmt, validate):
        name = fmt['json_schema']['name']
        names.append(name)
        if name == CURRICULUM_NAME:
            assert stage == 'review' and 'COURSE' not in messages[1]['content']
            assert course['lessons'][0]['questions'][0]['prompt'] not in messages[1]['content']
            assert course['lessons'][0]['title'] not in messages[1]['content']
            units = [key for key, _ in audit_units(packet).groups]
            value = {'source_fingerprint': packet.fingerprint, 'sections': [{'title': 'Approval',
                'source_units': units, 'depends_on_units': [], 'goals': [{'id': 'author-proposed',
                    'decision': 'Verify the approval procedure.', 'essential_case_conditions': [],
                    'source_refs': [packet.blocks[0].block_id]}]}], 'non_teaching_units': [],
                'source_uncertainties': []}
        elif stage == 'lesson':
            assert names[0] == CURRICULUM_NAME and 'UNTRUSTED_SOURCE_ONLY_CURRICULUM_JSON' in messages[1]['content']
            value = course
        elif name == CONTEXT_NAME:
            props = fmt['json_schema']['schema']['properties']
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course),
                     'supplements': {key: '' for key in props['supplements']['properties']},
                     'context_source_refs': [], 'unresolved_question_ids': []}
        elif name == CURRICULUM_BANK_NAME:
            text = messages[1]['content']
            body = text.split('\n\nSTANDALONE_QUESTIONS_JSON\n')[1].split('\nPREVIOUS_FINDINGS_JSON\n')[0]
            questions = json.loads(body)
            assert all(set(q) == {'lesson_id', 'id', 'prompt', 'choices'} for q in questions)
            assert 'correct_index' not in text and 'explanation' not in text
            assert course['lessons'][0]['content'] not in body
            assert 'UNTRUSTED_SOURCE_ONLY_CURRICULUM_JSON' in text
            value = bank_value(packet, course)
            value['curriculum_fingerprint'] = fmt['json_schema']['schema']['properties']['curriculum_fingerprint']['enum'][0]
            value['goal_checks'] = [{'goal_id': 'G1', 'status': 'MISSING',
                'source_refs': [packet.blocks[0].block_id], 'question_ids': [],
                'assessment_lesson_id': owner, 'reason': 'A material decision is not assessed.'}]
        elif name == CLAIM_EVIDENCE_NAME:
            value = audit_response(packet, course)
        elif name == MATERIALITY_SELECTOR_NAME:
            assert owner
            sent = view.decode(json.loads(messages[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1]))
            arbiter_inputs.extend(sent['critic_findings'])
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course),
                'judgments': [{'issue_id': item['issue_id'], 'verdict': 'MATERIAL_ERROR',
                    'reason': 'The proposed missing decision is material.', 'source_refs': item['evidence']['source_refs'],
                    'course_evidence': [], 'answer_check': {'status': 'NOT_APPLICABLE'}}
                    for item in sent['critic_findings']]}
        else:
            pytest.fail(f'Unexpected stage: {stage} {name}')
        wire = view.encode(value)
        validate(wire)
        return wire

    journal = Journal()
    def dispatcher(bound_journal):
        async def invoke(stage, group, messages, fmt, validate):
            return await stage_once(journal=bound_journal, stage=stage, group_id=group,
                source_sha256='b' * 64, route_fingerprint='c' * 64, messages=messages, response_format=fmt,
                invoke=lambda: provider(stage, group, messages, fmt, validate), response_validator=validate)
        return invoke

    result = await run_lesson_practical_cycle(packet, {}, dispatcher(journal), max_revisions=0, **FLAGS)
    cold = await run_lesson_practical_cycle(packet, {}, dispatcher(copy.copy(journal)), max_revisions=0, **FLAGS)
    assert cold == result and names.count(CURRICULUM_NAME) == 1 and names.count(CURRICULUM_BANK_NAME) == 1
    assert names.index(CURRICULUM_NAME) < names.index('practical_course') < names.index(CURRICULUM_BANK_NAME)
    assert not result.decision.accepted and not result.decision.source_uncertain
    assert result.curriculum_plan['sections'][0]['goals'][0]['id'] == 'G1'
    if owner:
        assert result.stop_reason == 'revision_limit' and result.decision.assessment_lesson_ids == ('l1',)
        assert len(arbiter_inputs) == 1 and arbiter_inputs[0]['scope'] == 'assessment'
        assert 'G1' in arbiter_inputs[0]['evidence']['problem']
    else:
        assert result.stop_reason == 'curriculum_coverage_unresolved'
        assert result.unresolved_curriculum_goals == ('G1',) and not arbiter_inputs


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['direct', 'managed'])
@pytest.mark.parametrize('kind', ['planner', 'bank'])
async def test_curriculum_pending_owned_stage_replays_and_fences_group(case, monkeypatch, provider, kind):
    _, packet, course = case
    fake, journal, client, _, _ = setup()
    model = 'gpt-6-luna'
    if provider == 'managed':
        client = ManagedLunaClient(base_url='http://127.0.0.1:18999/v1', api_key='synthetic',
            tenant_id=UUID(journal.tenant_id), user_id=journal.user_id, job_id=journal.job_id,
            credential_revision='synthetic')
        model = 'gpt-5.6-luna'
    view = PracticalModelView(packet)
    units = [key for key, _ in audit_units(packet).groups]
    plan = validate_curriculum({'source_fingerprint': packet.fingerprint, 'sections': [{'title': 'Approval',
        'source_units': units, 'depends_on_units': [], 'goals': [{'id': 'draft', 'decision': 'Follow procedure.',
            'essential_case_conditions': [], 'source_refs': [packet.blocks[0].block_id]}]}],
        'non_teaching_units': [], 'source_uncertainties': []}, packet)
    if kind == 'planner':
        fmt = curriculum_format(packet)
        messages = curriculum_messages(packet, view)
        value = plan
        group = 'practical:source-curriculum:v1'
    else:
        fmt = curriculum_bank_format(packet, course, plan)
        messages = curriculum_bank_messages(packet, course, plan, model_view=view)
        value = bank_value(packet, course)
        value['curriculum_fingerprint'] = _digest(plan)
        value['goal_checks'] = [{'goal_id': 'G1', 'status': 'COVERED', 'source_refs': [packet.blocks[0].block_id],
                                 'question_ids': ['q1'], 'assessment_lesson_id': '', 'reason': 'Question tests it.'}]
        group = 'practical:review:bank:' + 'a' * 64
    wire_fmt, wire = view.schema(fmt), view.encode(value)
    prepare = AsyncMock(return_value=object())
    invoke = AsyncMock(return_value=SimpleNamespace(content=wire, model=model,
        usage=SimpleNamespace(input_tokens=12, output_tokens=6, cached_input_tokens=None, reasoning_tokens=None)))
    monkeypatch.setattr(client, 'prepare', prepare)
    monkeypatch.setattr(client, 'invoke', invoke)
    options = dict(journal=journal, direct_client=client, stage='review', group_id=group,
                   source_sha256='b' * 64, route_fingerprint=client.cache_fingerprint(),
                   messages=messages, response_format=wire_fmt, direct_max_output_tokens=128,
                   response_validator=lambda received: None, invoke=AsyncMock())
    for wrong in ({'stage': 'lesson'}, {'group_id': 'practical:foreign:' + kind}):
        with pytest.raises(ValueError):
            await stage_once(**{**options, **wrong})
    prepare.assert_not_awaited()
    assert not fake.plans
    assert await stage_once(**options) == wire
    assert await stage_once(**{**options, 'journal': copy.copy(journal)}) == wire
    prepare.assert_awaited_once()
    invoke.assert_awaited_once()
    assert any(isinstance(item, dict) and item.get('response') == wire and item.get('direct_metadata')
               for item in fake.values.values())


@pytest.mark.asyncio
@pytest.mark.parametrize('policy', [25, 26, 27])
async def test_disabled_curriculum_keeps_legacy_request_identity(case, policy):
    _, packet, course = case
    view = PracticalModelView(packet)
    options = {key: value for key, value in FLAGS.items() if key not in {
        'curriculum_review', 'source_scope_complete', 'review_domains', 'claim_evidence'}}
    if policy >= 26:
        options['claim_evidence'] = True
    if policy >= 27:
        options['review_domains'] = True

    async def capture(extra):
        requests = []
        async def invoke(stage, group, messages, fmt, validate):
            requests.append(copy.deepcopy((stage, group, messages, fmt)))
            name = fmt['json_schema']['name']
            if stage == 'lesson':
                value = course
            elif name == CONTEXT_NAME:
                props = fmt['json_schema']['schema']['properties']
                value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course),
                    'supplements': {key: '' for key in props['supplements']['properties']},
                    'context_source_refs': [], 'unresolved_question_ids': []}
            elif name == QUESTION_BATCH_NAME:
                value = bank_value(packet, course)
            else:
                value = audit_response(packet, course) if policy >= 26 else clean_audit(packet, course)
            wire = view.encode(value)
            validate(wire)
            return wire
        result = await run_lesson_practical_cycle(packet, {}, invoke, max_revisions=0, **options, **extra)
        assert result.decision.accepted
        return requests

    assert await capture({}) == await capture({'curriculum_review': False})
