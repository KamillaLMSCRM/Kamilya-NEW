import copy
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.source_fidelity import ConversionFidelity
from app.modules.ai.v3 import practical_focused_cycle as cycle
from app.modules.ai.v3.focused_stage_guard import focused_source_review_required, focused_stage_allowed
from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
from app.modules.ai.v3.practical_action_object_graph import request as graph_request
from app.modules.ai.v3.practical_contract import build_practical_source_packet
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_service import practical_artifacts
from app.modules.ai.v3.revision_policy import (
    COHERENT_EDITORIAL_REVIEW_POLICY,
    FOCUSED_EDITORIAL_REVIEW_POLICY,
    is_autonomous_editorial_policy,
    is_editorial_policy,
    read_review_policy,
)
from app.modules.ai.v3.stage_checkpoint import _digest, stage_once, stage_plan
from tests.unit.test_practical_source_editor import empty_source_editor_review


@pytest.fixture
def focused_case():
    text = 'Не касаться поверхности.'
    fidelity = ConversionFidelity(metadata_present=True, metadata_verified=True)
    doc = DirectSourceDocument('doc', 'Source', 'file', 'other', 'r', (),
                               conversion_fidelity=fidelity, source_text=text)
    corpus = DirectSourceCorpus('tenant', (doc,), len(text), 0)
    packet = build_practical_source_packet(corpus)
    q = {'id': 'q', 'prompt': 'Question?', 'choices': ['a', 'b', 'c'], 'correct_index': 0,
         'explanation': 'Reason', 'source_refs': [packet.blocks[0].block_id]}
    course = {'title': 'Course', 'lessons': [{'id': 'lesson', 'title': 'Title', 'content': text, 'questions': [q]}]}
    return corpus, packet, course


def test_policy_is_versioned_and_stage_guard_is_exact():
    assert read_review_policy({'v3_review_policy': FOCUSED_EDITORIAL_REVIEW_POLICY}) == FOCUSED_EDITORIAL_REVIEW_POLICY
    assert read_review_policy({'v3_review_policy': COHERENT_EDITORIAL_REVIEW_POLICY}) == COHERENT_EDITORIAL_REVIEW_POLICY
    assert is_editorial_policy(FOCUSED_EDITORIAL_REVIEW_POLICY) and is_autonomous_editorial_policy(FOCUSED_EDITORIAL_REVIEW_POLICY)
    _, fmt, _ = graph_request('source', [{'id': 'x', 'text': 'Птица видит дерево.'}])
    group = 'practical:focused:graph:source:v36:' + 'a' * 64 + ':output=8192'
    def valid(_value):
        return None
    assert focused_stage_allowed('review', group, fmt, policy=FOCUSED_EDITORIAL_REVIEW_POLICY, validator=valid)
    for wrong in (group.rsplit(':output=', 1)[0], group.replace('source', 'learner'), group.replace('v36', 'v35'), group + 'x'):
        assert not focused_stage_allowed('review', wrong, fmt, policy=FOCUSED_EDITORIAL_REVIEW_POLICY, validator=valid)
    assert not focused_stage_allowed('repair', group, fmt, policy=FOCUSED_EDITORIAL_REVIEW_POLICY, validator=valid)
    assert not focused_stage_allowed('review', group, fmt, policy=COHERENT_EDITORIAL_REVIEW_POLICY, validator=valid)
    assert not focused_stage_allowed('review', group, fmt, policy=FOCUSED_EDITORIAL_REVIEW_POLICY, validator=None)
    changed = copy.deepcopy(fmt)
    changed['json_schema']['schema']['properties']['role']['enum'] = ['learner']
    assert not focused_stage_allowed('review', group, changed, policy=FOCUSED_EDITORIAL_REVIEW_POLICY, validator=valid)


