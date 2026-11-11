"""V2 uses the actual owned stage gate with fake journal and provider boundaries."""
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.managed_luna_client import ManagedLunaClient
from app.modules.ai.v3.direct_luna_owned_stage import run_direct_owned_stage
from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
from app.modules.ai.v3.practical_author_transport import normalize_practical_author
from app.modules.ai.v3.practical_contract import _course_format
from app.modules.ai.v3.practical_editorial_contract import _review_format as prose_review_format
from app.modules.ai.v3.practical_option_predicates import _format as blind_review_format
from app.modules.ai.v3.revision_policy import POLICY, SIMPLE_COURSE_REVIEW_POLICY, SIMPLE_COURSE_REVIEW_V2_POLICY
from app.modules.ai.v3.service import generate_v3_course_from_corpus
from app.modules.ai.v3.simple_course_editor import _review_format
from app.modules.ai.v3.simple_course_revision_v2 import editor_format
from app.modules.ai.v3.stage_checkpoint import _digest, stage_once
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_v3_simple_course_editor import course
from tests.unit.test_v3_simple_service import corpus_fixture


class InspectionReachedError(Exception):
    pass


def client_for(journal):
    return ManagedLunaClient(base_url='http://127.0.0.1:19000/v1', api_key='synthetic',
        tenant_id=UUID(journal.tenant_id), user_id=journal.user_id, job_id=journal.job_id,
        credential_revision='synthetic', model='gpt-6-luna', reasoning_effort='high')


@pytest.mark.asyncio
@pytest.mark.parametrize('stage,group,fmt', [
    ('lesson', 'author', _course_format(['SRC1'])),
    ('review', 'review-content', prose_review_format(['SRC1'], ['lesson'], ['question'], 'a' * 64, 'b' * 64)),
    ('review', 'review-assessment', blind_review_format('a' * 64, 'b' * 64, ['item'], ['SRC1'])),
    ('review', 'review-explanations', _review_format(['SRC1'], ['question'], 'a' * 64, 'b' * 64)),
    ('repair', 'editor', editor_format(['SRC1'], 'a' * 64, 'b' * 64, [])),
])
async def test_v2_stage_once_reaches_owned_inspection(monkeypatch, stage, group, fmt):
    _, journal, _, _, _ = setup()
    journal.review_policy_bound = True
    journal.expected_review_policy = SIMPLE_COURSE_REVIEW_V2_POLICY
    client = client_for(journal)
    inspection = AsyncMock(side_effect=InspectionReachedError())
    monkeypatch.setattr('app.modules.ai.v3.direct_luna_owned_stage.inspect_owned_stage', inspection)
    invoke = AsyncMock(side_effect=AssertionError('unexpected provider'))
    messages = [{'role': 'user', 'content': 'approved source'}]
    try:
        with pytest.raises(InspectionReachedError):
            await stage_once(journal, stage=stage, group_id=f'practical:simple:{group}:v2:' + 'a' * 64 + ':output=32768',
                source_sha256='c' * 64, route_fingerprint='d' * 64, messages=messages, response_format=fmt,
                invoke=invoke, direct_client=client, direct_max_output_tokens=32768, response_validator=lambda value: value)
        inspection.assert_awaited_once()
        assert inspection.await_args.kwargs['plan']['request_sha256'] == _digest([messages, fmt])
        invoke.assert_not_awaited()
    finally:
        client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('uncertain', [False, True])
