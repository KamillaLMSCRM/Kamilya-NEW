"""Offline same-transaction claim guard for selected owned evidence."""
import socket
from unittest.mock import AsyncMock

import httpx
import pytest

from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.pending_stage_transactions import has_pending
from app.modules.ai.v3.stage_checkpoint import stage_once
from tests.unit.test_direct_luna_owned_stage import setup


def fresh_repair_scope(fake, journal):
    from app.modules.ai.qa_luna_dev_route import QA_TENANT
    from app.modules.ai.v3.qa_luna_pending_policy import DIRECT_POLICY, KEY
    journal.tenant_id = fake.tenant_id = str(QA_TENANT)
    fake.job.params["source_analysis"][KEY] = DIRECT_POLICY


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(httpx, "AsyncClient", deny)
    monkeypatch.setattr(httpx, "Client", deny)


def params(journal, client, guard):
    return dict(journal=journal, stage="repair", group_id="g", source_sha256="a" * 64,
                route_fingerprint="b" * 64, messages=[{"role": "user", "content": "synthetic"}],
                response_format={"type": "json_object"}, invoke=AsyncMock(), direct_client=client,
                direct_max_output_tokens=128, _owned_claim_guard=guard)


@pytest.mark.asyncio
async def test_drift_at_claim_fails_before_provider_and_no_claim(monkeypatch):
    fake, journal, client, _, _ = setup()
    calls = []
    async def guard(session, job, plan):
        calls.append((session, job, plan))
        return len(calls) < 3
    async def prepare(*_args, ownership_checkpoint, **_kwargs):
        assert await ownership_checkpoint()
        return object()
    monkeypatch.setattr(client, "prepare", AsyncMock(side_effect=prepare))
    invoke = AsyncMock()
    monkeypatch.setattr(client, "invoke", invoke)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**params(journal, client, guard))
    assert len(calls) == 3 and not fake.plans and not has_pending(fake.job.result)
    invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_post_claim_denial_keeps_pending_and_no_retry(monkeypatch):
    fake, journal, client, _, _ = setup()
    count = 0
    async def guard(_session, _job, _plan):
        nonlocal count
        count += 1
        return count < 4
    async def prepare(*_args, ownership_checkpoint, **_kwargs):
        assert await ownership_checkpoint()
        return object()
    prepare_mock = AsyncMock(side_effect=prepare)
    invoke = AsyncMock()
    monkeypatch.setattr(client, "prepare", prepare_mock)
    monkeypatch.setattr(client, "invoke", invoke)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**params(journal, client, guard))
    assert has_pending(fake.job.result)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**params(journal, client, guard))
    prepare_mock.assert_awaited_once()
    invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_cold_replay_rechecks_guard_without_count_or_provider(monkeypatch):
    fake, journal, client, _, _ = setup()
    fresh_repair_scope(fake, journal)
    allowed = True
    async def guard(_session, _job, _plan):
        return allowed
    async def prepare(*_args, ownership_checkpoint, **_kwargs):
        assert await ownership_checkpoint()
        return object()
    async def invoke(_capability, *, ownership_checkpoint, **_kwargs):
        assert await ownership_checkpoint()
        return _direct_response({"ok": True})
    prepare_mock, invoke_mock = AsyncMock(side_effect=prepare), AsyncMock(side_effect=invoke)
    monkeypatch.setattr(client, "prepare", prepare_mock)
    monkeypatch.setattr(client, "invoke", invoke_mock)
    assert await stage_once(**params(journal, client, guard)) == {"ok": True}
    assert await stage_once(**params(journal, client, guard)) == {"ok": True}
    allowed = False
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**params(journal, client, guard))
    prepare_mock.assert_awaited_once()
    invoke_mock.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("guard", [None, lambda *_: True])
async def test_reserved_repair_rejects_missing_or_weaker_guard_before_count(monkeypatch, guard):
    _, journal, client, _, _ = setup()
    prepare = AsyncMock()
    monkeypatch.setattr(client, "prepare", prepare)
    args = params(journal, client, guard)
    args["group_id"] = "owned-diversity-repair:case"
    with pytest.raises(ExtractionOutcomeUnknownError, match="v3_owned_repair_guard_required"):
        await stage_once(**args)
    prepare.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("private"), __import__("asyncio").CancelledError()])
