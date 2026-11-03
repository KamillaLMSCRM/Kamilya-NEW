import asyncio
from uuid import uuid4

import pytest

from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError, extract_once
from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
from app.modules.ai.v3.pending_stage_transactions import has_pending
from app.modules.ai.v3.stage_checkpoint import stage_once
from tests.unit.test_pending_stage_transactions import TxJournal
from tests.unit.test_v3_extraction_checkpoint import identity


def journal():
    fake = TxJournal()
    user = uuid4()
    fake.job.user_id = user
    result = PendingStageJournal(fake.tenant_id, user, fake.job_id, fake.sessions)
    result.repository = fake
    result._lock_delivery = fake._lock_delivery
    result._owned_key = fake._owned_key
    result.read_owned_value_in_session = fake.read_owned_value_in_session
    return result, fake


def stage_args(journal, invoke):
    return dict(journal=journal, stage="lesson", group_id="part", source_sha256="a" * 64,
                route_fingerprint="b" * 64, messages=[{"role": "user", "content": "synthetic"}],
                response_format={"type": "json_object"}, invoke=invoke)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["stage", "extraction"])
async def test_pending_journal_subclass_cannot_fall_back_to_legacy(kind):
    class UnsupportedPendingJournal(PendingStageJournal):
        pass

    base, _ = journal()
    active = UnsupportedPendingJournal(base.tenant_id, base.user_id, base.job_id, base.sessions)
    async def invoke():
        raise AssertionError("provider must not be invoked")
    with pytest.raises(ValueError, match="pending_journal_type_invalid"):
        if kind == "stage":
            await stage_once(**stage_args(active, invoke))
        else:
            await extract_once(active, identity(), invoke)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["stage", "extraction"])
async def test_pending_claim_finalize_and_redelivery_replay(kind):
    active, fake = journal()
    calls = []
    async def invoke():
        calls.append(1)
        assert has_pending(fake.job.result)
        return {"lesson": "synthetic"} if kind == "stage" else {"rules": []}
    async def execute():
        return await stage_once(**stage_args(active, invoke)) if kind == "stage" else await extract_once(active, identity(), invoke)
    expected = {"lesson": "synthetic"} if kind == "stage" else {"rules": []}
    assert await execute() == expected and not has_pending(fake.job.result)
    assert await execute() == expected and calls == [1]


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ValueError("invalid"), asyncio.CancelledError("cancelled"), TimeoutError("unknown")])
async def test_postclaim_errors_keep_marker_and_no_retry(error):
    active, fake = journal()
    calls = []
    async def invoke():
        calls.append(1)
        raise error
    with pytest.raises(ExtractionOutcomeUnknownError) as caught:
        await stage_once(**stage_args(active, invoke))
    assert caught.value.__cause__ is error and has_pending(fake.job.result)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**stage_args(active, invoke))
    assert calls == [1]


@pytest.mark.asyncio
async def test_concurrent_calls_one_provider_and_other_held():
    active, fake = journal()
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def invoke():
        calls.append(1)
        started.set()
        await release.wait()
        return {"lesson": "x"}
    first = asyncio.create_task(stage_once(**stage_args(active, invoke)))
    await started.wait()
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**stage_args(active, invoke))
    release.set()
    assert await first == {"lesson": "x"} and calls == [1] and not has_pending(fake.job.result)


@pytest.mark.asyncio
async def test_legacy_incomplete_claim_holds_in_pending_mode():
    from app.modules.ai.v3.stage_checkpoint import _digest, stage_plan

    active, fake = journal()
    async def invoke():
        raise AssertionError("provider must not be invoked")
    params = stage_args(active, invoke)
    plan = stage_plan(active, stage=params["stage"], group_id=params["group_id"],
        source_sha256=params["source_sha256"], route_fingerprint=params["route_fingerprint"],
        messages=params["messages"], response_format=params["response_format"])
    fake.plans[f"v3-stage-claim:{_digest(plan)}"] = plan
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**params)


@pytest.mark.asyncio
async def test_claim_lost_ack_never_invokes_provider():
    active, fake = journal()
    fake.fail_ack = True
    calls = []
    async def invoke():
        calls.append(1)
        return {"x": 1}
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**stage_args(active, invoke))
    assert not calls and has_pending(fake.job.result)
    fake.fail_ack = False
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**stage_args(active, invoke))
    assert not calls


@pytest.mark.asyncio
async def test_preinvoke_source_error_is_sanitized_and_never_invokes():
    import traceback

    active, fake = journal()
    calls = []
    checks = 0
    async def verify(_session, _job, _plan):
        nonlocal checks
        checks += 1
        if checks == 2:
            raise ValueError("synthetic-private")
        return True
    active.verify_source = verify
    async def invoke():
        calls.append(1)
        return {"lesson": "x"}
    with pytest.raises(ExtractionOutcomeUnknownError, match="source_unverified") as error:
        await stage_once(**stage_args(active, invoke))
    assert error.value.__cause__ is None and error.value.__context__ is None
    assert "synthetic-private" not in "".join(traceback.format_exception(error.value))
    assert not calls and has_pending(fake.job.result)

@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["source", "route"])
async def test_inflight_source_or_route_drift_holds_pending_without_retry(drift):
    active, fake = journal()
    current = {"source": "initial-source", "route": "initial-route"}
    calls = []
    checks = []

    async def verify(_session, job, _plan):
        assert fake.lock.locked()
        assert job is fake.job
        checks.append(dict(current))
        return current == {"source": "initial-source", "route": "initial-route"}

    active.verify_source = verify
    async def invoke():
        calls.append(1)
        current[drift] = "changed"
        return {"lesson": "synthetic"}

    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**stage_args(active, invoke))
    assert len(checks) == 3 and has_pending(fake.job.result)
    assert not any(key.startswith("v3-stage-result:") for key in fake.values)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await stage_once(**stage_args(active, invoke))
    assert calls == [1] and has_pending(fake.job.result)