async def test_v2_service_runs_five_owned_stages_and_cold_replays(monkeypatch, uncertain):
    fake, journal, _, _, _ = setup()
    journal.review_policy_bound = True
    journal.expected_review_policy = SIMPLE_COURSE_REVIEW_V2_POLICY
    corpus = replace(corpus_fixture(), tenant_id=journal.tenant_id)
    client = client_for(journal)
    prepared, invoked = [], []

    async def prepare(messages, *, response_format, ownership_checkpoint, **kwargs):
        assert await ownership_checkpoint() is True
        prepared.append(response_format['json_schema']['name'])
        return messages, response_format

    async def invoke(value, *, ownership_checkpoint, **kwargs):
        assert await ownership_checkpoint() is True
        messages, fmt = value
        name = fmt['json_schema']['name']
        invoked.append(name)
        if name == 'v3_practical_option_predicates_v1':
            props = fmt['json_schema']['schema']['properties']
            items = props['judgments']['items']['properties']['item_id']['enum']
            result = {'source_fingerprint': props['source_fingerprint']['enum'][0],
                      'bank_fingerprint': props['bank_fingerprint']['enum'][0],
                      'judgments': [{'item_id': item, 'status': ('UNDECIDABLE' if uncertain else 'SUPPORTED') if index == 0 else 'NOT_SUPPORTED',
                                     'reason': 'Synthetic independent decision', 'source_refs': ['SRC1'],
                                     'compatible_case': 'Source-backed case' if index == 0 else ''}
                                    for index, item in enumerate(items)]}
            return SimpleNamespace(content=result, model='gpt-6-luna',
                usage=SimpleNamespace(input_tokens=100, output_tokens=25, cached_input_tokens=0, reasoning_tokens=5))
        payload = json.loads(messages[1]['content'])
        if name == 'practical_course':
            raw = course()
            raw['extra'] = None
            result = normalize_practical_author(json.dumps(raw), fmt)
        elif name == 'simple_course_review_v1':
            result = {'source_fingerprint': payload['source_fingerprint'], 'draft_fingerprint': payload['draft_fingerprint'],
                      'proposals': [], 'source_questions': []}
        elif name == 'v3_practical_editorial_review_v1':
            result = {'source_fingerprint': payload['source_fingerprint'], 'course_fingerprint': payload['draft_fingerprint'],
                      'summary': 'Synthetic source-to-prose review', 'findings': [], 'source_notes': [],
                      'narrative_sources': {'lesson': ['SRC1']}}
        else:
            assert name == 'simple_course_editor_v2'
            raw = {'source_fingerprint': payload['source_fingerprint'], 'draft_fingerprint': payload['draft_fingerprint'],
                   'course': course(), 'lesson_sources': [{'lesson_id': 'lesson', 'source_refs': ['SRC1']}],
                   'source_questions': [], 'source_question_decisions': [], 'extra': None}
            result = normalize_practical_author(json.dumps(raw), fmt)
        return SimpleNamespace(content=result, model='gpt-6-luna',
            usage=SimpleNamespace(input_tokens=100, output_tokens=25, cached_input_tokens=0, reasoning_tokens=5))

    monkeypatch.setattr(client, 'prepare', prepare)
    monkeypatch.setattr(client, 'invoke', invoke)
    monkeypatch.setattr('app.modules.ai.v3.service._practical_output_budget', AsyncMock(return_value=32768))
    args = dict(corpus=corpus, intent=CourseIntent(), generation_client=None, extraction_journal=journal,
        direct_client=client, revision_policy=POLICY, review_policy=SIMPLE_COURSE_REVIEW_V2_POLICY,
        route_fingerprint='d' * 64)
    try:
        first = await generate_v3_course_from_corpus(**args)
        cold = PendingStageJournal(journal.tenant_id, journal.user_id, journal.job_id, fake.sessions,
                                   verify_source=journal.verify_source)
        cold.repository = fake
        cold._lock_delivery = fake._lock_delivery
        cold._owned_key = fake._owned_key
        cold.read_owned_value_in_session = fake.read_owned_value_in_session
        cold.review_policy_bound = True
        cold.expected_review_policy = SIMPLE_COURSE_REVIEW_V2_POLICY
        second = await generate_v3_course_from_corpus(**{**args, 'extraction_journal': cold})
        assert prepared == invoked == ['practical_course', 'v3_practical_editorial_review_v1',
                                       'v3_practical_option_predicates_v1', 'simple_course_review_v1', 'simple_course_editor_v2']
        assert first.content == second.content and first.assessment == second.assessment
        assert len([key for key in fake.values if key.startswith('v3-stage-result:')]) == 5
        ref = first.content.modules[0].lessons[0].source_references[0]
        assert ref['doc_id'] == corpus.documents[0].doc_id
        assert ref['source_revision'] == corpus.documents[0].source_revision
        assert ref['source_text_sha256'] == corpus.documents[0].editorial_document.working_sha256
        assert first.diagnostics['v3_review_policy'] == SIMPLE_COURSE_REVIEW_V2_POLICY
        independent_issues = [row for row in first.diagnostics['draft_review']['issues'] if row['id'].startswith('simple-independent-')]
        assert len(independent_issues) == int(uncertain)
        if uncertain:
            assert independent_issues[0]['kind'] == 'editorial_review'
            assert independent_issues[0]['target_id'] == 'question'
            assert independent_issues[0]['evidence']['unverified'] is True
            assert first.diagnostics['requires_source_review'] is False
    finally:
        client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['v1_policy', 'v1_group', 'unbound', 'owner', 'request', 'source', 'route', 'format_missing', 'wrong_format'])
async def test_v2_transport_rejects_forged_plan_before_inspection(monkeypatch, fault):
    _, journal, _, _, _ = setup()
    journal.review_policy_bound = True
    journal.expected_review_policy = SIMPLE_COURSE_REVIEW_V2_POLICY
    client = client_for(journal)
    fmt = prose_review_format(['SRC1'], ['lesson'], ['question'], 'a' * 64, 'b' * 64)
    messages = [{'role': 'user', 'content': 'approved source'}]
    plan = dict(schema='v3-stage-checkpoint-v1', tenant_id=journal.tenant_id, job_id=journal.job_id,
        stage='review', group_id='practical:simple:review-content:v2:' + 'a' * 64 + ':output=32768',
        source_sha256='c' * 64, route_fingerprint='d' * 64, request_sha256=_digest([messages, fmt]))
    if fault == 'v1_policy':
        journal.expected_review_policy = SIMPLE_COURSE_REVIEW_POLICY
    elif fault == 'v1_group':
        plan['group_id'] = plan['group_id'].replace('review-content:v2', 'review:v1')
    elif fault == 'unbound':
        journal.review_policy_bound = False
    elif fault == 'owner':
        plan['job_id'] = 'another-job'
    elif fault == 'request':
        plan['request_sha256'] = 'e' * 64
    elif fault == 'source':
        plan['source_sha256'] = 'invalid'
    elif fault == 'route':
        plan['route_fingerprint'] = 'invalid'
    elif fault == 'wrong_format':
        fmt = _course_format(['SRC1'])
        plan['request_sha256'] = _digest([messages, fmt])
    else:
        fmt = None
    inspection = AsyncMock()
    monkeypatch.setattr('app.modules.ai.v3.direct_luna_owned_stage.inspect_owned_stage', inspection)
    try:
        with pytest.raises(ValueError, match='managed_structured_plan_invalid'):
            await run_direct_owned_stage(journal=journal, client=client, plan=plan, result_key='result',
                claim_key='claim', validate_value=lambda value: value, validate_response=lambda value: value,
                messages=messages, max_output_tokens=32768, response_format=fmt)
        inspection.assert_not_awaited()
    finally:
        client.close()
