import asyncio
import time
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.modules.admin.runtime_configuration.catalog import RuntimeSnapshot
from app.modules.ai.llm_client import LLMProviderConfig, ResilientLLMClient
from app.modules.ai.v3.cooperative_budget import CooperativeBudget, PreclaimYieldError, active_budget
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.pending_stage_transactions import claim_with_pending, finalize_pending, has_pending
from app.modules.ai.v3.provider_profile import V3ProfiledClient
from app.modules.ai.v3.stage_checkpoint import _digest, stage_once
from tests.unit.test_pending_stage_journal import journal, stage_args
from tests.unit.test_pending_stage_transactions import TxJournal, args


def profile(seconds=0.03, *, enabled=True):
    client = ResilientLLMClient([LLMProviderConfig('synthetic', 'https://example.invalid', 'key', 'model')])
    policy = RuntimeSnapshot(1, {'provider.deepseek.timeout_seconds': seconds})
    return V3ProfiledClient(client, policy, job_id='synthetic', cooperative_deadline=enabled)


@pytest.mark.parametrize('value', [True, 0, -1, float('nan'), float('inf'), '1'])
def test_invalid_bound_fails_closed(value):
    with pytest.raises((ValueError, TypeError)):
        profile(value)


def test_profile_identity_and_legacy_default():
    one = profile(120, enabled=False)
    legacy = V3ProfiledClient(one._client, one._policy, job_id='synthetic')
    new = V3ProfiledClient(one._client, one._policy, job_id='synthetic', cooperative_deadline=True)
    assert legacy.cache_fingerprint() == one.cache_fingerprint() != new.cache_fingerprint()
    assert legacy.generation_deadline_seconds is None and new.generation_deadline_seconds == 120
    with pytest.raises(ValueError):
        profile(enabled=1)


@pytest.mark.asyncio
async def test_whole_native_invocation_times_out_once_and_cancellation_propagates(monkeypatch):
    calls = []
    async def slow(_client, *_args, **kwargs):
        calls.append(kwargs)
        await asyncio.sleep(10)
    monkeypatch.setattr(ResilientLLMClient, 'ainvoke', slow)
    with pytest.raises(TimeoutError):
        await profile().ainvoke('request', response_format={'type': 'json_object'})
    assert len(calls) == 1 and calls[0]['request_profile'] == 'course_generation'
    task = asyncio.create_task(profile(5).ainvoke('request'))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_legacy_wire_unchanged(monkeypatch):
    seen = []
    async def invoke(_client, messages, **kwargs):
        seen.append((messages, kwargs))
        return SimpleNamespace(content='{"ok":true}', finish_reason='stop', content_is_reasoning=False)
    monkeypatch.setattr(ResilientLLMClient, 'ainvoke', invoke)
    await profile(enabled=False).ainvoke('request', response_format={'type': 'json_object'})
    await profile(enabled=True).ainvoke('request', response_format={'type': 'json_object'})
    assert seen[0] == seen[1]


@pytest.mark.asyncio
async def test_expired_budget_yields_without_any_claim_write_and_replays_completed():
    journal = TxJournal()
    journal.native_generation_seconds = 120
    options = args(journal)
    before = deepcopy(journal.job.result)
    token = active_budget.set(CooperativeBudget(deadline=time.monotonic() - 1))
    try:
        with pytest.raises(PreclaimYieldError):
            await claim_with_pending(**options)
        assert journal.job.result == before and not journal.plans and not journal.values
    finally:
        active_budget.reset(token)
    await claim_with_pending(**options)
    value = {'identity': _digest(options['plan']), 'response': {'ok': True}}
    await finalize_pending(**options, value=value)
    token = active_budget.set(CooperativeBudget(deadline=time.monotonic() - 1))
    try:
        assert await claim_with_pending(**options) == {'ok': True}
    finally:
        active_budget.reset(token)


@pytest.mark.asyncio
async def test_existing_pending_is_held_even_with_expired_budget():
    journal = TxJournal()
    journal.native_generation_seconds = 120
    await claim_with_pending(**args(journal))
    token = active_budget.set(CooperativeBudget(deadline=time.monotonic() - 1))
    try:
        with pytest.raises(ExtractionOutcomeUnknownError):
            await claim_with_pending(**args(journal))
    finally:
        active_budget.reset(token)


@pytest.mark.asyncio
async def test_postclaim_deadline_is_unknown_and_redelivery_never_resends(monkeypatch):
    active, fake = journal()
    client = profile()
    active.native_generation_seconds = client.generation_deadline_seconds
    calls = []
    async def slow(_client, *_args, **_kwargs):
        calls.append(1)
        await asyncio.sleep(10)
    monkeypatch.setattr(ResilientLLMClient, 'ainvoke', slow)
    async def invoke():
        return await client.ainvoke('synthetic')
    with pytest.raises(ExtractionOutcomeUnknownError) as caught:
        await stage_once(**stage_args(active, invoke))
    assert isinstance(caught.value.__cause__, TimeoutError) and has_pending(fake.job.result)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**stage_args(active, invoke))
    assert calls == [1]
