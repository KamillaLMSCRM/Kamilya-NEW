"""Offline wall-clock slicing preserves completed provider work and ownership."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.modules.ai.v3.cooperative_budget import CooperativeBudget, PreclaimYieldError, active_budget
from app.modules.ai.v3.direct_luna_owned_stage import run_direct_owned_stage
from app.modules.ai.v3.pending_stage_transactions import has_pending
from tests.unit.test_direct_luna_owned_stage import options, setup


@pytest.mark.asyncio
async def test_budget_yields_before_count_without_touching_journal(monkeypatch):
    fake, journal, client, plan, validate = setup()
    prepare, invoke = AsyncMock(), AsyncMock()
    monkeypatch.setattr(client, 'prepare', prepare)
    monkeypatch.setattr(client, 'invoke', invoke)
    monkeypatch.setattr('app.modules.ai.v3.cooperative_budget.time.monotonic', lambda: 421.0)
    token = active_budget.set(CooperativeBudget.start(now=0))
    try:
        with pytest.raises(PreclaimYieldError):
            await run_direct_owned_stage(**options(journal, client, plan, validate))
    finally:
        active_budget.reset(token)
    prepare.assert_not_awaited()
    invoke.assert_not_awaited()
    assert not fake.plans and not has_pending(fake.job.result)


@pytest.mark.asyncio
async def test_budget_rechecks_after_count_and_discards_capability(monkeypatch):
    fake, journal, client, plan, validate = setup()
    clock = [420.0]
    cap = object()
    async def prepare(*_args, **_kwargs):
        clock[0] = 481.0
        return cap
    monkeypatch.setattr(client, 'prepare', AsyncMock(side_effect=prepare))
    invoke, discard = AsyncMock(), Mock(wraps=client.discard)
    monkeypatch.setattr(client, 'invoke', invoke)
    monkeypatch.setattr(client, 'discard', discard)
    monkeypatch.setattr('app.modules.ai.v3.cooperative_budget.time.monotonic', lambda: clock[0])
    token = active_budget.set(CooperativeBudget.start(now=0))
    try:
        with pytest.raises(PreclaimYieldError):
            await run_direct_owned_stage(**options(journal, client, plan, validate))
    finally:
        active_budget.reset(token)
    discard.assert_called_once_with(cap)
    invoke.assert_not_awaited()
    assert not fake.plans and not has_pending(fake.job.result)


@pytest.mark.asyncio
async def test_completed_response_replays_after_budget_exhausted(monkeypatch):
    fake, journal, client, plan, validate = setup()
    prepare = AsyncMock(return_value=object())
    invoke = AsyncMock(return_value=SimpleNamespace(content={'ok': True}, model='gpt-6-luna',
        usage=SimpleNamespace(input_tokens=12, output_tokens=8, cached_input_tokens=0, reasoning_tokens=4)))
    monkeypatch.setattr(client, 'prepare', prepare)
    monkeypatch.setattr(client, 'invoke', invoke)
    assert await run_direct_owned_stage(**options(journal, client, plan, validate)) == {'ok': True}
    token = active_budget.set(CooperativeBudget(deadline=0))
    try:
        assert await run_direct_owned_stage(**options(journal, client, plan, validate)) == {'ok': True}
    finally:
        active_budget.reset(token)
    prepare.assert_awaited_once()
    invoke.assert_awaited_once()
    assert not has_pending(fake.job.result)


@pytest.mark.asyncio
@pytest.mark.parametrize('owned', [True, False])
async def test_preclaim_yield_uses_only_owned_interruption_and_never_refunds(monkeypatch, owned):
    from app.modules.ai import delivery_ownership, job_service, pipeline

    tenant, user, doc = uuid4(), uuid4(), uuid4()
    monkeypatch.setattr(pipeline, '_check_generation_source_job', AsyncMock())
    monkeypatch.setattr(pipeline, '_update_job_db', AsyncMock(return_value=False))
    monkeypatch.setattr(pipeline, 'load_direct_source_corpus', AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(pipeline, '_run_v3_generation', AsyncMock(side_effect=PreclaimYieldError('before_claim')))
    refund = AsyncMock(side_effect=AssertionError('refund forbidden'))
    hold = AsyncMock(side_effect=AssertionError('unknown fence forbidden'))
    monkeypatch.setattr(pipeline, '_release_generation_reservation', refund)
    monkeypatch.setattr(pipeline, '_persist_pending_stage_hold', hold)
    session = object()
    @asynccontextmanager
    async def sessions():
        yield session
    monkeypatch.setattr(pipeline, 'async_session_factory', sessions)
    interrupt = AsyncMock(return_value=owned)
    monkeypatch.setattr(job_service, 'interrupt_claimed_generation_execution', interrupt)
    token = delivery_ownership.delivery_id.set('delivery-A')
    try:
        call = pipeline.run_generation_pipeline('job', [str(doc)], tenant_id=tenant, user_id=user,
            source_analysis={'generation_engine': 'evidence_v3', 'analysis_mode': 'direct_source'})
        if owned:
            state = await call
            assert state.status == 'interrupted' and state.errors == ['generation_interrupted']
        else:
            with pytest.raises(delivery_ownership.DeliveryOwnershipLostError):
                await call
    finally:
        delivery_ownership.delivery_id.reset(token)
    interrupt.assert_awaited_once_with(session, 'job', str(tenant), 'delivery-A')
    refund.assert_not_awaited()
    hold.assert_not_awaited()


def test_task_budget_starts_before_claim_and_is_reset(monkeypatch):
    import asyncio

    import app.core.db as core_db
    from app.modules.ai import job_service, tasks

    clock = [1000.0]
    monkeypatch.setattr('app.modules.ai.v3.cooperative_budget.time.monotonic', lambda: clock[0])
    @asynccontextmanager
    async def sessions():
        yield object()
    async def claim(*_args):
        clock[0] = 1090.0
        return True
    async def pipeline(**_kwargs):
        budget = active_budget.get()
        assert budget is not None and budget.deadline == 2200.0
        return SimpleNamespace(status='interrupted', message='saved', progress=40)
    monkeypatch.setattr(core_db, 'async_session_factory', sessions)
    monkeypatch.setattr(job_service, 'claim_generation_execution', claim)
    monkeypatch.setattr(tasks, 'run_generation_pipeline', pipeline)
    monkeypatch.setattr(tasks, '_run_async', asyncio.run)
    outer = active_budget.get()
    result = tasks.generate_course_task.apply(task_id='delivery-A', throw=True, kwargs={
        'job_id': 'job', 'documents': ['doc'], 'tenant_id': str(uuid4()),
        'source_analysis': {'generation_engine': 'evidence_v3', 'analysis_mode': 'direct_source'},
    }).get()
    assert result['status'] == 'interrupted'
    assert active_budget.get() is outer
