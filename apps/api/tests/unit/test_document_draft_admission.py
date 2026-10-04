"""Caller receipt and AI job must share admission commit before dispatch."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.ai import job_service


@pytest.mark.asyncio
async def test_caller_link_precedes_commit_and_dispatch(monkeypatch):
    events = []
    job = SimpleNamespace(id="synthetic-job")
    db = SimpleNamespace(commit=AsyncMock(side_effect=lambda: events.append("commit")))
    monkeypatch.setattr(job_service, "create_admitted_ai_job", AsyncMock(return_value=job))
    monkeypatch.setattr(job_service, "build_ai_job_queue_metadata", AsyncMock(return_value={}))

    async def link(admitted):
        assert admitted is job
        events.append("link")

    class Dispatcher:
        def dispatch(self, *args, **kwargs):
            events.append("dispatch")

    returned, _ = await job_service.submit_ai_job(
        db, tenant_id=UUID(int=1), user_id=UUID(int=2), course_id=None,
        params={}, task_name="generate_course", task_kwargs=lambda admitted: {},
        active_limit=2, worker_concurrency=2, historical_estimate_seconds=510,
        dispatcher=Dispatcher(), before_commit=link,
    )
    assert returned is job
    assert events == ["link", "commit", "dispatch"]


@pytest.mark.asyncio
async def test_caller_link_failure_does_not_commit_or_dispatch(monkeypatch):
    job = SimpleNamespace(id="synthetic-job")
    db = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(job_service, "create_admitted_ai_job", AsyncMock(return_value=job))
    monkeypatch.setattr(job_service, "build_ai_job_queue_metadata", AsyncMock(return_value={}))
    dispatch = AsyncMock()

    async def failing_link(admitted):
        raise ValueError("synthetic-link-failure")

    with pytest.raises(ValueError, match="synthetic-link-failure"):
        await job_service.submit_ai_job(
            db, tenant_id=UUID(int=1), user_id=UUID(int=2), course_id=None,
            params={}, task_name="generate_course", task_kwargs=lambda admitted: {},
            active_limit=2, worker_concurrency=2, historical_estimate_seconds=510,
            dispatcher=SimpleNamespace(dispatch=dispatch), before_commit=failing_link,
        )
    db.commit.assert_not_awaited()
    dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_failure_rebinds_rls_before_recording_failure(monkeypatch):
    from app.core import auth

    events = []
    db = SimpleNamespace(commit=AsyncMock(side_effect=lambda: events.append("commit")))
    job = SimpleNamespace(id="synthetic-job")
    monkeypatch.setattr(job_service, "create_admitted_ai_job", AsyncMock(return_value=job))
    monkeypatch.setattr(job_service, "build_ai_job_queue_metadata", AsyncMock(return_value={}))
    monkeypatch.setattr(auth, "_set_tenant_security_context", AsyncMock(side_effect=lambda *args: events.append("tenant")))
    monkeypatch.setattr(auth, "_set_user_security_context", AsyncMock(side_effect=lambda *args: events.append("user")))
    monkeypatch.setattr(job_service, "update_ai_job", AsyncMock(side_effect=lambda *args, **kwargs: events.append("update")))
    class Failure:
        def dispatch(self, *args, **kwargs):
            raise job_service.AIJobSubmissionUnavailableError("synthetic-failure")
    with pytest.raises(job_service.AIJobSubmissionUnavailableError):
        await job_service.submit_ai_job(db, tenant_id=UUID(int=1), user_id=UUID(int=2), course_id=None,
            params={}, task_name="generate_course", task_kwargs=lambda admitted: {}, active_limit=2,
            worker_concurrency=2, historical_estimate_seconds=510, dispatcher=Failure())
    assert events == ["commit", "tenant", "user", "update", "commit"]