@pytest.mark.asyncio
async def test_direct_owned_native_graph_has_exact_allowlist(monkeypatch):
    from app.modules.ai.managed_luna_client import ManagedLunaClient

    journal = PendingStageJournal('tenant', uuid4(), 'job', lambda: None)
    journal.review_policy_bound = True
    journal.expected_review_policy = FOCUSED_EDITORIAL_REVIEW_POLICY
    journal.verify_source = AsyncMock(return_value=True)
    messages, fmt, local = graph_request('source', [{'id': 'x', 'text': 'Птица видит дерево.'}])
    value = {'role': 'source', 'input_fingerprint': local['input_fingerprint'], 'decisions': [
        {'token_id': token['token_id'], 'classification': 'UNKNOWN', 'object_kind': 'UNKNOWN',
         'object_quote': '', 'negation_quote': '', 'note': ''} for token in local['candidates']]}
    captured = []
    async def fake_owned(**kwargs):
        captured.append(kwargs)
        assert kwargs['response_format'] == fmt
        return kwargs['validate_response'](value)
    monkeypatch.setattr('app.modules.ai.v3.direct_luna_owned_stage.run_direct_owned_stage', fake_owned)
    client = ManagedLunaClient(base_url='http://127.0.0.1:18999/v1', api_key='synthetic', tenant_id=uuid4(),
        user_id=uuid4(), job_id=str(uuid4()), credential_revision='synthetic', model='gpt-6-luna',
        deadline_seconds=300, reasoning_effort='high')
    group = 'practical:focused:graph:source:v36:' + 'a' * 64 + ':output=8192'
    try:
        result = await stage_once(journal, stage='review', group_id=group, source_sha256='b' * 64,
            route_fingerprint='c' * 64, messages=messages, response_format=fmt, invoke=AsyncMock(),
            direct_client=client, direct_max_output_tokens=8192, response_validator=lambda _raw: None)
        assert result == value and len(captured) == 1
        with pytest.raises(ValueError, match='focused_stage_scope_invalid'):
            await stage_once(journal, stage='review', group_id=group.replace('source', 'learner'),
                source_sha256='b' * 64, route_fingerprint='c' * 64, messages=messages,
                response_format=fmt, invoke=AsyncMock(), direct_client=client, response_validator=lambda _raw: None)
        assert len(captured) == 1
    finally:
        client.close()


@pytest.mark.asyncio
async def test_direct_owned_second_guard_checks_scope_and_request_hash(monkeypatch):
    from app.modules.ai.managed_luna_client import ManagedLunaClient
    from app.modules.ai.v3 import direct_luna_owned_stage as direct

    journal = PendingStageJournal('tenant', uuid4(), 'job', lambda: None)
    journal.review_policy_bound = True
    journal.expected_review_policy = FOCUSED_EDITORIAL_REVIEW_POLICY
    journal.verify_source = AsyncMock(return_value=True)
    messages, fmt, _ = graph_request('source', [{'id': 'x', 'text': 'Птица видит дерево.'}])
    group = 'practical:focused:graph:source:v36:' + 'a' * 64 + ':output=8192'
    plan = stage_plan(journal, stage='review', group_id=group, source_sha256='b' * 64,
                      route_fingerprint='c' * 64, messages=messages, response_format=fmt)
    inspect_stage = AsyncMock(return_value=SimpleNamespace(decision='replay', result={'replayed': True}))
    monkeypatch.setattr(direct, 'inspect_owned_stage', inspect_stage)
    client = ManagedLunaClient(base_url='http://127.0.0.1:18999/v1', api_key='synthetic', tenant_id=uuid4(),
        user_id=uuid4(), job_id=str(uuid4()), credential_revision='synthetic', model='gpt-6-luna',
        deadline_seconds=300, reasoning_effort='high')
    async def run(candidate_plan, schema=fmt):
        return await direct.run_direct_owned_stage(journal=journal, client=client, plan=candidate_plan,
            result_key='result', claim_key='claim', validate_value=lambda value: value,
            validate_response=lambda value: value, messages=messages, max_output_tokens=8192, response_format=schema)
    try:
        assert await run(plan) == {'replayed': True}
        for change in ({'request_sha256': 'f' * 64}, {'tenant_id': 'foreign'}, {'job_id': 'foreign'},
                       {'group_id': group.replace('source', 'learner')}, {'source_sha256': 'bad'}):
            with pytest.raises(ValueError, match='managed_structured_plan_invalid'):
                await run({**plan, **change})
        with pytest.raises(ValueError, match='managed_structured_plan_invalid'):
            await run(plan, None)
        journal.expected_review_policy = COHERENT_EDITORIAL_REVIEW_POLICY
        with pytest.raises(ValueError, match='managed_structured_plan_invalid'):
            await run(plan)
        assert inspect_stage.await_count == 1
    finally:
        client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('drift', ['none', 'policy', 'marker', 'owner', 'source'])
