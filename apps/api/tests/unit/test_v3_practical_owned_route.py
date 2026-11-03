import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.ai.managed_luna_client import ManagedLunaClient
from app.modules.ai.v3.direct_luna_owned_stage import run_direct_owned_stage
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.pending_stage_transactions import has_pending
from app.modules.ai.v3.practical_audit_units import audit_units
from app.modules.ai.v3.practical_contract import course_response_format
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_patch import practical_patch_format
from app.modules.ai.v3.practical_review import interpret_practical_review, practical_review_format
from app.modules.ai.v3.practical_source_audit import source_audit_format
from app.modules.ai.v3.stage_checkpoint import _digest, stage_once, stage_plan
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_v3_practical_review import example, finding


@pytest.mark.parametrize('provider', ['direct', 'managed'])
@pytest.mark.parametrize('stage', ['lesson', 'review', 'repair', 'source_audit'])
@pytest.mark.parametrize('aliases', [False, True])
@pytest.mark.asyncio
async def test_practical_stage_owned_checkpoint_and_replay(monkeypatch, provider, stage, aliases):
    packet, course, review, ref = example.__wrapped__()
    fake, journal, direct, _plan, _validator = setup()
    client = direct
    model = 'gpt-6-luna'
    if provider == 'managed':
        client = ManagedLunaClient(base_url='http://127.0.0.1:18999/v1', api_key='synthetic',
            tenant_id=UUID(journal.tenant_id), user_id=journal.user_id, job_id=journal.job_id,
            credential_revision='synthetic')
        model = 'gpt-5.6-luna'
    if stage == 'source_audit':
        fmt = source_audit_format(packet, course)
        body = {key: copy.deepcopy(review[key]) for key in (
            'source_fingerprint', 'source_review', 'source_notes', 'findings', 'narrative_sources')}
        grouping = audit_units(packet)
        body['source_units_fingerprint'] = grouping.fingerprint
        body['source_checks'] = [{'unit_id': key, 'source_refs': list(refs), 'status': 'TAUGHT',
            'lesson_ids': [lesson['id'] for lesson in course['lessons']], 'reason': 'Checked source block.'}
            for key, refs in grouping.groups]
        group, stage = 'practical:source-audit:' + 'a' * 64, 'review'
    elif stage == 'lesson':
        fmt, body, group = course_response_format(packet), course, 'practical:author:v1'
    elif stage == 'review':
        fmt, body, group = practical_review_format(packet, course), review, 'practical:review:' + 'a' * 64
    else:
        review['findings'] = [finding('question', 'question', ref)]
        decision = interpret_practical_review(review, packet, course)
        fmt = practical_patch_format(packet, course, decision)
        body = {'course_fingerprint': fmt['json_schema']['schema']['properties']['course_fingerprint']['enum'][0],
            'new_lessons': [], 'new_questions': [], 'question_updates': {
            'question': course['lessons'][0]['questions'][0]}}
        group = 'practical:repair:' + 'a' * 64
    view = PracticalModelView(packet)
    canonical = copy.deepcopy(body)
    if aliases:
        fmt, body = view.schema(fmt), view.encode(body)
    validated = []
    def semantic_validator(value):
        decoded = view.decode(value) if aliases else value
        assert decoded == canonical
        validated.append(decoded)
    messages = [{'role': 'user', 'content': 'synthetic request'}]
    prepare = AsyncMock(return_value=object())
    invoke = AsyncMock(return_value=SimpleNamespace(content=body, model=model,
        usage=SimpleNamespace(input_tokens=12, output_tokens=6, cached_input_tokens=None, reasoning_tokens=None)))
    monkeypatch.setattr(client, 'prepare', prepare)
    monkeypatch.setattr(client, 'invoke', invoke)
    options = dict(journal=journal, direct_client=client, stage=stage, group_id=group,
        source_sha256='b' * 64, route_fingerprint=client.cache_fingerprint(),
        messages=messages, response_format=fmt, direct_max_output_tokens=128,
        response_validator=semantic_validator)
    plan = stage_plan(journal, **{key: options[key] for key in (
        'stage', 'group_id', 'source_sha256', 'route_fingerprint', 'messages', 'response_format')})
    assert plan['request_sha256'] == _digest([messages, fmt]) and plan['stage'] == stage and plan['group_id'] == group
    assert await stage_once(invoke=AsyncMock(), **options) == body
    cold_options = {**options, 'journal': copy.copy(journal)}
    assert await stage_once(invoke=AsyncMock(), **cold_options) == body
    prepare.assert_awaited_once()
    invoke.assert_awaited_once()
    assert len(validated) >= 2  # Before persistence and again on replay.
    assert any(value.get('response') == body for value in fake.values.values() if isinstance(value, dict))


@pytest.mark.parametrize('defect', ['group', 'hash'])
@pytest.mark.asyncio
async def test_unowned_practical_plan_rejected_before_prepare(monkeypatch, defect):
    packet, _course, _review, _ref = example.__wrapped__()
    fake, journal, client, _plan, validator = setup()
    fmt = course_response_format(packet)
    messages = [{'role': 'user', 'content': 'synthetic request'}]
    plan = stage_plan(journal, stage='lesson', group_id='practical:author:v1', source_sha256='b' * 64,
        route_fingerprint=client.cache_fingerprint(), messages=messages, response_format=fmt)
    if defect == 'group':
        plan['group_id'] = 'foreign:author'
    else:
        plan['request_sha256'] = '0' * 64
    prepare = AsyncMock()
    monkeypatch.setattr(client, 'prepare', prepare)
    with pytest.raises(ValueError, match='managed_structured_plan_invalid'):
        await run_direct_owned_stage(journal=journal, client=client, plan=plan, result_key='result',
            claim_key='claim', validate_value=validator, validate_response=lambda value: value,
            messages=messages, max_output_tokens=128, response_format=fmt)
    prepare.assert_not_awaited()
    assert not fake.plans


@pytest.mark.asyncio
async def test_foreign_review_target_cannot_finalize_or_reinvoke(monkeypatch):
    packet, course, review, ref = example.__wrapped__()
    review['findings'] = [finding('question', 'lesson', ref)]
    fmt = practical_review_format(packet, course)
    from app.modules.ai.v3.practical_review import matches_practical_review
    assert not matches_practical_review(review, fmt)
    fake, journal, client, _plan, _validator = setup()
    prepare = AsyncMock(return_value=object())
    invoke = AsyncMock(return_value=SimpleNamespace(content=review, model='gpt-6-luna',
        usage=SimpleNamespace(input_tokens=12, output_tokens=6, cached_input_tokens=None, reasoning_tokens=None)))
    monkeypatch.setattr(client, 'prepare', prepare)
    monkeypatch.setattr(client, 'invoke', invoke)
    def validate_review(value):
        interpret_practical_review(value, packet, course)
    options = dict(journal=journal, direct_client=client, stage='review',
        group_id='practical:review:' + 'a' * 64, source_sha256='b' * 64,
        route_fingerprint=client.cache_fingerprint(), messages=[{'role': 'user', 'content': 'synthetic'}],
        response_format=fmt, direct_max_output_tokens=128,
        response_validator=validate_review)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(invoke=AsyncMock(), **options)
    assert has_pending(fake.job.result)
    assert not any(value.get('response') == review for value in fake.values.values() if isinstance(value, dict))
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(invoke=AsyncMock(), **{**options, 'journal': copy.copy(journal)})
    prepare.assert_awaited_once()
    invoke.assert_awaited_once()