async def test_reserved_guard_error_and_cancellation_deny_without_count(monkeypatch, failure):
    from app.modules.ai.v3.diversity_owned_selection_guard import OwnedSelectionGuard
    fake, journal, client, _, _ = setup()
    fresh_repair_scope(fake, journal)
    async def check(*_args):
        raise failure
    prepare = AsyncMock()
    monkeypatch.setattr(client, "prepare", prepare)
    args = params(journal, client, OwnedSelectionGuard("a" * 64, check, "case"))
    args["group_id"] = "owned-diversity-repair:case"
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**args)
    prepare.assert_not_awaited()


@pytest.mark.asyncio
async def test_reserved_guard_drift_at_finalize_keeps_pending_no_retry(monkeypatch):
    from app.modules.ai.v3.diversity_owned_selection_guard import OwnedSelectionGuard
    fake, journal, client, _, _ = setup()
    fresh_repair_scope(fake, journal)
    count = 0
    async def check(*_args):
        nonlocal count
        count += 1
        return count < 6
    async def prepare(*_args, ownership_checkpoint, **_kwargs):
        assert await ownership_checkpoint()
        return object()
    async def invoke(_capability, *, ownership_checkpoint, **_kwargs):
        assert await ownership_checkpoint()
        return _direct_response({"ok": True})
    prepare_mock, invoke_mock = AsyncMock(side_effect=prepare), AsyncMock(side_effect=invoke)
    monkeypatch.setattr(client, "prepare", prepare_mock)
    monkeypatch.setattr(client, "invoke", invoke_mock)
    args = params(journal, client, OwnedSelectionGuard("a" * 64, check, "case"))
    args["group_id"] = "owned-diversity-repair:case"
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**args)
    assert has_pending(fake.job.result)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**args)
    prepare_mock.assert_awaited_once()
    invoke_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_repair_slot_cold_replay_and_changed_attempt_denied_before_count(monkeypatch):
    from app.modules.ai.v3.diversity_owned_selection_guard import OwnedSelectionGuard
    from app.modules.ai.v3.pending_stage_transactions import REPAIR_SLOTS_KEY
    fake, journal, client, _, _ = setup()
    fresh_repair_scope(fake, journal)
    async def check(*_args): return True
    async def prepare(*_args, **_kwargs): return object()
    async def invoke(*_args, **_kwargs): return _direct_response({"ok": True})
    monkeypatch.setattr(client, "prepare", AsyncMock(side_effect=prepare))
    monkeypatch.setattr(client, "invoke", AsyncMock(side_effect=invoke))
    args = params(journal, client, OwnedSelectionGuard("a" * 64, check, "case"))
    args["group_id"] = "owned-diversity-repair:case"
    assert await stage_once(**args) == {"ok": True}
    assert REPAIR_SLOTS_KEY in fake.job.result and not has_pending(fake.job.result)
    from tests.unit.test_v3_diversity_direct_journal import cold_journal
    assert await stage_once(**(args | {"journal": cold_journal(journal, fake)})) == {"ok": True}
    for changed in (args | {"messages": [{"role": "user", "content": "changed"}]},
                    args | {"_owned_claim_guard": OwnedSelectionGuard("b" * 64, check, "case")}):
        with pytest.raises(ExtractionOutcomeUnknownError):
            await stage_once(**changed)
    del fake.job.result[REPAIR_SLOTS_KEY]
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**args)
    client.prepare.assert_awaited_once()
    client.invoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_repair_claims_and_lost_ack_keep_one_slot(monkeypatch):
    import asyncio

    from app.modules.ai.v3.diversity_owned_selection_guard import OwnedSelectionGuard
    from app.modules.ai.v3.pending_stage_transactions import REPAIR_SLOTS_KEY
    fake, journal, client, _, _ = setup()
    fresh_repair_scope(fake, journal)
    async def check(*_args): return True
    async def prepare(*_args, **_kwargs): return object()
    async def invoke(*_args, **_kwargs): raise TimeoutError("unknown")
    monkeypatch.setattr(client, "prepare", AsyncMock(side_effect=prepare))
    monkeypatch.setattr(client, "invoke", AsyncMock(side_effect=invoke))
    args = params(journal, client, OwnedSelectionGuard("a" * 64, check, "case"))
    args["group_id"] = "owned-diversity-repair:case"
    outcomes = await asyncio.gather(stage_once(**args), stage_once(**args), return_exceptions=True)
    assert all(isinstance(outcome, ExtractionOutcomeUnknownError) for outcome in outcomes)
    assert len(fake.job.result[REPAIR_SLOTS_KEY]["entries"]) == 1 and has_pending(fake.job.result)
    client.invoke.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("lost_ack", [False, True])
