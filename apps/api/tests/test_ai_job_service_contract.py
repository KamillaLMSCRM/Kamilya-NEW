"""Unit contracts for terminal AI job state protection."""
from __future__ import annotations

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

    async def get_cancelled_job(*args, **kwargs):
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
