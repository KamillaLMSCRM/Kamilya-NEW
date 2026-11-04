"""Context custody across real service, scoped revision, and cold journal replay."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.managed_luna_client import ManagedLunaClient
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.practical_arbitration import TYPED_SELECTOR_NAME
from app.modules.ai.v3.practical_atomic_audit import STRICT_OWNER_NAME
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_question_context import (
    NAME,
    apply_context_supplements,
    context_format,
    context_messages,
)
from app.modules.ai.v3.practical_review import QUESTION_BATCH_NAME
from app.modules.ai.v3.practical_service import generate_practical_course
from app.modules.ai.v3.response_contracts import matches_response_contract, response_contract
from app.modules.ai.v3.revision_policy import CONTEXT_SUPPLEMENT_PRACTICAL_REVIEW_POLICY
from app.modules.ai.v3.stage_checkpoint import stage_once
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_v3_partitioned_extraction import Journal
from tests.unit.test_v3_practical_arbitrated_cycle import clean_audit
from tests.unit.test_v3_practical_bank_cycle import bank_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


def context_value(fmt, *, unresolved=(), supplement=''):
    props = fmt['json_schema']['schema']['properties']
    ids = list(props['supplements']['properties'])
    value = {'source_fingerprint': props['source_fingerprint']['enum'][0],
            'course_fingerprint': props['course_fingerprint']['enum'][0],
            'supplements': {qid: supplement if qid == ids[0] and qid not in unresolved else '' for qid in ids},
            'unresolved_question_ids': list(unresolved)}
    if 'context_source_refs' in props:
        refs = props['context_source_refs']['items']['properties']['source_refs']['items']['enum']
        value['context_source_refs'] = [{'question_id': qid, 'source_refs': [refs[0]]}
                                        for qid, text in value['supplements'].items() if text]
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize('unresolved', [False, True])
async def test_service_context_reaches_assessment_and_cold_replay_never_repeats_calls(case, unresolved):
    corpus, packet, original = case
    view = PracticalModelView(packet)
    current = copy.deepcopy(original)
    names = []

    async def invoke(messages, fmt):
        nonlocal current
        name = fmt['json_schema']['name']
        names.append(name)
        if name == 'practical_course':
            value = original
        elif name == NAME:
            value = view.decode(context_value(fmt, unresolved=('q1',) if unresolved else (), supplement='The ticket is unapproved.'))
            current, _ = apply_context_supplements(packet, current, ('q1', 'q2'), value)
        elif name == QUESTION_BATCH_NAME:
            bank = json.loads(messages[1]['content'].split('\n\nSTANDALONE_QUESTIONS_JSON\n')[1].split('\nPREVIOUS_FINDINGS_JSON\n')[0])
            assert bank[0]['prompt'] == current['lessons'][0]['questions'][0]['prompt']
            value = bank_value(packet, current)
        else:
            assert name == STRICT_OWNER_NAME
            value = clean_audit(packet, current)
        return view.encode(value)

    journal = Journal()
    kwargs = dict(intent=CourseIntent(), invoke=invoke, source_sha256='b' * 64,
                  journal=journal, route_fingerprint='c' * 64,
                  review_policy=CONTEXT_SUPPLEMENT_PRACTICAL_REVIEW_POLICY)
    first = await generate_practical_course(corpus, **kwargs)
    # A new process reconstructs the cycle only from durable values.
    cold = Journal()
    cold.plans, cold.values = copy.deepcopy(journal.plans), copy.deepcopy(journal.values)
    replay = await generate_practical_course(corpus, **{**kwargs, 'journal': cold})
    assert first.diagnostics == replay.diagnostics
    assert names == ['practical_course', NAME, QUESTION_BATCH_NAME, STRICT_OWNER_NAME]
    assert first.diagnostics['automated_review_passed'] is not unresolved
    assert first.diagnostics['practical_unresolved_question_context'] == (['q1'] if unresolved else [])
    assert first.diagnostics['practical_course'] == current
    assert first.assessment.assessments[0].mcq[0].question == current['lessons'][0]['questions'][0]['prompt']
    if unresolved:
        assert first.diagnostics['validation_report']['stop_reason'] == 'question_context_unresolved'
        assert first.diagnostics['practical_course'] == original


@pytest.mark.asyncio
async def test_unrelated_owned_question_repair_cannot_drop_prior_unresolved_context(case):
    corpus, packet, original = case
    view = PracticalModelView(packet)
    current = copy.deepcopy(original)
    repaired = False
    context_targets = []

    async def invoke(messages, fmt):
        nonlocal current, repaired
        name = fmt['json_schema']['name']
        props = fmt['json_schema']['schema']['properties']
        if name == 'practical_course':
            value = original
        elif name == NAME:
            ids = tuple(props['supplements']['properties'])
            context_targets.append(ids)
            value = context_value(fmt, unresolved=('q1',) if 'q1' in ids else ())
        elif name == QUESTION_BATCH_NAME:
            value = bank_value(packet, current)
            if not repaired:
                value['answer_keys']['q2'] = -1
                row = next(row for row in value['answerability'] if row['question_id'] == 'q2')
                row.update(status='UNKNOWN', possible_options=[], reason='The question has a missing premise.')
        elif name == STRICT_OWNER_NAME:
            value = clean_audit(packet, current)
        elif name == TYPED_SELECTOR_NAME:
            sent = view.decode(json.loads(messages[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1]))
            evidence = sent['standalone_questions'][0]['prompt']['evidence_id']
            answer = {'status': 'UNIQUE' if repaired else 'UNKNOWN', 'question_id': 'q2',
                      'possible_options': [0] if repaired else [], 'source_refs': original['lessons'][0]['questions'][1]['source_refs'],
                      'reason': 'The repaired prompt now states its premise.' if repaired else 'The premise is missing.'}
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(current),
                'judgments': [{'issue_id': row['issue_id'], 'verdict': 'ALREADY_COVERED' if repaired else 'MATERIAL_ERROR',
                    'reason': 'Independently checked the question.', 'source_refs': answer['source_refs'],
                    'course_evidence': [evidence] if repaired else [], 'answer_check': answer}
                    for row in sent['critic_findings']]}
        else:
            assert set(props['question_updates']['properties']) == {'q2'}
            q = copy.deepcopy(current['lessons'][0]['questions'][1])
            q['prompt'] += ' With the missing premise.'
            value = {'course_fingerprint': _digest(current), 'new_lessons': [], 'new_questions': [],
                     'question_updates': {'q2': q}}
            current['lessons'][0]['questions'][1] = copy.deepcopy(q)
            repaired = True
        if 'issue_checks' in props:
            value['issue_checks'] = {key: {'status': 'RESOLVED', 'reason': 'Checked after the owned repair.'}
                                     for key in props['issue_checks']['properties']}
        return view.encode(value)

    result = await generate_practical_course(corpus, intent=CourseIntent(), invoke=invoke,
        source_sha256='b' * 64, journal=Journal(), route_fingerprint='c' * 64,
        review_policy=CONTEXT_SUPPLEMENT_PRACTICAL_REVIEW_POLICY)
    assert context_targets == [('q1', 'q2'), ('q2',)]
    assert result.diagnostics['practical_unresolved_question_context'] == ['q1']
    assert result.diagnostics['practical_course']['lessons'][0]['questions'][0] == original['lessons'][0]['questions'][0]
    assert not result.diagnostics['automated_review_passed']
    assert result.diagnostics['validation_report']['stop_reason'] == 'question_context_unresolved'


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['direct', 'managed'])
async def test_context_owned_format_is_registered_and_cold_replays_under_each_transport(case, monkeypatch, provider):
    _, packet, course = case
    fake, journal, client, _, _ = setup()
    model = 'gpt-6-luna'
    if provider == 'managed':
        client = ManagedLunaClient(base_url='http://127.0.0.1:18999/v1', api_key='synthetic',
            tenant_id=UUID(fake.tenant_id), user_id=fake.job.user_id, job_id=fake.job_id,
            credential_revision='synthetic', model=model)
    view = PracticalModelView(packet)
    fmt = view.schema(context_format(packet, course, ('q1',)))
    wire = context_value(fmt)
    assert response_contract(fmt) == 'practical_question_context'
    assert matches_response_contract(wire, fmt)
    prepare = AsyncMock(return_value=object())
    invoke = AsyncMock(return_value=SimpleNamespace(content=wire, model=model,
        usage=SimpleNamespace(input_tokens=12, output_tokens=6, cached_input_tokens=None, reasoning_tokens=None)))
    monkeypatch.setattr(client, 'prepare', prepare)
    monkeypatch.setattr(client, 'invoke', invoke)
    kwargs = dict(journal=journal, direct_client=client, stage='review',
        group_id='practical:context:' + 'a' * 64, source_sha256='b' * 64,
        route_fingerprint=client.cache_fingerprint(), messages=context_messages(packet, course, ('q1',), model_view=view),
        response_format=fmt, direct_max_output_tokens=128,
        response_validator=lambda value: apply_context_supplements(packet, course, ('q1',), view.decode(value)),
        invoke=AsyncMock())
    with pytest.raises(ValueError, match='direct_owned_format_invalid'):
        await stage_once(**{**kwargs, 'group_id': 'practical:source-read:' + 'a' * 64})
    prepare.assert_not_awaited()
    assert await stage_once(**kwargs) == wire
    assert await stage_once(**{**kwargs, 'journal': copy.copy(journal)}) == wire
    prepare.assert_awaited_once()
    invoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_context_outcome_preserves_author_and_never_implicitly_reissues(case):
    corpus, packet, course = case
    view = PracticalModelView(packet)
    names = []

    async def invoke(_messages, fmt):
        name = fmt['json_schema']['name']
        names.append(name)
        if name == 'practical_course':
            return view.encode(course)
        assert name == NAME
        raise TimeoutError('The context call may have been dispatched.')

    journal = Journal()
    kwargs = dict(intent=CourseIntent(), invoke=invoke, journal=journal,
        source_sha256='b' * 64, route_fingerprint='c' * 64,
        review_policy=CONTEXT_SUPPLEMENT_PRACTICAL_REVIEW_POLICY)
    with pytest.raises(TimeoutError):
        await generate_practical_course(corpus, **kwargs)
    cold = Journal()
    cold.plans, cold.values = copy.deepcopy(journal.plans), copy.deepcopy(journal.values)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await generate_practical_course(corpus, **{**kwargs, 'journal': cold})
    assert names == ['practical_course', NAME]