async def test_existing_native_final_fence_covers_v36(monkeypatch, drift):
    from app.modules.ai import pipeline
    from app.modules.ai.v3.owned_source_context import OwnedSourceContext
    from app.modules.ai.v3.revision_policy import EDITORIAL_ORDINARY_EXTENDED_MARKER, EDITORIAL_ORDINARY_KEY
    from tests.unit.test_v3_native_final_source import native_fixture

    monkeypatch.setattr('app.core.config.get_settings', lambda: None)
    monkeypatch.setattr(OwnedSourceContext, 'verify_locked', AsyncMock(return_value=drift != 'source'))
    state, job, _document = native_fixture(FOCUSED_EDITORIAL_REVIEW_POLICY)
    monkeypatch.setattr('app.modules.ai.qa_luna_dev_route.QA_TENANT', uuid4())
    state.source_analysis[EDITORIAL_ORDINARY_KEY] = EDITORIAL_ORDINARY_EXTENDED_MARKER
    job.params['source_analysis'][EDITORIAL_ORDINARY_KEY] = EDITORIAL_ORDINARY_EXTENDED_MARKER
    if drift == 'policy':
        job.params['source_analysis']['v3_review_policy'] = COHERENT_EDITORIAL_REVIEW_POLICY
    elif drift == 'marker':
        state.source_analysis[EDITORIAL_ORDINARY_KEY] = 'forged'
    elif drift == 'owner':
        job.user_id = uuid4()
    if drift == 'none':
        await pipeline._verify_native_practical_final_source(None, job, state, job.tenant_id, state.native_practical_final[0].user_id)
    else:
        with pytest.raises(ValueError, match='v3_native_final_source_unverified'):
            await pipeline._verify_native_practical_final_source(None, job, state, job.tenant_id, state.native_practical_final[0].user_id)


@pytest.mark.asyncio
@pytest.mark.parametrize('drift', ['none', 'policy', 'route', 'source'])
async def test_existing_managed_final_fence_covers_v36(monkeypatch, drift):
    from app.modules.ai import pipeline
    from app.modules.ai.delivery_ownership import delivery_id
    from app.modules.ai.qa_luna_dev_route import QA_TENANT
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    from app.modules.ai.v3.qa_luna_pending_policy import KEY, MANAGED_POLICY
    from app.modules.ai.v3.revision_policy import EDITORIAL_MANAGED_QA_MARKER, EDITORIAL_QA_KEY
    from tests.unit.test_v3_editorial_managed_route import config
    from tests.unit.test_v3_final_source_save_fence import owned

    state, job, user = owned()
    monkeypatch.setattr('app.core.config.get_settings', lambda: config('vm-development-worker'))
    state.source_analysis.update({KEY: MANAGED_POLICY, EDITORIAL_QA_KEY: EDITORIAL_MANAGED_QA_MARKER,
                                  'v3_review_policy': FOCUSED_EDITORIAL_REVIEW_POLICY})
    job.params['source_analysis'].update({KEY: MANAGED_POLICY, EDITORIAL_QA_KEY: EDITORIAL_MANAGED_QA_MARKER,
                                          'v3_review_policy': FOCUSED_EDITORIAL_REVIEW_POLICY})
    job.course_id = None
    monkeypatch.setattr(state.owned_v3_source_context, 'verify_locked', AsyncMock(return_value=drift != 'source'))
    if drift == 'policy':
        job.params['source_analysis']['v3_review_policy'] = COHERENT_EDITORIAL_REVIEW_POLICY
    elif drift == 'route':
        job.result['v3_owned_route_binding']['fingerprint'] = 'b' * 64
    token = delivery_id.set('delivery')
    try:
        if drift == 'none':
            await pipeline._verify_fresh_v3_final_source(object(), job, state, QA_TENANT, user)
            await pipeline._verify_native_practical_final_source(object(), job, state, QA_TENANT, user)
        else:
            with pytest.raises(ExtractionOutcomeUnknownError, match='v3_final_source_unverified'):
                await pipeline._verify_fresh_v3_final_source(object(), job, state, QA_TENANT, user)
    finally:
        delivery_id.reset(token)


