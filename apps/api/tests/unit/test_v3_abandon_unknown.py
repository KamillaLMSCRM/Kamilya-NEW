import socket
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.ai import job_service, router
from app.modules.ai.schemas import AbandonUnknownGenerationRequest
from app.modules.ai.v3.pending_stage_transactions import has_pending


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("network denied")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)


def fixture_job(actor):
    signature = "a" * 64
    return SimpleNamespace(id="job", user_id=actor, status="running", stage="lesson", course_id=None,
        params={"documents": ["source"], "generation_reservation_released": False},
        result={"v3_pending_stages": {"policy": "v3-pending-stages-v1", "entries": {signature:
            {"claim_key": "claim", "result_key": "result", "token": "b" * 32}}}},
        message="", completed_at=None, updated_at=None)


def test_availability_requires_valid_owned_pending_and_no_existing_disposition():
    actor = uuid4()
    job = fixture_job(actor)
    assert job_service.can_abandon_unknown(job)
    for key in ("v3_final_save_intent", "v3_final_save_receipt", "source_first_commit_intent"):
        job.result[key] = None
        assert not job_service.can_abandon_unknown(job)
        del job.result[key]
    job.params["generation_abandonment"] = None
    assert not job_service.can_abandon_unknown(job)
    del job.params["generation_abandonment"]
    job.course_id = uuid4()
    assert not job_service.can_abandon_unknown(job)
    job.course_id = None
    job.status = "failed"
    assert not job_service.can_abandon_unknown(job)
    job.status = "interrupted"
    job.result["v3_pending_stages"] = None
    assert not job_service.can_abandon_unknown(job)
    job = fixture_job(actor)
    job.params = None
    assert not job_service.can_abandon_unknown(job)


@pytest.mark.asyncio
async def test_job_response_only_exposes_availability_to_owner(monkeypatch):
    actor = uuid4()
    job = fixture_job(actor)
    job.created_at = job.updated_at = datetime.now(UTC)
    job.started_at = None
    job.progress = 34
    job.errors = []
    monkeypatch.setattr(router, "_job_progress_detail", lambda _job: {})
    own = await router._job_response(AsyncMock(), job, queue_metadata={}, viewer_id=actor)
    other = await router._job_response(AsyncMock(), job, queue_metadata={}, viewer_id=uuid4())
    assert own.abandon_available is True and other.abandon_available is False
    assert "v3_pending_stages" not in own.model_dump_json()


@pytest.mark.asyncio
async def test_abandon_preserves_pending_reservation_and_is_idempotent(monkeypatch):
    tenant, actor = uuid4(), uuid4()
    job, db = fixture_job(actor), AsyncMock()
    original_result, original_params = deepcopy(job.result), deepcopy(job.params)
    calls = []
    async def execute(statement, parameters):
        assert "pg_advisory_xact_lock" in str(statement)
        assert parameters == {"tenant_id": str(tenant)}
        calls.append("advisory")
    db.execute.side_effect = execute
    async def lock(*_args): calls.append("tenant")
    async def get(*_args, **kwargs):
        assert kwargs["for_update"] is True and calls in (["advisory", "tenant"], ["tenant"])
        calls.append("job")
        return job
    monkeypatch.setattr(job_service, "_lock_tenant_row", lock)
    monkeypatch.setattr(job_service, "get_ai_job", get)
    assert await job_service.abandon_unknown_generation(db, job_id="job", tenant_id=tenant, user_id=actor) == "abandoned"
    assert calls == ["advisory", "tenant", "job"] and job.status == "failed" and job.stage == "abandoned"
    assert router._visible_job_status_message(job)[0] == "abandoned"
    assert job.result == original_result and has_pending(job.result)
    assert {k: v for k, v in job.params.items() if k != "generation_abandonment"} == original_params
    assert job.params["generation_abandonment"]["provider_outcome"] == "unknown"
    calls.clear()
    calls.append("tenant")
    assert await job_service.release_generation_reservation_once(db, job_id="job", tenant_id=tenant) is False
    calls.clear()
    assert await job_service.abandon_unknown_generation(db, job_id="job", tenant_id=tenant, user_id=actor) == "abandoned"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_foreign_actor_and_absent_or_malformed_pending_denied(monkeypatch):
    tenant, actor = uuid4(), uuid4()
    job, db = fixture_job(actor), AsyncMock()
    monkeypatch.setattr(job_service, "_lock_tenant_row", AsyncMock())
    monkeypatch.setattr(job_service, "get_ai_job", AsyncMock(return_value=job))
    assert await job_service.abandon_unknown_generation(db, job_id="job", tenant_id=tenant, user_id=uuid4()) == "not_found"
    for value in ({}, {"v3_pending_stages": None}):
        job.result = value
        assert await job_service.abandon_unknown_generation(db, job_id="job", tenant_id=tenant, user_id=actor) == "conflict"
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_intent_and_changed_marker_fail_closed(monkeypatch):
    tenant, actor = uuid4(), uuid4()
    job, db = fixture_job(actor), AsyncMock()
    monkeypatch.setattr(job_service, "_lock_tenant_row", AsyncMock())
    monkeypatch.setattr(job_service, "get_ai_job", AsyncMock(return_value=job))
    job.params["generation_abandonment"] = None
    assert await job_service.abandon_unknown_generation(db, job_id="job", tenant_id=tenant, user_id=actor) == "conflict"
    del job.params["generation_abandonment"]
    job.result["v3_final_save_intent"] = None
    assert await job_service.abandon_unknown_generation(db, job_id="job", tenant_id=tenant, user_id=actor) == "conflict"
    del job.result["v3_final_save_intent"]
    assert await job_service.abandon_unknown_generation(db, job_id="job", tenant_id=tenant, user_id=actor) == "abandoned"
    next(iter(job.result["v3_pending_stages"]["entries"].values()))["token"] = "c" * 32
    assert await job_service.abandon_unknown_generation(db, job_id="job", tenant_id=tenant, user_id=actor) == "conflict"


