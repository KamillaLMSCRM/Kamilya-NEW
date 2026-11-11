"""Exercise the actual owned transport seam, without any provider or DB request."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.ai.managed_luna_client import ManagedLunaClient
from app.modules.ai.v3.practical_contract import _course_format
from app.modules.ai.v3.revision_policy import SIMPLE_COURSE_REVIEW_POLICY
from app.modules.ai.v3.simple_course_editor import _editor_format, _review_format
from app.modules.ai.v3.stage_checkpoint import _digest, stage_once
from tests.unit.test_direct_luna_owned_stage import setup


class InspectionReachedError(Exception):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize('stage,group,fmt', [
    ('lesson', 'author', _course_format(['SRC1'])),
    ('review', 'review', _review_format(['SRC1'], ['L1', 'Q1'], 'a' * 64, 'b' * 64)),
    ('repair', 'editor', _editor_format(['SRC1'], 'a' * 64, 'b' * 64)),
])
async def test_simple_native_stage_reaches_owned_inspection_without_inference(monkeypatch, stage, group, fmt):
    _, journal, _, _, _ = setup()
    journal.review_policy_bound = True
    journal.expected_review_policy = SIMPLE_COURSE_REVIEW_POLICY
    client = ManagedLunaClient(base_url='http://127.0.0.1:19000/v1', api_key='synthetic',
        tenant_id=UUID(journal.tenant_id), user_id=journal.user_id, job_id=journal.job_id,
        credential_revision='synthetic', model='gpt-6-luna', reasoning_effort='high')
    inspection = AsyncMock(side_effect=InspectionReachedError())
    monkeypatch.setattr('app.modules.ai.v3.direct_luna_owned_stage.inspect_owned_stage', inspection)
    invoke = AsyncMock(side_effect=AssertionError('provider_must_not_be_called'))
    try:
        with pytest.raises(InspectionReachedError):
            await stage_once(journal, stage=stage,
                group_id='practical:simple:' + group + ':v1:' + 'a' * 64 + ':output=32768',
                source_sha256='c' * 64, route_fingerprint='d' * 64,
                messages=[{'role': 'user', 'content': 'approved source'}], response_format=fmt,
                invoke=invoke, direct_client=client, direct_max_output_tokens=32768,
                response_validator=lambda value: value)
        inspection.assert_awaited_once()
        invoke.assert_not_awaited()
        plan = inspection.await_args.kwargs['plan']
        assert plan['request_sha256'] == _digest([[{'role': 'user', 'content': 'approved source'}], fmt])
    finally:
        client.close()


@pytest.mark.asyncio
async def test_all_three_simple_stages_use_owned_transport_and_cold_replay(monkeypatch):
    import json
    from dataclasses import replace

    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.v3.practical_author_transport import normalize_practical_author
    from app.modules.ai.v3.revision_policy import POLICY
    from app.modules.ai.v3.service import generate_v3_course_from_corpus
    from tests.unit.test_v3_simple_service import corpus_fixture, responses

    fake, journal, _, _, _ = setup()
    journal.review_policy_bound = True
    journal.expected_review_policy = SIMPLE_COURSE_REVIEW_POLICY
    corpus = replace(corpus_fixture(), tenant_id=journal.tenant_id)
    client = ManagedLunaClient(base_url='http://127.0.0.1:19000/v1', api_key='synthetic',
        tenant_id=UUID(journal.tenant_id), user_id=journal.user_id, job_id=journal.job_id,
        credential_revision='synthetic', model='gpt-6-luna', reasoning_effort='high')
    kinds, respond = responses()
    prepared = []

    async def prepare(messages, *, response_format, ownership_checkpoint, **kwargs):
        assert await ownership_checkpoint() is True
        prepared.append(response_format['json_schema']['name'])
        return messages, response_format

    async def invoke(value, *, ownership_checkpoint, **kwargs):
        assert await ownership_checkpoint() is True
        messages, fmt = value
        result = await respond(messages, fmt)
        if fmt['json_schema']['name'] in {'practical_course', 'simple_course_editor_v1'}:
            result = normalize_practical_author(result if type(result) is str else json.dumps(result), fmt)
        return SimpleNamespace(content=result, model='gpt-6-luna',
            usage=SimpleNamespace(input_tokens=100, output_tokens=25, cached_input_tokens=0, reasoning_tokens=5))

    monkeypatch.setattr(client, 'prepare', prepare)
    monkeypatch.setattr(client, 'invoke', invoke)
    monkeypatch.setattr('app.modules.ai.v3.service._practical_output_budget', AsyncMock(return_value=32768))
    args = dict(corpus=corpus, intent=CourseIntent(), generation_client=None, extraction_journal=journal,
        direct_client=client, revision_policy=POLICY, review_policy=SIMPLE_COURSE_REVIEW_POLICY,
        route_fingerprint='d' * 64)
    try:
        first = await generate_v3_course_from_corpus(**args)
        second = await generate_v3_course_from_corpus(**args)
        assert prepared == kinds == ['practical_course', 'simple_course_review_v1', 'simple_course_editor_v1']
        assert first.content == second.content and first.assessment == second.assessment
        assert len([k for k in fake.values if k.startswith('v3-stage-result:')]) == 3
    finally:
        client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['old_policy', 'unbound', 'owner', 'request', 'source', 'format_missing'])
async def test_simple_owned_transport_rejects_forged_plan_before_inspection(monkeypatch, fault):
    from app.modules.ai.v3.direct_luna_owned_stage import run_direct_owned_stage

    _, journal, _, _, _ = setup()
    journal.review_policy_bound = True
    journal.expected_review_policy = SIMPLE_COURSE_REVIEW_POLICY
    client = ManagedLunaClient(base_url='http://127.0.0.1:19000/v1', api_key='synthetic',
        tenant_id=UUID(journal.tenant_id), user_id=journal.user_id, job_id=journal.job_id,
        credential_revision='synthetic', model='gpt-6-luna', reasoning_effort='high')
    fmt = _review_format(['SRC1'], ['L1'], 'a' * 64, 'b' * 64)
    messages = [{'role': 'user', 'content': 'approved source'}]
    plan = dict(schema='v3-stage-checkpoint-v1', tenant_id=journal.tenant_id, job_id=journal.job_id,
        stage='review', group_id='practical:simple:review:v1:' + 'a' * 64 + ':output=32768',
        source_sha256='c' * 64, route_fingerprint='d' * 64, request_sha256=_digest([messages, fmt]))
    if fault == 'old_policy':
        journal.expected_review_policy = 'v3-practical-source-review-v36'
    elif fault == 'unbound':
        journal.review_policy_bound = False
    elif fault == 'owner':
        plan['job_id'] = 'another-job'
    elif fault == 'request':
        plan['request_sha256'] = 'e' * 64
    elif fault == 'source':
        plan['source_sha256'] = 'invalid'
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
