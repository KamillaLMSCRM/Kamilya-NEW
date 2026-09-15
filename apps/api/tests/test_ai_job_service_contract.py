"""Unit contracts for terminal AI job state protection."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.models.ai_job import AIJob
from app.modules.ai import job_service


@pytest.mark.asyncio
async def test_update_ai_job_does_not_resurrect_cancelled_job(monkeypatch):
    job = AIJob(
        id="cancelled-job-contract",
        status="cancelled",
        stage="cancelled",
        message="worker diagnostic retained",
        errors={"recovery": {"code": "stale_ai_job_recovered"}},
        result={"checkpoint": "retained"},
    )

    lookup = {}

    async def get_cancelled_job(*args, **kwargs):
        lookup.update(kwargs)
        return job

    monkeypatch.setattr(job_service, "get_ai_job", get_cancelled_job)

    result = await job_service.update_ai_job(
        object(),
        job.id,
        tenant_id="tenant-contract",
        status="completed",
        stage="completed",
        message="late worker completion",
        progress=100,
    )

    assert result is job
    assert job.status == "cancelled"
    assert job.stage == "cancelled"
    assert job.message == "worker diagnostic retained"
    assert job.errors == {"recovery": {"code": "stale_ai_job_recovered"}}
    assert job.result == {"checkpoint": "retained"}
    assert lookup == {"tenant_id": "tenant-contract", "for_update": True}


@pytest.mark.asyncio
async def test_update_ai_job_sets_completed_at_for_completed_status(monkeypatch):
    job = AIJob(id="completed-job-contract", status="running", stage="saving")

    async def get_running_job(*args, **kwargs):
        return job

    monkeypatch.setattr(job_service, "get_ai_job", get_running_job)
    fixed_now = datetime(2026, 9, 14, tzinfo=UTC)
    monkeypatch.setattr(job_service, "datetime", type("FixedDateTime", (), {
        "now": staticmethod(lambda *_args, **_kwargs: fixed_now),
    }))

    result = await job_service.update_ai_job(
        type("DB", (), {"flush": AsyncMock()})(),
        job.id,
        tenant_id="tenant-contract",
        status="completed",
        stage="completed",
    )

    assert result is job
    assert job.completed_at == fixed_now


@pytest.mark.asyncio
async def test_generation_reservation_release_is_durable_and_idempotent(monkeypatch):
    from app.core import trial_limits
    from app.modules.ai import budget

    job = AIJob(
        id="reservation-contract",
        tenant_id="tenant-contract",
        status="cancelled",
        params={
            "documents": ["doc-1"],
            "generation_reservation_required": True,
            "generation_reservation_released": False,
        },
    )
    lookup = AsyncMock(return_value=job)
    release = AsyncMock()
    refund = AsyncMock()
    db = type("DB", (), {"flush": AsyncMock()})()
    monkeypatch.setattr(job_service, "get_ai_job", lookup)
    monkeypatch.setattr(trial_limits, "release_ai_course_generation", release)
    monkeypatch.setattr(budget, "refund_llm_budget", refund)

    assert await job_service.release_generation_reservation_once(
        db, job_id=job.id, tenant_id="tenant-contract"
    ) is True
    assert await job_service.release_generation_reservation_once(
        db, job_id=job.id, tenant_id="tenant-contract"
    ) is False

    release.assert_awaited_once_with(db, "tenant-contract")
    refund.assert_awaited_once_with(db, "tenant-contract", "generate_course")
    assert job.params["generation_reservation_released"] is True
