"""Synthetic real-cycle checks; no model, network or database is used."""
import copy
import json

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.v3.practical_arbitration import MATERIALITY_SELECTOR_NAME
from app.modules.ai.v3.practical_atomic_audit import STRICT_OWNER_NAME, atomic_audit_messages
from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_fidelity import PRACTICAL_DECISION_GUIDE
from app.modules.ai.v3.practical_lesson_cycle import run_lesson_practical_cycle
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_question_context import NAME
from app.modules.ai.v3.practical_review import QUESTION_BATCH_NAME
from app.modules.ai.v3.practical_service import generate_practical_course
from app.modules.ai.v3.revision_policy import MATERIALITY_PRACTICAL_REVIEW_POLICY
from tests.unit.test_v3_partitioned_extraction import Journal
from tests.unit.test_v3_practical_arbitrated_cycle import clean_audit
from tests.unit.test_v3_practical_bank_cycle import bank_value
from tests.unit.test_v3_question_context_cycle import context_value

pytest_plugins = ('tests.unit.test_v3_practical_cycle',)


@pytest.mark.asyncio
@pytest.mark.parametrize('eventually_proved', [False, True])
async def test_partial_repair_preserves_good_question_and_unproved_issue_then_cold_replays(case, eventually_proved, monkeypatch):
    corpus, packet, original = case
    view = PracticalModelView(packet)
    current = copy.deepcopy(original)
    repaired = False
    calls = []
    owned_repairs = []
    completed_cycles = []
    import app.modules.ai.v3.practical_lesson_cycle as cycle
    real_cycle = cycle.run_lesson_practical_cycle
    async def observe_cycle(*args, **kwargs):
        result = await real_cycle(*args, **kwargs)
        completed_cycles.append(result)
        return result
    monkeypatch.setattr(cycle, 'run_lesson_practical_cycle', observe_cycle)

    async def invoke(messages, fmt):
        nonlocal repaired
        name = fmt['json_schema']['name']
        props = fmt['json_schema']['schema']['properties']
        calls.append(name)
        if name == 'practical_course':
            # Review findings/repair scopes are not instructions to the author.
            assert PRACTICAL_DECISION_GUIDE not in messages[0]['content']
            value = original
        elif name == NAME:
            value = context_value(fmt)
        elif name == QUESTION_BATCH_NAME:
            value = bank_value(packet, current)
            if not repaired:
                for question in ('q1', 'q2'):
                    value['answer_keys'][question] = -1
                    answer = next(row for row in value['answerability'] if row['question_id'] == question)
                    answer.update(status='UNKNOWN', possible_options=[], reason='The critic has not established a unique answer.')
        elif name == STRICT_OWNER_NAME:
            assert PRACTICAL_DECISION_GUIDE in messages[0]['content']
            value = clean_audit(packet, current)
        elif name == MATERIALITY_SELECTOR_NAME:
            sent = view.decode(json.loads(messages[1]['content'].split('\nWHOLE_COURSE_AND_ALLEGATIONS_JSON\n')[1]))
            prompts = {q['id']: q['prompt']['evidence_id'] for q in sent['standalone_questions']}
            rows = []
            for issue in sent['critic_findings']:
                qid = issue['id']
                proved = repaired and (qid == 'q2' or eventually_proved)
                rows.append({'issue_id': issue['issue_id'],
                    'verdict': 'ALREADY_COVERED' if proved else 'STYLE_ONLY' if qid == 'q1' else 'MATERIAL_ERROR',
                    'reason': 'Owned independent question check.' if proved else 'Unproven dismissal.' if qid == 'q1' else 'Missing premise requires a scoped repair.',
                    'source_refs': issue['evidence']['source_refs'],
                    'course_evidence': [prompts[qid]] if proved else [],
                    'answer_check': {'status': 'UNIQUE', 'question_id': qid, 'possible_options': [0],
                        'source_refs': issue['evidence']['source_refs'], 'reason': 'The owned question has one source-supported answer.'}
                        if proved else {'status': 'NOT_APPLICABLE'}})
            value = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(current), 'judgments': rows}
        else:
            assert set(props['question_updates']['properties']) == {'q2'}
            assert 'lesson_updates' not in props
            owned_repairs.append('q2')
            question = copy.deepcopy(current['lessons'][0]['questions'][1])
            question['prompt'] += ' The approver has already signed the ticket.'
            value = {'course_fingerprint': _digest(current), 'new_lessons': [], 'new_questions': [],
                     'question_updates': {'q2': question}}
            current['lessons'][0]['questions'][1] = copy.deepcopy(question)
            repaired = True
        if 'issue_checks' in props:
            # A critic's claimed resolution must not erase an unproved arbiter hold.
            value['issue_checks'] = {key: {'status': 'RESOLVED', 'reason': 'The critic considers it resolved.'}
                                     for key in props['issue_checks']['properties']}
        return view.encode(value)

    journal = Journal()
    options = dict(intent=CourseIntent(), source_sha256='b'*64, route_fingerprint='c'*64,
                   review_policy=MATERIALITY_PRACTICAL_REVIEW_POLICY)
    result = await generate_practical_course(corpus, invoke=invoke, journal=journal, **options)
    assert owned_repairs == ['q2']
    assert result.diagnostics['practical_course']['lessons'][0]['questions'][0] == original['lessons'][0]['questions'][0]
    assert result.diagnostics['practical_course']['lessons'][0]['content'] == original['lessons'][0]['content']
    assert result.diagnostics['automated_review_passed'] is eventually_proved
    decision = completed_cycles[0].decision
    if eventually_proved:
        assert not decision.feedback
    else:
        assert len(decision.feedback) == 1
        held = decision.feedback[0]
        assert held['scope'] == 'source' and held['evidence']['problem'] == 'NEEDS_REVIEW'
        assert held['evidence']['original_finding']['id'] == 'q1'
        assert decision.question_ids == () and decision.lesson_ids == ()
    cold = Journal()
    cold.plans, cold.values = copy.deepcopy(journal.plans), copy.deepcopy(journal.values)
    async def forbidden(*args):
        raise AssertionError('Cold replay dispatched a new provider request.')
    replay = await generate_practical_course(corpus, invoke=forbidden, journal=cold, **options)
    assert replay.diagnostics == result.diagnostics