@pytest.mark.asyncio
async def test_endpoint_requires_explicit_ack_and_returns_no_claim(monkeypatch):
    actor, tenant = uuid4(), uuid4()
    user = SimpleNamespace(id=actor, tenant_id=tenant)
    callback = AsyncMock(return_value="abandoned")
    monkeypatch.setattr(router, "abandon_unknown_generation", callback)
    with pytest.raises(HTTPException) as error:
        await router.abandon_unknown_job("job", AbandonUnknownGenerationRequest(acknowledge_outcome_and_cost_unknown=False), AsyncMock(), user)
    assert error.value.status_code == 409
    callback.assert_not_awaited()
    output = await router.abandon_unknown_job("job", AbandonUnknownGenerationRequest(acknowledge_outcome_and_cost_unknown=True), AsyncMock(), user)
    assert output == {"status": "abandoned", "provider_outcome": "unknown", "cost": "unknown"}
    with pytest.raises(ValidationError):
        AbandonUnknownGenerationRequest(acknowledge_outcome_and_cost_unknown=1)


@pytest.mark.asyncio
async def test_late_finalization_and_cancel_remain_fenced(monkeypatch):
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    from app.modules.ai.v3.pending_stage_transactions import claim_with_pending, finalize_pending
    from app.modules.ai.v3.stage_checkpoint import _digest
    from tests.unit.test_pending_stage_transactions import TxJournal, args

    journal = TxJournal()
    request = args(journal)
    await claim_with_pending(**request)
    original = deepcopy(journal.job.result)
    journal.job.status = "failed"
    with pytest.raises(ExtractionOutcomeUnknownError):
        await finalize_pending(**request, value={"identity": _digest(request["plan"]), "response": {"ok": True}})
    assert journal.job.result == original

    tenant = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant)
    monkeypatch.setattr(router, "_lock_tenant_row", AsyncMock())
    monkeypatch.setattr(router, "get_ai_job", AsyncMock(return_value=journal.job))
    db = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await router.cancel_generation("job", db, user)
    assert error.value.status_code == 409
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_redelivery_requires_pending_status_and_no_pending_marker():
    db = AsyncMock()
    db.execute.side_effect = [None, SimpleNamespace(rowcount=0)]
    assert not await job_service.claim_generation_execution(db, "job", str(uuid4()), "job")
    statement = db.execute.await_args_list[1].args[0]
    from sqlalchemy.dialects import postgresql
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "pending" in compiled.params.values()
    assert "v3_pending_stages" in compiled.params.values()


def test_viewer_availability_requires_authenticated_uuid_identity():
    actor=uuid4()
    job=fixture_job(actor)
    assert router._viewer_can_abandon_unknown(job,actor)
    assert not router._viewer_can_abandon_unknown(job,None)
    assert not router._viewer_can_abandon_unknown(job,str(actor))
    assert not router._viewer_can_abandon_unknown(job,uuid4())