async def test_repair_slot_claim_rollback_or_commit_ack_unknown(monkeypatch, lost_ack):
    from app.modules.ai.v3.diversity_owned_selection_guard import OwnedSelectionGuard
    from app.modules.ai.v3.pending_stage_transactions import REPAIR_SLOTS_KEY
    fake, journal, client, _, _ = setup()
    fresh_repair_scope(fake, journal)
    async def check(*_args): return True
    monkeypatch.setattr(client, "prepare", AsyncMock(return_value=object()))
    monkeypatch.setattr(client, "invoke", AsyncMock())
    if lost_ack:
        fake.fail_ack = True
    else:
        monkeypatch.setattr(fake, "create_plan", AsyncMock(side_effect=RuntimeError("precommit")))
    args = params(journal, client, OwnedSelectionGuard("a" * 64, check, "case"))
    args["group_id"] = "owned-diversity-repair:case"
    with pytest.raises(ExtractionOutcomeUnknownError if lost_ack else RuntimeError):
        await stage_once(**args)
    assert (REPAIR_SLOTS_KEY in fake.job.result) is lost_ack
    assert has_pending(fake.job.result) is lost_ack
    client.invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_v2_cannot_claim_fresh_v3_repair_slot(monkeypatch):
    from app.modules.ai.v3.diversity_owned_selection_guard import OwnedSelectionGuard
    from app.modules.ai.v3.qa_luna_pending_policy import DIRECT_POLICY_V2, KEY
    fake, journal, client, _, _ = setup()
    fresh_repair_scope(fake, journal)
    fake.job.params["source_analysis"][KEY] = DIRECT_POLICY_V2
    async def check(*_args): return True
    monkeypatch.setattr(client, "prepare", AsyncMock())
    args = params(journal, client, OwnedSelectionGuard("a" * 64, check, "case"))
    args["group_id"] = "owned-diversity-repair:case"
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**args)
    client.prepare.assert_not_awaited()


@pytest.mark.asyncio
async def test_repair_finalize_lost_ack_replays_owned_result_without_new_attempt(monkeypatch):
    from app.modules.ai.v3.diversity_owned_selection_guard import OwnedSelectionGuard
    from app.modules.ai.v3.pending_stage_transactions import REPAIR_SLOTS_KEY
    fake, journal, client, _, _ = setup()
    fresh_repair_scope(fake, journal)
    async def check(*_args): return True
    async def invoke(*_args, **_kwargs):
        fake.fail_ack = True
        return _direct_response({"ok": True})
    monkeypatch.setattr(client, "prepare", AsyncMock(return_value=object()))
    monkeypatch.setattr(client, "invoke", AsyncMock(side_effect=invoke))
    args = params(journal, client, OwnedSelectionGuard("a" * 64, check, "case"))
    args["group_id"] = "owned-diversity-repair:case"
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**args)
    assert REPAIR_SLOTS_KEY in fake.job.result and not has_pending(fake.job.result)
    fake.fail_ack = False
    assert await stage_once(**args) == {"ok": True}
    client.prepare.assert_awaited_once()
    client.invoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_existing_repair_slot_without_checkpoints_holds_before_count(monkeypatch):
    from app.modules.ai.v3.diversity_owned_selection_guard import OwnedSelectionGuard
    fake, journal, client, _, _ = setup()
    fresh_repair_scope(fake, journal)
    async def check(*_args): return True
    monkeypatch.setattr(client, "prepare", AsyncMock(return_value=object()))
    monkeypatch.setattr(client, "invoke", AsyncMock(return_value=_direct_response({"ok": True})))
    args = params(journal, client, OwnedSelectionGuard("a" * 64, check, "case"))
    args["group_id"] = "owned-diversity-repair:case"
    assert await stage_once(**args) == {"ok": True}
    fake.plans.clear()
    fake.values.clear()
    client.prepare.reset_mock()
    client.invoke.reset_mock()
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**args)
    client.prepare.assert_not_awaited()
    client.invoke.assert_not_awaited()


def _direct_response(content):
    from app.modules.ai.direct_luna_api import LunaUsage
    from app.modules.ai.direct_luna_responses_client import ResponsesResult
    return ResponsesResult(content=content, model="gpt-6-luna", usage=LunaUsage(None, None, None, None))
