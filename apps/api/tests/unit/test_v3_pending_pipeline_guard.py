"""Synthetic pending-stage guard on the common pipeline status writer."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai import job_service, pipeline
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "interrupted", "cancelled", "completed"])
async def test_terminal_update_holds_present_null_pending_stage(monkeypatch, status):
    job = SimpleNamespace(params={"source_analysis": {"generation_engine": "evidence_v3"}},
                          result={"v3_pending_stages": None})
    session = SimpleNamespace(execute=AsyncMock())

    class Manager:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(pipeline, "async_session_factory", Manager)
    monkeypatch.setattr(pipeline, "lock_owned_delivery", AsyncMock())
    monkeypatch.setattr(job_service, "get_ai_job", AsyncMock(return_value=job))
    update = AsyncMock()
    monkeypatch.setattr(job_service, "update_ai_job", update)
    with pytest.raises(ExtractionOutcomeUnknownError):
        await pipeline._update_job_db("job", tenant_id=uuid4(), status=status)
    update.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", ["failure", "cancel"])
async def test_pending_stage_during_terminal_update_returns_hold_without_refund(monkeypatch, cause):
    import asyncio

    tenant, user, doc = uuid4(), uuid4(), uuid4()
    monkeypatch.setattr(pipeline, "_check_generation_source_job", AsyncMock())
    update = AsyncMock(side_effect=[False, ExtractionOutcomeUnknownError("pending")])
    monkeypatch.setattr(pipeline, "_update_job_db", update)
    monkeypatch.setattr(pipeline, "load_direct_source_corpus", AsyncMock(return_value=SimpleNamespace()))
    failure = RuntimeError("synthetic") if cause == "failure" else asyncio.CancelledError()
    monkeypatch.setattr(pipeline, "_run_v3_generation", AsyncMock(side_effect=failure))
    refund = AsyncMock(side_effect=AssertionError("refund forbidden"))
    monkeypatch.setattr(pipeline, "_release_generation_reservation", refund)
    hold = AsyncMock(return_value=True)
    monkeypatch.setattr(pipeline, "_persist_pending_stage_hold", hold)
    state = await pipeline.run_generation_pipeline("job", [str(doc)], tenant_id=tenant, user_id=user,
        source_analysis={"generation_engine": "evidence_v3", "analysis_mode": "direct_source"})
    assert state.status == "interrupted"
    assert state.errors == ["generation_stage_outcome_unknown"]
    refund.assert_not_awaited()
    hold.assert_awaited_once_with("job", tenant, user, expected_qa_marker=None)

@pytest.mark.asyncio
@pytest.mark.parametrize("marker,expected", [(None, True), ({}, True), ("absent", False)])
async def test_owned_pending_hold_preserves_marker_and_healthy_running(monkeypatch, marker, expected):
    from app.modules.ai.v3 import pending_stage_transactions

    tenant, user = uuid4(), uuid4()
    original = {} if marker == "absent" else {"v3_pending_stages": marker}
    job = SimpleNamespace(result=dict(original), status="running", stage="generation", message="active",
                          errors=None, completed_at=None, updated_at=None)
    session = SimpleNamespace(commit=AsyncMock())
    class Manager:
        async def __aenter__(self): return session
        async def __aexit__(self, *args): return None
    monkeypatch.setattr(pipeline, "async_session_factory", Manager)
    lock = AsyncMock(return_value=job)
    monkeypatch.setattr(pending_stage_transactions, "_locked_job", lock)
    assert await pipeline._persist_pending_stage_hold("job", tenant, user) is expected
    lock.assert_awaited_once()
    assert job.result == original
    if expected:
        assert job.status == "interrupted" and job.errors == ["generation_stage_outcome_unknown"]
        session.commit.assert_awaited_once()
    else:
        assert job.status == "running" and job.message == "active"
        session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["ownership", "database"])
async def test_pending_hold_failure_never_mutates_or_refunds(monkeypatch, failure):
    from app.modules.ai.v3 import pending_stage_transactions

    tenant, user = uuid4(), uuid4()
    job = SimpleNamespace(result={"v3_pending_stages": None}, status="running", stage="generation", message="active",
                          errors=None, completed_at=None, updated_at=None)
    class Manager:
        async def __aenter__(self):
            if failure == "database":
                raise OSError("synthetic database unavailable")
            return SimpleNamespace()
        async def __aexit__(self, *args): return None
    monkeypatch.setattr(pipeline, "async_session_factory", Manager)
    monkeypatch.setattr(pending_stage_transactions, "_locked_job", AsyncMock(side_effect=ValueError("ownership lost")))
    refund = AsyncMock(side_effect=AssertionError("refund forbidden"))
    monkeypatch.setattr(pipeline, "_release_generation_reservation", refund)
    assert not await pipeline._persist_pending_stage_hold("job", tenant, user)
    assert job.status == "running" and job.result == {"v3_pending_stages": None}
    refund.assert_not_awaited()

@pytest.mark.asyncio
async def test_timeout_terminal_write_with_pending_requests_owned_hold(monkeypatch):
    tenant, user, doc = uuid4(), uuid4(), uuid4()
    monkeypatch.setattr(pipeline, "_check_generation_source_job", AsyncMock())
    monkeypatch.setattr(pipeline, "_update_job_db", AsyncMock(side_effect=[False, ExtractionOutcomeUnknownError("pending")]))
    monkeypatch.setattr(pipeline, "load_direct_source_corpus", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(pipeline, "_run_v3_generation", AsyncMock(side_effect=pipeline.SoftTimeLimitExceeded()))
    hold = AsyncMock(return_value=True)
    refund = AsyncMock(side_effect=AssertionError("refund forbidden"))
    monkeypatch.setattr(pipeline, "_persist_pending_stage_hold", hold)
    monkeypatch.setattr(pipeline, "_release_generation_reservation", refund)
    state = await pipeline.run_generation_pipeline("job", [str(doc)], tenant_id=tenant, user_id=user,
        source_analysis={"generation_engine": "evidence_v3", "analysis_mode": "direct_source"})
    assert state.status == "interrupted" and state.errors == ["generation_stage_outcome_unknown"]
    hold.assert_awaited_once_with("job", tenant, user, expected_qa_marker=None)
    refund.assert_not_awaited()

@pytest.mark.asyncio
async def test_provider_exhaustion_terminal_write_with_pending_requests_owned_hold(monkeypatch):
    tenant, user, doc = uuid4(), uuid4(), uuid4()
    monkeypatch.setattr(pipeline, "_check_generation_source_job", AsyncMock())
    monkeypatch.setattr(pipeline, "_update_job_db", AsyncMock(side_effect=[False, ExtractionOutcomeUnknownError("pending")]))
    monkeypatch.setattr(pipeline, "load_direct_source_corpus", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(pipeline, "_run_v3_generation", AsyncMock(
        side_effect=pipeline.AllProvidersFailedError("synthetic provider exhaustion")))
    hold = AsyncMock(return_value=True)
    refund = AsyncMock(side_effect=AssertionError("refund forbidden"))
    monkeypatch.setattr(pipeline, "_persist_pending_stage_hold", hold)
    monkeypatch.setattr(pipeline, "_release_generation_reservation", refund)
    state = await pipeline.run_generation_pipeline("job", [str(doc)], tenant_id=tenant, user_id=user,
        source_analysis={"generation_engine": "evidence_v3", "analysis_mode": "direct_source"})
    assert state.status == "interrupted" and state.errors == ["generation_stage_outcome_unknown"]
    hold.assert_awaited_once_with("job", tenant, user, expected_qa_marker=None)
    refund.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_claim", [False, True])
async def test_unmarked_exact_qa_unknown_installs_fence_without_retry_or_refund(monkeypatch, legacy_claim):
    from app.modules.ai.qa_luna_dev_route import QA_TENANT
    from app.modules.ai.v3 import pending_stage_transactions
    from app.modules.ai.v3.qa_luna_pending_policy import KEY, POLICY

    user = uuid4()
    job = SimpleNamespace(result={"prior_claim_may_exist": legacy_claim}, status="running", stage="generation",
        message="active", errors=None, completed_at=None, updated_at=None, course_id=None,
        params={"source_analysis": {KEY: POLICY, "generation_engine": "evidence_v3"}})
    session = SimpleNamespace(commit=AsyncMock())
    class Manager:
        async def __aenter__(self): return session
        async def __aexit__(self, *args): return None
    monkeypatch.setattr(pipeline, "async_session_factory", Manager)
    monkeypatch.setattr(pending_stage_transactions, "_locked_job", AsyncMock(return_value=job))
    assert await pipeline._persist_pending_stage_hold("job", QA_TENANT, user, expected_qa_marker=POLICY)
    assert job.result == {"prior_claim_may_exist": legacy_claim, "v3_pending_stages": None}
    assert job.status == "interrupted" and not job_service.is_resumable_generation_job(job)
    monkeypatch.setattr(job_service, "get_ai_job", AsyncMock(return_value=job))
    assert not await job_service.release_generation_reservation_once(SimpleNamespace(), job_id="job", tenant_id=QA_TENANT)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["tenant", "dispatch", "stored", "engine", "course"])
async def test_unmarked_non_qa_or_mismatched_route_is_not_modified(monkeypatch, mismatch):
    from app.modules.ai.qa_luna_dev_route import QA_TENANT
    from app.modules.ai.v3 import pending_stage_transactions
    from app.modules.ai.v3.qa_luna_pending_policy import KEY, POLICY

    user = uuid4()
    job = SimpleNamespace(result={}, status="running", course_id=None,
        params={"source_analysis": {KEY: POLICY, "generation_engine": "evidence_v3"}})
    tenant, dispatched = QA_TENANT, POLICY
    if mismatch == "tenant":
        tenant = uuid4()
    if mismatch == "dispatch":
        dispatched = "invalid"
    if mismatch == "stored":
        job.params["source_analysis"][KEY] = "invalid"
    if mismatch == "engine":
        job.params["source_analysis"]["generation_engine"] = "evidence_v2"
    if mismatch == "course":
        job.course_id = uuid4()
    session = SimpleNamespace(commit=AsyncMock())
    class Manager:
        async def __aenter__(self): return session
        async def __aexit__(self, *args): return None
    monkeypatch.setattr(pipeline, "async_session_factory", Manager)
    monkeypatch.setattr(pending_stage_transactions, "_locked_job", AsyncMock(return_value=job))
    assert not await pipeline._persist_pending_stage_hold("job", tenant, user, expected_qa_marker=dispatched)
    assert job.status == "running" and job.result == {}
    session.commit.assert_not_awaited()