@pytest.mark.parametrize('flag', [True, 'yes', 1, None])
def test_atomic_review_materiality_requires_strict_owned_format(case, flag):
    _, packet, course = case
    with pytest.raises(ValueError, match='practical_atomic_audit_format_invalid'):
        atomic_audit_messages(packet, course, materiality_review=flag)


@pytest.mark.asyncio
@pytest.mark.parametrize('options', [{'materiality_review':True}, {'materiality_review':'yes'},
                                   {'materiality_review':1}, {'assessment_coverage':True,'materiality_review':True}])
async def test_invalid_materiality_policy_cannot_dispatch_a_model(case, options):
    _, packet, _ = case
    async def forbidden(*args):
        raise AssertionError('Invalid flags dispatched a model call.')
    with pytest.raises(ValueError, match='practical_revision_policy_invalid'):
        await run_lesson_practical_cycle(packet, {}, forbidden, **options)


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['direct', 'managed'])
@pytest.mark.parametrize('outcome', ['unproved_hold', 'nonmaterial', 'unknown_transport'])
async def test_typed_materiality_survives_both_transports_and_never_reissues_unknown(case, monkeypatch, provider, outcome):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import UUID

    from app.modules.ai.managed_luna_client import ManagedLunaClient
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    from app.modules.ai.v3.practical_arbitration import (
        adjudicate_practical_findings,
        arbitration_format,
        arbitration_messages,
    )
    from app.modules.ai.v3.response_contracts import matches_response_contract
    from app.modules.ai.v3.stage_checkpoint import stage_once
    from tests.unit.test_direct_luna_owned_stage import setup
    from tests.unit.test_v3_practical_materiality import decision, issue, row, value

    _, packet, course = case
    fake, journal, client, _, _ = setup()
    if provider == 'managed':
        client = ManagedLunaClient(base_url='http://127.0.0.1:18999/v1', api_key='synthetic',
            tenant_id=UUID(fake.tenant_id), user_id=fake.job.user_id, job_id=fake.job_id,
            credential_revision='synthetic', model='gpt-6-luna')
    item = issue(packet, 'owned-coverage')
    assessment = decision(item)
    options = dict(selectors=True, typed_findings=True, materiality_review=True)
    view = PracticalModelView(packet)
    fmt = view.schema(arbitration_format(packet, course, assessment, **options))
    verdict = 'NON_MATERIAL' if outcome == 'nonmaterial' else 'STYLE_ONLY'
    wire = view.encode(value(packet, course, [row(item, verdict=verdict)]))
    assert matches_response_contract(wire, fmt)
    prepare = AsyncMock(return_value=object())
    invoke = AsyncMock(return_value=SimpleNamespace(content=wire, model='gpt-6-luna',
        usage=SimpleNamespace(input_tokens=12, output_tokens=6, cached_input_tokens=None, reasoning_tokens=None)))
    if outcome == 'unknown_transport':
        invoke.side_effect = TimeoutError('Synthetic unknown outcome, not a real dispatched call.')
    monkeypatch.setattr(client, 'prepare', prepare)
    monkeypatch.setattr(client, 'invoke', invoke)
    observed = []
    def validate(value):
        observed.append(adjudicate_practical_findings(view.decode(value), packet, course, assessment,
            {'l1': [packet.blocks[0].block_id]}, **options))
    kwargs = dict(journal=journal, direct_client=client, stage='review', group_id='practical:arbitrate:synthetic',
        source_sha256='b'*64, route_fingerprint=client.cache_fingerprint(),
        messages=arbitration_messages(packet, course, assessment, model_view=view, **options),
        response_format=fmt, direct_max_output_tokens=128, response_validator=validate, invoke=AsyncMock())
    if outcome == 'unknown_transport':
        for owned_journal in (journal, copy.copy(journal)):
            with pytest.raises(ExtractionOutcomeUnknownError):
                await stage_once(**{**kwargs, 'journal':owned_journal})
        assert not observed
    else:
        assert await stage_once(**kwargs) == wire
        assert await stage_once(**{**kwargs, 'journal':copy.copy(journal)}) == wire
        assert observed and all(result.accepted is (outcome == 'nonmaterial') for result in observed)
        if outcome == 'unproved_hold':
            assert all(result.feedback[0]['issue_id'] == 'owned-coverage' for result in observed)
    prepare.assert_awaited_once()
    invoke.assert_awaited_once()