@pytest.mark.asyncio
async def test_fake_owned_journal_repair_then_cold_replay_and_drift(focused_case):
    corpus, packet, course = focused_case
    view = PracticalModelView(packet)
    journal = PendingStageJournal('tenant', uuid4(), 'job', lambda: None)
    journal.review_policy_bound = True
    journal.expected_review_policy = FOCUSED_EDITORIAL_REVIEW_POLICY
    source_hash, route_hash = 'a' * 64, 'b' * 64
    requested = {'source': source_hash, 'route': route_hash}
    actor = journal.user_id
    calls, store = [], {}
    async def verify(_session, _job, plan):
        return (plan['source_sha256'] == source_hash and plan['route_fingerprint'] == route_hash
                and journal.user_id == actor)
    journal.verify_source = verify

    async def pending(*, plan, result_key, claim_key, validate_value, validate_response, invoke, _owned_claim_guard,
                      author_custody=None):
        if not await journal.verify_source(None, None, plan):
            raise ValueError('owned_source_or_route_drift')
        if result_key not in store:
            received = await invoke()
            value = validate_response(received)
            store[result_key] = {'identity': _digest(plan), 'response': value, 'response_sha256': _digest(value)}
            custody = author_custody(received) if author_custody is not None else None
            if custody is not None:
                store[result_key]['author_custody'] = custody
        return validate_value(store[result_key])
    journal.run_pending = pending

    async def stage(name, group, messages, fmt, validator):
        async def invoke():
            calls.append(group)
            if ':author:' in group:
                return view.encode(copy.deepcopy(course))
            if ':graph:' in group:
                data = json.loads(messages[1]['content'])
                return {'role': data['role'], 'input_fingerprint': data['input_fingerprint'], 'decisions': [
                    {'token_id': row['token_id'], 'classification': 'UNKNOWN', 'object_kind': 'UNKNOWN',
                     'object_quote': '', 'negation_quote': '', 'note': ''} for row in data['candidate_tokens']]}
            if ':editorial-review:' in group:
                return empty_source_editor_review(fmt)
            if ':questions:' in group:
                payload = json.loads(messages[1]['content'].split('\nQUESTION_EDITOR_JSON\n', 1)[1])
                return {'source_fingerprint': packet.fingerprint, 'course_fingerprint': payload['course_fingerprint'],
                        'checks': [{'question_id': 'q', 'status': 'VALID', 'reason': 'reviewed'}], 'updates': []}
            if ':question-repair:' in group:
                assert 'UNVERIFIED_CURRENT_QUESTION_FINDINGS_JSON' in messages[1]['content']
                payload = json.loads(messages[1]['content'].split('\nQUESTION_EDITOR_JSON\n', 1)[1].split(
                    '\nUNVERIFIED_CURRENT_QUESTION_FINDINGS_JSON\n', 1)[0])
                q = copy.deepcopy(payload['questions'][0]['questions'][0])
                q['prompt'] = 'Repaired?'
                return {'source_fingerprint': packet.fingerprint, 'course_fingerprint': payload['course_fingerprint'],
                        'checks': [{'question_id': 'q', 'status': 'REPAIRED', 'reason': 'corrected'}],
                        'updates': [{'lesson_id': 'lesson', 'question': q}]}
            if ':blind:' in group:
                props = fmt['json_schema']['schema']['properties']
                ids = props['judgments']['items']['properties']['item_id']['enum']
                updated = 'Repaired?' in messages[1]['content']
                return {'source_fingerprint': props['source_fingerprint']['enum'][0],
                    'bank_fingerprint': props['bank_fingerprint']['enum'][0], 'judgments': [
                        {'item_id': item, 'status': ('SUPPORTED' if index == 0 else 'NOT_SUPPORTED') if updated else 'UNDECIDABLE',
                         'reason': 'read', 'source_refs': ['SRC1'] if updated and index == 0 else [],
                         'compatible_case': 'source-grounded' if updated and index == 0 else ''}
                        for index, item in enumerate(ids)]}
            raise AssertionError(group)
        return await stage_once(journal, stage=name, group_id=group + ':output=8192', source_sha256=requested['source'],
                                route_fingerprint=requested['route'], messages=messages, response_format=fmt, invoke=invoke,
                                response_validator=validator)

    result = await cycle.run_focused_cycle(packet, corpus, CourseIntent(), (), stage,
                                           max_output_tokens=8192, max_revisions=2)
    assert result.course['lessons'][0]['questions'][0]['prompt'] == 'Repaired?'
    assert result.course['lessons'][0]['content'] == course['lessons'][0]['content']
    assert result.decision.accepted is False and not result.decision.source_uncertain
    assert len([g for g in calls if ':question-repair:' in g]) == 1
    assert len([g for g in calls if ':blind:' in g]) == 2
    first_calls = list(calls)
    replayed = await cycle.run_focused_cycle(packet, corpus, CourseIntent(), (), stage,
                                             max_output_tokens=8192, max_revisions=2)
    assert replayed.course == result.course and calls == first_calls
    journal.expected_review_policy = COHERENT_EDITORIAL_REVIEW_POLICY
    with pytest.raises(ValueError, match='focused_stage_scope_invalid'):
        await cycle.run_focused_cycle(packet, corpus, CourseIntent(), (), stage, max_output_tokens=8192, max_revisions=2)
    assert calls == first_calls
    journal.expected_review_policy = FOCUSED_EDITORIAL_REVIEW_POLICY
    for field in ('source', 'route'):
        requested[field] = 'c' * 64
        with pytest.raises(ValueError, match='owned_source_or_route_drift'):
            await cycle.run_focused_cycle(packet, corpus, CourseIntent(), (), stage, max_output_tokens=8192, max_revisions=2)
        requested[field] = source_hash if field == 'source' else route_hash
    journal.user_id = uuid4()
    with pytest.raises(ValueError, match='owned_source_or_route_drift'):
        await cycle.run_focused_cycle(packet, corpus, CourseIntent(), (), stage, max_output_tokens=8192, max_revisions=2)
    assert calls == first_calls
