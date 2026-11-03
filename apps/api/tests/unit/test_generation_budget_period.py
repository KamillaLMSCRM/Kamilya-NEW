"""A cancellation in a later month must not spend another month's refund."""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.ai import budget, job_service


def owned_job(**changes):
    values = dict(course_id=None, result=None,
                  params={"documents": ["synthetic"], "generation_reservation_required": True},
                  created_at=datetime(2026, 10, 29, 12, tzinfo=UTC),
                  started_at=datetime(2026, 10, 29, 12, 1, tzinfo=UTC))
    return SimpleNamespace(**(values | changes))


@pytest.mark.asyncio
async def test_later_month_cancellation_refunds_only_proven_admission_period(monkeypatch):
    job, db = owned_job(), AsyncMock()
    monkeypatch.setattr(job_service, "get_ai_job", AsyncMock(return_value=job))
    trial, refund = AsyncMock(), AsyncMock()
    monkeypatch.setattr("app.core.trial_limits.release_ai_course_generation", trial)
    monkeypatch.setattr(budget, "refund_llm_budget", refund)
    assert await job_service.release_generation_reservation_once(db, job_id="job", tenant_id="tenant") is True
    refund.assert_awaited_once_with(db, "tenant", "generate_course", month_key="2026-10")
    assert job.params["generation_reservation_released"] is True
    assert await job_service.release_generation_reservation_once(db, job_id="job", tenant_id="tenant") is False
    refund.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("created,started", [(None, None),
    (datetime(2026, 10, 31, 23, 59, tzinfo=UTC), datetime(2026, 11, 1, 0, 1, tzinfo=UTC))])
async def test_legacy_unproven_period_cannot_refund_or_mark_released(monkeypatch, created, started):
    job, db = owned_job(created_at=created, started_at=started), AsyncMock()
    monkeypatch.setattr(job_service, "get_ai_job", AsyncMock(return_value=job))
    trial, refund = AsyncMock(), AsyncMock()
    monkeypatch.setattr("app.core.trial_limits.release_ai_course_generation", trial)
    monkeypatch.setattr(budget, "refund_llm_budget", refund)
    with pytest.raises(ValueError, match="generation_budget_period_unverified"):
        await job_service.release_generation_reservation_once(db, job_id="job", tenant_id="tenant")
    trial.assert_not_awaited()
    refund.assert_not_awaited()
    assert "generation_reservation_released" not in job.params


@pytest.mark.asyncio
async def test_explicit_charge_period_resolves_midnight_interval(monkeypatch):
    job, db = owned_job(created_at=datetime(2026, 10, 31, 23, 59, tzinfo=UTC),
                        started_at=datetime(2026, 11, 1, 0, 1, tzinfo=UTC)), AsyncMock()
    job.params["generation_budget_month"] = "2026-11"
    monkeypatch.setattr(job_service, "get_ai_job", AsyncMock(return_value=job))
    refund = AsyncMock()
    monkeypatch.setattr("app.core.trial_limits.release_ai_course_generation", AsyncMock())
    monkeypatch.setattr(budget, "refund_llm_budget", refund)
    assert await job_service.release_generation_reservation_once(db, job_id="job", tenant_id="tenant") is True
    assert refund.await_args.kwargs == {"month_key": "2026-11"}


@pytest.mark.asyncio
async def test_refund_uses_explicit_month_without_touching_current_month():
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(rowcount=1)
    await budget.refund_llm_budget(db, "tenant", "generate_course", month_key="2026-10")
    statement, params = db.execute.await_args.args
    assert params["m"] == "2026-10" and "month_key = :m" in str(statement)


@pytest.mark.asyncio
@pytest.mark.parametrize("rowcount", [0, -1])
async def test_missing_or_unverified_historical_usage_cannot_claim_refund(rowcount):
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(rowcount=rowcount)
    with pytest.raises(ValueError, match="llm_budget_refund_unverified"):
        await budget.refund_llm_budget(db, "tenant", "generate_course", month_key="2026-10")


@pytest.mark.asyncio
async def test_implicit_period_keeps_existing_best_effort_refund_contract(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, _tz):
            return datetime(2026, 11, 2, tzinfo=UTC)
    monkeypatch.setattr(budget, "datetime", Clock)
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(rowcount=0)
    await budget.refund_llm_budget(db, "tenant", "generate_course")
    statement, params = db.execute.await_args.args
    assert "cost_cents >= :cost" not in str(statement) and "GREATEST(0," in str(statement)
    assert params["m"] == "2026-11"


@pytest.mark.asyncio
@pytest.mark.parametrize("period", ["2026-13", "2026-00", "2026-1", "private", True])
async def test_invalid_explicit_period_fails_before_database(period):
    db = AsyncMock()
    with pytest.raises(ValueError, match="llm_budget_period_invalid"):
        await budget.refund_llm_budget(db, "tenant", "generate_course", month_key=period)
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_admission_receipt_and_dispatch_failure_keep_charge_month_across_midnight(monkeypatch):
    from uuid import uuid4

    clock = SimpleNamespace(value=datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC))
    monkeypatch.setattr(job_service, "datetime", SimpleNamespace(now=lambda _tz: clock.value))
    job, db = SimpleNamespace(id="job", params={}), AsyncMock()
    async def create(_db, **kwargs):
        assert "generation_budget_month" not in kwargs["params"]
        job.params = dict(kwargs["params"])
        return job
    monkeypatch.setattr(job_service, "create_admitted_ai_job", create)
    monkeypatch.setattr(job_service, "build_ai_job_queue_metadata", AsyncMock(return_value={}))
    monkeypatch.setattr(job_service, "update_ai_job", AsyncMock())
    monkeypatch.setattr("app.core.auth._set_tenant_security_context", AsyncMock())
    monkeypatch.setattr("app.core.auth._set_user_security_context", AsyncMock())
    monkeypatch.setattr("app.core.trial_limits.reserve_ai_course_generation", AsyncMock())
    monkeypatch.setattr("app.core.trial_limits.release_ai_course_generation", AsyncMock())
    charge, refund = AsyncMock(), AsyncMock()
    monkeypatch.setattr(budget, "check_and_charge_llm_budget", charge)
    monkeypatch.setattr(budget, "refund_llm_budget", refund)
    async def before_commit(active):
        assert active.params["generation_budget_month"] == "2026-10"
    class Dispatcher:
        def dispatch(self, *_args, **_kwargs):
            clock.value = datetime(2026, 11, 1, 0, 0, 1, tzinfo=UTC)
            raise job_service.AIJobSubmissionUnavailableError("synthetic")
    with pytest.raises(job_service.AIJobSubmissionUnavailableError):
        await job_service.submit_ai_job(db, tenant_id=uuid4(), user_id=uuid4(), course_id=None,
            params={"generation_budget_month": "2099-12"}, task_name="generate_course", task_kwargs=lambda _job: {},
            active_limit=2, worker_concurrency=1, historical_estimate_seconds=1, generation=True,
            reserve_course_generation=True, dispatcher=Dispatcher(), before_commit=before_commit)
    assert charge.await_args.kwargs["month_key"] == refund.await_args.kwargs["month_key"] == "2026-10"
    assert job.params["generation_budget_month"] == "2026-10"
