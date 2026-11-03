"""Owned source-reading custody binds metadata to the configured managed model."""
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
from app.modules.ai.v3.stage_checkpoint import _digest, stage_once
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_v3_practical_source_reader import packet, response


def make_case(monkeypatch, model, returned_model):
    source = packet('# 1. Definitions\nTerms.\n\n# 2. Work\nRule.\n')
    part = source_reader_parts(source)[1]
    view = PracticalModelView(source)
    wire = view.encode(response(source, part))
    fake, journal, _, _, _ = setup()
    client = ManagedLunaClient(
        base_url='http://127.0.0.1:18999/v1', api_key='synthetic',
        tenant_id=UUID(journal.tenant_id), user_id=journal.user_id, job_id=journal.job_id,
        credential_revision='r1', model=model,
        reasoning_effort='high' if model == 'gpt-6-luna' else 'low',
        deadline_seconds=300 if model == 'gpt-6-luna' else 60,
    )
    prepare = AsyncMock(return_value=object())
    invoke = AsyncMock(return_value=SimpleNamespace(
        content=wire, model=returned_model,
        usage=SimpleNamespace(input_tokens=12, output_tokens=6, cached_input_tokens=None, reasoning_tokens=None),
    ))
    monkeypatch.setattr(client, 'prepare', prepare)
    monkeypatch.setattr(client, 'invoke', invoke)
    def validate(value):
        validate_source_read(view.decode(value), source, part)
    options = dict(journal=journal, direct_client=client, stage='review',
        group_id='practical:source-read:' + part.fingerprint, source_sha256='b' * 64,
        route_fingerprint=client.cache_fingerprint(), messages=source_read_messages(source, part, view),
        response_format=view.schema(source_read_format(source, part)), direct_max_output_tokens=128,
        response_validator=validate, invoke=AsyncMock())
    return fake, journal, wire, options, prepare, invoke


@pytest.mark.asyncio
@pytest.mark.parametrize('model', ['gpt-6-luna', 'gpt-5.6-luna'])
async def test_matching_model_finalizes_and_cold_replays_without_new_invocation(monkeypatch, model):
    fake, journal, wire, options, prepare, invoke = make_case(monkeypatch, model, model)
    assert await stage_once(**options) == wire
    assert not has_pending(fake.job.result)
    saved = next(value for value in fake.values.values()
                 if isinstance(value, dict) and value.get('response') == wire)
    assert saved['direct_metadata']['model'] == model
    assert await stage_once(**{**options, 'journal': copy.copy(journal)}) == wire
    prepare.assert_awaited_once()
    invoke.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(('model', 'wrong'), [
    ('gpt-6-luna', 'gpt-5.6-luna'), ('gpt-5.6-luna', 'gpt-6-luna'),
])
async def test_wrong_model_response_is_held_and_never_reinvoked(monkeypatch, model, wrong):
    fake, journal, wire, options, prepare, invoke = make_case(monkeypatch, model, wrong)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**options)
    assert has_pending(fake.job.result)
    assert not any(isinstance(value, dict) and value.get('response') == wire for value in fake.values.values())
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**{**options, 'journal': copy.copy(journal)})
    prepare.assert_awaited_once()
    invoke.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(('model', 'wrong'), [
    ('gpt-6-luna', 'gpt-5.6-luna'), ('gpt-5.6-luna', 'gpt-6-luna'),
])
async def test_wrong_cached_model_is_rejected_even_with_valid_metadata_digest(monkeypatch, model, wrong):
    fake, journal, wire, options, prepare, invoke = make_case(monkeypatch, model, model)
    assert await stage_once(**options) == wire
    saved = next(value for value in fake.values.values()
                 if isinstance(value, dict) and value.get('response') == wire)
    saved['direct_metadata']['model'] = wrong
    saved['direct_metadata_sha256'] = _digest(saved['direct_metadata'])
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**{**options, 'journal': copy.copy(journal)})
    prepare.assert_awaited_once()
    invoke.assert_awaited_once()
