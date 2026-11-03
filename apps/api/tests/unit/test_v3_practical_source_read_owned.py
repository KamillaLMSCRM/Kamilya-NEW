"""Offline source-reader claim, validation, and replay through the owned journal."""
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.ai.managed_luna_client import ManagedLunaClient
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.pending_stage_transactions import has_pending
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_source_reader import (
    source_read_format,
    source_read_messages,
    source_reader_parts,
    validate_source_read,
)
from app.modules.ai.v3.stage_checkpoint import _digest, stage_once, stage_plan
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_v3_practical_source_reader import packet, response


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['valid', 'context', 'foreign', 'unknown'])
async def test_managed_source_reader_claim_and_cold_hold(monkeypatch, outcome):
    source = packet('# 1. Definitions\nTerms.\n\n# 2. Work\nRule.\n')
    first, part = source_reader_parts(source)
    view = PracticalModelView(source)
    fmt = view.schema(source_read_format(source, part))
    messages = source_read_messages(source, part, view)
    body = response(source, part)
    if outcome == 'context':
        body['source_checks'][0]['rules'][0]['source_refs'] = list(first.groups[0][1])
    elif outcome == 'foreign':
        body['source_checks'][0]['rules'][0]['source_refs'] = ['foreign']
    if outcome == 'foreign':
        wire = view.encode(response(source, part))
        wire['source_checks'][0]['rules'][0]['source_refs'] = ['SRC9999']
    else:
        wire = view.encode(body)
    fake, journal, _direct, _plan, _validator = setup()
    client = ManagedLunaClient(base_url='http://127.0.0.1:18999/v1', api_key='synthetic',
        tenant_id=UUID(journal.tenant_id), user_id=journal.user_id, job_id=journal.job_id,
        credential_revision='r1')
    prepare = AsyncMock(return_value=object())
    if outcome == 'unknown':
        invoke = AsyncMock(side_effect=RuntimeError('synthetic unknown'))
    else:
        invoke = AsyncMock(return_value=SimpleNamespace(content=wire, model='gpt-5.6-luna',
            usage=SimpleNamespace(input_tokens=12, output_tokens=6, cached_input_tokens=None, reasoning_tokens=None)))
    monkeypatch.setattr(client, 'prepare', prepare)
    monkeypatch.setattr(client, 'invoke', invoke)
    def validate(value):
        validate_source_read(view.decode(value), source, part)
    options = dict(journal=journal, direct_client=client, stage='review',
        group_id='practical:source-read:' + part.fingerprint, source_sha256='b' * 64,
        route_fingerprint=client.cache_fingerprint(), messages=messages, response_format=fmt,
        direct_max_output_tokens=128, response_validator=validate)
    plan = stage_plan(journal, **{key: options[key] for key in (
        'stage', 'group_id', 'source_sha256', 'route_fingerprint', 'messages', 'response_format')})
    assert plan['request_sha256'] == _digest([messages, fmt])
    if outcome == 'valid':
        assert await stage_once(invoke=AsyncMock(), **options) == wire
        assert await stage_once(invoke=AsyncMock(), **{**options, 'journal': copy.copy(journal)}) == wire
        assert not has_pending(fake.job.result)
        assert any(value.get('response') == wire for value in fake.values.values() if isinstance(value, dict))
        journal.verify_source = AsyncMock(return_value=False)
        with pytest.raises(ExtractionOutcomeUnknownError):
            await stage_once(invoke=AsyncMock(), **{**options, 'journal': copy.copy(journal)})
    else:
        with pytest.raises(ExtractionOutcomeUnknownError):
            await stage_once(invoke=AsyncMock(), **options)
        assert has_pending(fake.job.result)
        assert not any(value.get('response') == wire for value in fake.values.values() if isinstance(value, dict))
        with pytest.raises(ExtractionOutcomeUnknownError):
            await stage_once(invoke=AsyncMock(), **{**options, 'journal': copy.copy(journal)})
    prepare.assert_awaited_once()
    assert prepare.await_args.kwargs['response_format'] == fmt
    invoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_changed_owned_source_refuses_before_reader_preparation(monkeypatch):
    source = packet('# 1. Work\nRule.\n')
    part = source_reader_parts(source)[0]
    view = PracticalModelView(source)
    fake, journal, _direct, _plan, _validator = setup()
    journal.verify_source = AsyncMock(return_value=False)
    client = ManagedLunaClient(base_url='http://127.0.0.1:18999/v1', api_key='synthetic',
        tenant_id=UUID(journal.tenant_id), user_id=journal.user_id, job_id=journal.job_id,
        credential_revision='r1')
    prepare = AsyncMock()
    monkeypatch.setattr(client, 'prepare', prepare)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(journal=journal, direct_client=client, stage='review',
            group_id='practical:source-read:' + part.fingerprint, source_sha256='b' * 64,
            route_fingerprint=client.cache_fingerprint(), messages=source_read_messages(source, part, view),
            response_format=view.schema(source_read_format(source, part)), direct_max_output_tokens=128,
            invoke=AsyncMock(), response_validator=lambda value: validate_source_read(view.decode(value), source, part))
    prepare.assert_not_awaited()
    assert not fake.plans
