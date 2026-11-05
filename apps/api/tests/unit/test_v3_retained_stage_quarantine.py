"""Terminal human stop is independent of a claim about the provider's response."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.ai import job_service, router
from app.modules.ai.schemas import QuarantineGenerationRequest
from tests.unit.test_v3_abandon_unknown import fixture_job, no_network  # noqa: F401


def prepared(actor):
    job = fixture_job(actor)
    job.status = "interrupted"
    job.updated_at = datetime(2026, 11, 4, 16, 0, tzinfo=UTC)
    return job


@pytest.mark.asyncio
async def test_stop_retains_received_evidence_pending_reservation_and_ordered_ownership_locks(monkeypatch):
    actor, tenant = uuid4(), uuid4()
    job, db = prepared(actor), AsyncMock()
    job.result["received_rejected_usage"] = {"input_tokens": 74010, "output_tokens": 9612}
    original_params, original_result = deepcopy(job.params), deepcopy(job.result)
    observed = job.updated_at
    calls = []
    async def execute(statement, parameters):
        assert "pg_advisory_xact_lock" in str(statement) and parameters == {"tenant_id": str(tenant)}
        calls.append("advisory")
    async def lock(*_args):
        calls.append("tenant")
    async def get(*_args, **kwargs):
        assert kwargs == {"tenant_id": str(tenant), "for_update": True}
        calls.append("job")
        return job
    db.execute.side_effect = execute
    monkeypatch.setattr(job_service, "_lock_tenant_row", lock)
    monkeypatch.setattr(job_service, "get_ai_job", get)
    assert await job_service.quarantine_generation(db, job_id="job", tenant_id=tenant,
        user_id=actor, expected_updated_at=observed) == "quarantined"
    assert calls == ["advisory", "tenant", "job"]
    assert job.status == "failed" and job.stage == "quarantined"
    assert job.result == original_result
    assert {k: v for k, v in job.params.items() if k != "generation_quarantine"} == original_params
    assert "provider_outcome" not in job.params["generation_quarantine"]
    assert "cost" not in job.params["generation_quarantine"]
    assert router._visible_job_status_message(job) == ("failed", job.message)
    job.errors = ["generation_stage_outcome_unknown"]
    assert router._visible_job_errors(job) == ["generation_stage_outcome_unknown"]
    assert not job_service.can_abandon_unknown(job)
    calls.clear()
    assert await job_service.quarantine_generation(db, job_id="job", tenant_id=tenant,
        user_id=actor, expected_updated_at=observed) == "quarantined"
    db.commit.assert_awaited_once()
    assert await job_service.release_generation_reservation_once(db, job_id="job", tenant_id=tenant) is False
    assert job.result == original_result


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["stale", "foreign", "absent", "running", "completed", "course",
    "no_pending", "malformed", "final_intent", "final_receipt", "existing_abandonment", "naive"])
async def test_conflicting_changes_and_foreign_or_finalizing_jobs_cannot_be_terminalized(monkeypatch, change):
    actor, tenant = uuid4(), uuid4()
    job, db = prepared(actor), AsyncMock()
    observed = job.updated_at
    if change == "stale":
        job.updated_at += timedelta(microseconds=1)
    if change == "foreign":
        job.user_id = uuid4()
    if change == "running":
        job.status = "running"
    if change == "completed":
        job.status = "completed"
    if change == "course":
        job.course_id = uuid4()
    if change == "no_pending":
        job.result = {}
    if change == "malformed":
        job.result = {"v3_pending_stages": {"bad": True}}
    if change == "final_intent":
        job.result["v3_final_save_intent"] = None
    if change == "final_receipt":
        job.result["v3_final_save_receipt"] = None
    if change == "existing_abandonment":
        job.params["generation_abandonment"] = None
    if change == "naive":
        observed = observed.replace(tzinfo=None)
    before = deepcopy(vars(job))
    monkeypatch.setattr(job_service, "_lock_tenant_row", AsyncMock())
    monkeypatch.setattr(job_service, "get_ai_job", AsyncMock(return_value=None if change == "absent" else job))
    result = await job_service.quarantine_generation(db, job_id="job", tenant_id=tenant,
        user_id=actor, expected_updated_at=observed)
    assert result == ("not_found" if change in {"foreign", "absent"} else "conflict")
    assert vars(job) == before
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_idempotent_record_fails_closed_if_pending_or_actor_changes(monkeypatch):
    actor, tenant = uuid4(), uuid4()
    job, db = prepared(actor), AsyncMock()
    observed = job.updated_at
    monkeypatch.setattr(job_service, "_lock_tenant_row", AsyncMock())
    monkeypatch.setattr(job_service, "get_ai_job", AsyncMock(return_value=job))
    assert await job_service.quarantine_generation(db, job_id="job", tenant_id=tenant,
        user_id=actor, expected_updated_at=observed) == "quarantined"
    next(iter(job.result["v3_pending_stages"]["entries"].values()))["token"] = "c" * 32
    assert not job_service.is_quarantined_generation(job)
    assert await job_service.quarantine_generation(db, job_id="job", tenant_id=tenant,
        user_id=actor, expected_updated_at=observed) == "conflict"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_endpoint_ack_is_explicit_and_does_not_assert_a_provider_response_or_cost(monkeypatch):
    actor, tenant, observed = uuid4(), uuid4(), datetime.now(UTC)
    user = SimpleNamespace(id=actor, tenant_id=tenant)
    callback = AsyncMock(return_value="quarantined")
    monkeypatch.setattr(router, "quarantine_generation", callback)
    with pytest.raises(HTTPException) as error:
        await router.quarantine_job("job", QuarantineGenerationRequest(
            acknowledge_retained_stage=False, expected_updated_at=observed), AsyncMock(), user)
    assert error.value.status_code == 409
    callback.assert_not_awaited()
    response = await router.quarantine_job("job", QuarantineGenerationRequest(
        acknowledge_retained_stage=True, expected_updated_at=observed), AsyncMock(), user)
    assert response == {"status": "quarantined", "pending_stage": "retained", "reservation": "unchanged"}
    callback.assert_awaited_once()
    with pytest.raises(ValidationError):
        QuarantineGenerationRequest(acknowledge_retained_stage=1, expected_updated_at=observed)
    with pytest.raises(ValidationError):
        QuarantineGenerationRequest(acknowledge_retained_stage=True, expected_updated_at=observed,
            provider_outcome="received")
