"""Offline continuation of completed managed source reads across a budget yield."""
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.ai.managed_luna_client import ManagedLunaClient
from app.modules.ai.v3.cooperative_budget import CooperativeBudget, PreclaimYieldError, active_budget
from app.modules.ai.v3.pending_stage_transactions import has_pending
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.practical_source_reader import (
    source_read_format,
    source_read_messages,
    source_reader_parts,
    validate_source_read,
)
from app.modules.ai.v3.stage_checkpoint import stage_once
from tests.unit.test_direct_luna_owned_stage import setup
from tests.unit.test_v3_practical_source_reader import packet, response


@pytest.mark.asyncio
async def test_luna6_read_replays_after_preclaim_yield_and_next_part_runs(monkeypatch):
    source = packet('# 1. Definitions\nTerms.\n\n# 2. Work\nRule.\n')
    first, second = source_reader_parts(source)
    view = PracticalModelView(source)
    fake, journal, _, _, _ = setup()
    client = ManagedLunaClient(
        base_url='http://127.0.0.1:18999/v1', api_key='synthetic',
        tenant_id=UUID(journal.tenant_id), user_id=journal.user_id, job_id=journal.job_id,
        credential_revision='r1', model='gpt-6-luna', reasoning_effort='high', deadline_seconds=300,
    )
    wires = [view.encode(response(source, part)) for part in (first, second)]
    prepare = AsyncMock(return_value=object())
    invoke = AsyncMock(side_effect=[SimpleNamespace(content=wire, model='gpt-6-luna',
        usage=SimpleNamespace(input_tokens=12, output_tokens=6, cached_input_tokens=None, reasoning_tokens=1))
        for wire in wires])
    monkeypatch.setattr(client, 'prepare', prepare)
    monkeypatch.setattr(client, 'invoke', invoke)
    clock = [0.0]
    monkeypatch.setattr('app.modules.ai.v3.cooperative_budget.time.monotonic', lambda: clock[0])

    def options(part, owned_journal):
        def validate(value):
            validate_source_read(view.decode(value), source, part)
        return dict(journal=owned_journal, direct_client=client, stage='review',
            group_id='practical:source-read:' + part.fingerprint, source_sha256='b' * 64,
            route_fingerprint=client.cache_fingerprint(), messages=source_read_messages(source, part, view),
            response_format=view.schema(source_read_format(source, part)), direct_max_output_tokens=128,
            response_validator=validate, invoke=AsyncMock())

    token = active_budget.set(CooperativeBudget(deadline=1000))
    try:
        assert await stage_once(**options(first, journal)) == wires[0]
        clock[0] = 600.0
        with pytest.raises(PreclaimYieldError, match='generation_time_budget_exhausted'):
            await stage_once(**options(second, journal))
        assert not has_pending(fake.job.result)
        prepare.assert_awaited_once()
        invoke.assert_awaited_once()
    finally:
        active_budget.reset(token)

    cold_journal = copy.copy(journal)
    token = active_budget.set(CooperativeBudget(deadline=2000))
    try:
        assert await stage_once(**options(first, cold_journal)) == wires[0]
        prepare.assert_awaited_once()
        invoke.assert_awaited_once()
        assert await stage_once(**options(second, cold_journal)) == wires[1]
        assert prepare.await_count == invoke.await_count == 2
        assert not has_pending(fake.job.result)
    finally:
        active_budget.reset(token)