@pytest.mark.asyncio
async def test_usable_pending_draft_does_not_invent_provenance(focused_case):
    corpus, packet, course = focused_case
    from app.modules.ai.v3.practical_cycle import PracticalCycleResult
    from app.modules.ai.v3.practical_review import PracticalReviewDecision
    review = {'source_fingerprint': packet.fingerprint, 'course_fingerprint': _digest(course),
              'source_notes': [], 'narrative_sources': {'lesson': []}}
    result = PracticalCycleResult(course, review, PracticalReviewDecision(False, False, (), (), False, ()),
        ({'autonomous_editorial': True, 'focused_observations_unverified': True,
          'unverified_revised_prose': ['lesson']},), 'focused_review_pending',
        standalone_review=True, editorial_review=True)
    artifacts = practical_artifacts(result, corpus, packet, 'a' * 64, editorial_policy=FOCUSED_EDITORIAL_REVIEW_POLICY)
    assert artifacts.diagnostics['automated_review_passed'] is False
    assert artifacts.diagnostics['requires_editorial_review'] is True
    assert artifacts.diagnostics['requires_source_review'] is False
    assert artifacts.diagnostics['practical_unverified_prose_lesson_ids'] == ['lesson']
    assert artifacts.diagnostics['draft_review']['source_clarification_required'] is False
    assert artifacts.diagnostics['draft_review']['human_review_required'] is True
    assert artifacts.diagnostics['draft_review']['draft_fingerprint'] == _digest(course)
    assert artifacts.content.modules[0].lessons[0].source_validation_status == 'needs_review'
    assert focused_source_review_required(artifacts) is False
    damaged = copy.deepcopy(artifacts)
    damaged.content.modules[0].lessons[0].content += '[UNREADABLE_PERCENTAGE_VALUE]'
    assert focused_source_review_required(damaged) is True
    stale = copy.deepcopy(artifacts)
    stale.diagnostics['draft_review']['draft_fingerprint'] = 'f' * 64
    assert focused_source_review_required(stale) is True
    unverified = replace(corpus, documents=(replace(corpus.documents[0], conversion_fidelity=ConversionFidelity.unverified()),))
    held = practical_artifacts(result, unverified, packet, 'a' * 64, editorial_policy=FOCUSED_EDITORIAL_REVIEW_POLICY)
    assert held.diagnostics['requires_source_review'] is True
    assert focused_source_review_required(held) is True
