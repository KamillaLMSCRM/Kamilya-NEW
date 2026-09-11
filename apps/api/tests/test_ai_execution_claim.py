"""Contracts for durable, at-least-once AI generation delivery."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from billiard.exceptions import SoftTimeLimitExceeded

from app.modules.ai import job_service


@pytest.mark.asyncio
async def test_claim_generation_execution_is_atomic_and_commits():
    db = AsyncMock()
    db.execute.return_value = Mock(rowcount=1)

    tenant_id = uuid4()
    claimed = await job_service.claim_generation_execution(db, "job-1", tenant_id)

    assert claimed is True
    db.commit.assert_awaited_once()
    assert len(db.execute.await_args_list) == 2
    context_statement = db.execute.await_args_list[0].args[0]
    assert "set_current_tenant" in str(context_statement)
    assert db.execute.await_args_list[0].args[1] == {"tid": tenant_id}
    statement = db.execute.await_args_list[1].args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "ai_jobs.status = 'pending'" in compiled
    assert "UPDATE ai_jobs" in compiled


@pytest.mark.parametrize("rowcount", [0, None])
async def test_claim_generation_execution_rejects_duplicate_or_terminal_delivery(rowcount):
    db = AsyncMock()
    db.execute.return_value = Mock(rowcount=rowcount)

    assert await job_service.claim_generation_execution(db, "job-1", uuid4()) is False
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_claim_generation_execution_fails_closed_without_tenant_context():
    with pytest.raises(ValueError, match="tenant_id is required"):
        await job_service.claim_generation_execution(AsyncMock(), "job-1")


@pytest.mark.asyncio
async def test_interrupt_generation_execution_is_atomic_resumable_and_commits():
    db = AsyncMock()
    db.execute.return_value = Mock(rowcount=1)
    tenant_id = str(uuid4())

    interrupted = await job_service.interrupt_claimed_generation_execution(
        db,
        "job-timeout",
        tenant_id,
    )

    assert interrupted is True
    db.commit.assert_awaited_once()
    assert len(db.execute.await_args_list) == 2
    statement = db.execute.await_args_list[1].args[0]
    compiled_statement = statement.compile()
    compiled = str(compiled_statement)
    assert "ai_jobs.status" in compiled
    assert "UPDATE ai_jobs" in compiled
    values = compiled_statement.params
    assert "running" in values.values()
    assert "interrupted" in values.values()
    assert "generation_interrupted" in str(values)


def test_failed_pipeline_result_is_terminal_and_not_retried(monkeypatch):
    from app.core import db as db_module
    from app.modules.ai import tasks

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class Factory:
        def __call__(self):
            return Session()

    async def claimed(*args, **kwargs):
        return True

    captured = {}

    async def failed_pipeline(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="failed", message="provider failed", progress=42)

    monkeypatch.setattr(db_module, "async_session_factory", Factory())
    monkeypatch.setattr(job_service, "claim_generation_execution", claimed)
    monkeypatch.setattr(tasks, "run_generation_pipeline", failed_pipeline)
    monkeypatch.setattr(tasks, "_run_async", lambda awaitable: asyncio.run(awaitable))

    result = tasks.generate_course_task.run(
        job_id="job-1",
        documents=[],
        num_modules=1,
        lessons_per_module=4,
        tenant_id=str(uuid4()),
        user_id=str(uuid4()),
    )

    assert result == {"job_id": "job-1", "status": "failed", "message": "provider failed", "progress": 42}
    assert captured["num_modules"] == 1
    assert captured["lessons_per_module"] == 4


def test_pipeline_exception_is_persisted_as_terminal_failure(monkeypatch):
    from app.core import db as db_module
    from app.modules.ai import tasks

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class Factory:
        def __call__(self):
            return Session()

    async def claimed(*args, **kwargs):
        return True

    async def exploding_pipeline(**kwargs):
        raise RuntimeError("provider disconnected")

    persisted = AsyncMock(return_value=True)
    monkeypatch.setattr(db_module, "async_session_factory", Factory())
    monkeypatch.setattr(job_service, "claim_generation_execution", claimed)
    monkeypatch.setattr(job_service, "fail_claimed_generation_execution", persisted)
    monkeypatch.setattr(tasks, "run_generation_pipeline", exploding_pipeline)
    monkeypatch.setattr(tasks, "_run_async", lambda awaitable: asyncio.run(awaitable))

    tenant_id = str(uuid4())
    result = tasks.generate_course_task.run(
        job_id="job-2",
        documents=[],
        tenant_id=tenant_id,
        user_id=str(uuid4()),
    )

    assert result == {
        "job_id": "job-2",
        "status": "failed",
        "message": "RuntimeError: generation failed",
    }
    persisted.assert_awaited_once()
    assert persisted.await_args.args[1:] == (
        "job-2",
        "RuntimeError: generation failed",
        tenant_id,
    )


def test_soft_time_limit_is_persisted_as_resumable_interruption(monkeypatch):
    from app.core import db as db_module
    from app.modules.ai import tasks

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class Factory:
        def __call__(self):
            return Session()

    async def claimed(*args, **kwargs):
        return True

    async def timed_out_pipeline(**kwargs):
        raise SoftTimeLimitExceeded()

    interrupted = AsyncMock(return_value=True)
    terminal_failure = AsyncMock(return_value=True)
    monkeypatch.setattr(db_module, "async_session_factory", Factory())
    monkeypatch.setattr(job_service, "claim_generation_execution", claimed)
    monkeypatch.setattr(job_service, "interrupt_claimed_generation_execution", interrupted, raising=False)
    monkeypatch.setattr(job_service, "fail_claimed_generation_execution", terminal_failure)
    monkeypatch.setattr(tasks, "run_generation_pipeline", timed_out_pipeline)
    monkeypatch.setattr(tasks, "_run_async", lambda awaitable: asyncio.run(awaitable))

    tenant_id = str(uuid4())
    result = tasks.generate_course_task.run(
        job_id="job-timeout",
        documents=[],
        tenant_id=tenant_id,
        user_id=str(uuid4()),
    )

    assert result == {
        "job_id": "job-timeout",
        "status": "interrupted",
        "message": "Генерация приостановлена и может быть продолжена без повторной обработки готовых частей",
    }
    interrupted.assert_awaited_once_with(
        interrupted.await_args.args[0],
        "job-timeout",
        tenant_id,
    )
    terminal_failure.assert_not_awaited()
