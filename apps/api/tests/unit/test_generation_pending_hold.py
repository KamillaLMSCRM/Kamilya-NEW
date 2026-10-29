from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from billiard.exceptions import SoftTimeLimitExceeded
from sqlalchemy.dialects import postgresql

from app.modules.ai.job_service import interrupt_pending_generation_execution


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery", ["job", "resume-delivery"])
async def test_pending_hold_predicate_binds_tenant_delivery_and_engine(delivery):
    db = AsyncMock()
    db.execute.return_value = Mock(rowcount=1)
    assert await interrupt_pending_generation_execution(db, "job", "tenant", delivery)
    statement = db.execute.await_args_list[1].args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    values = compiled.params.values()
    assert "tenant_id" in sql and "status" in sql
    assert all(value in values for value in ("tenant", "job", delivery, "pending", "interrupted", "evidence_v2", "direct_source"))
    assert "delivery_task_id" in values
    assert ("resume_count" in values) == (delivery == "job")
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_pending_hold_loses_claim_race_without_mutation():
    db = AsyncMock()
    db.execute.return_value = Mock(rowcount=0)
    assert not await interrupt_pending_generation_execution(db, "job", "tenant", "job")


@pytest.mark.asyncio
async def test_pending_hold_propagates_database_failure_and_requires_identity():
    db = AsyncMock()
    db.execute.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError):
        await interrupt_pending_generation_execution(db, "job", "tenant", "job")
    db.commit.assert_not_awaited()
    with pytest.raises(ValueError):
        await interrupt_pending_generation_execution(AsyncMock(), "job", "tenant", None)


@pytest.mark.parametrize(("hold_result", "expected"), [(True, "interrupted"), (False, "claim_outcome_unknown"), (RuntimeError(), "claim_outcome_unknown")])
def test_task_preclaim_failure_holds_or_reports_unknown(monkeypatch, hold_result, expected):
    from app.core import db
    from app.modules.ai import job_service, tasks

    session = AsyncMock()
    manager = AsyncMock()
    manager.__aenter__.return_value = session
    monkeypatch.setattr(db, "async_session_factory", lambda: manager)
    monkeypatch.setattr(db, "engine", SimpleNamespace(dispose=AsyncMock()))
    monkeypatch.setattr(job_service, "claim_generation_execution", AsyncMock(side_effect=RuntimeError()))
    if isinstance(hold_result, Exception):
        hold = AsyncMock(side_effect=hold_result)
    else:
        hold = AsyncMock(return_value=hold_result)
    monkeypatch.setattr(job_service, "interrupt_pending_generation_execution", hold)
    provider = AsyncMock()
    monkeypatch.setattr(tasks, "run_generation_pipeline", provider)
    result = tasks.generate_course_task.apply(task_id="job", kwargs={
        "job_id": "job", "documents": [], "tenant_id": str(uuid4()), "user_id": str(uuid4()),
        "source_analysis": {"generation_engine": "evidence_v2", "analysis_mode": "direct_source"},
    }, throw=True).get()
    assert result["status"] == expected
    hold.assert_awaited_once()
    provider.assert_not_awaited()


@pytest.mark.parametrize("failure", [RuntimeError(), SoftTimeLimitExceeded()])
def test_task_does_not_claim_terminal_transition_when_fence_rejects(monkeypatch, failure):
    from app.core import db
    from app.modules.ai import job_service, tasks

    manager = AsyncMock()
    manager.__aenter__.return_value = AsyncMock()
    monkeypatch.setattr(db, "async_session_factory", lambda: manager)
    monkeypatch.setattr(db, "engine", SimpleNamespace(dispose=AsyncMock()))
    monkeypatch.setattr(job_service, "claim_generation_execution", AsyncMock(return_value=True))
    monkeypatch.setattr(job_service, "fail_claimed_generation_execution", AsyncMock(return_value=False))
    monkeypatch.setattr(job_service, "interrupt_claimed_generation_execution", AsyncMock(return_value=False))
    monkeypatch.setattr(tasks, "run_generation_pipeline", AsyncMock(side_effect=failure))
    result = tasks.generate_course_task.apply(task_id="job", kwargs={
        "job_id": "job", "documents": [], "tenant_id": str(uuid4()), "user_id": str(uuid4()),
        "source_analysis": {"generation_engine": "evidence_v2", "analysis_mode": "direct_source"},
    }, throw=True).get()
    assert result["status"] == "claim_outcome_unknown"
