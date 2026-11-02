from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.ai import budget, job_service, router, tasks


def test_celery_accepted_then_ack_lost_is_unknown_and_never_republished(monkeypatch):
    sent = []
    def publish(**kwargs):
        sent.append(kwargs)
        raise TimeoutError("private broker details")
    monkeypatch.setattr(tasks, "generate_course_task", SimpleNamespace(apply_async=publish))
    with pytest.raises(job_service.AIJobDispatchOutcomeUnknownError) as error:
        job_service.CeleryAIJobDispatcher().dispatch("generate_course", task_id="delivery", kwargs={"job_id": "job"})
    assert len(sent) == 1 and sent[0]["task_id"] == "delivery" and sent[0]["retry"] is False
    assert "private broker details" not in str(error.value)


def test_missing_celery_task_is_known_unavailable(monkeypatch):
    monkeypatch.setattr(tasks, "generate_course_task", None)
    with pytest.raises(job_service.AIJobSubmissionUnavailableError):
        job_service.CeleryAIJobDispatcher().dispatch("generate_course", task_id="delivery", kwargs={})


@pytest.mark.asyncio
async def test_submit_unknown_preserves_committed_job_and_reservation(monkeypatch):
    tenant, actor = uuid4(), uuid4()
    job, db, sent = SimpleNamespace(id="job", params={}), AsyncMock(), []
    async def create(_db, **kwargs):
        job.params = dict(kwargs["params"])
        return job
    monkeypatch.setattr(job_service, "create_admitted_ai_job", create)
    monkeypatch.setattr(job_service, "build_ai_job_queue_metadata", AsyncMock(return_value={}))
    update = AsyncMock()
    monkeypatch.setattr(job_service, "update_ai_job", update)
    reserve, release, charge, refund = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr("app.core.trial_limits.reserve_ai_course_generation", reserve)
    monkeypatch.setattr("app.core.trial_limits.release_ai_course_generation", release)
    monkeypatch.setattr(budget, "check_and_charge_llm_budget", charge)
    monkeypatch.setattr(budget, "refund_llm_budget", refund)
    class Dispatcher:
        def dispatch(self, name, *, task_id, kwargs):
            sent.append((name, task_id, kwargs))
            raise job_service.AIJobDispatchOutcomeUnknownError("")
    with pytest.raises(job_service.AIJobDispatchOutcomeUnknownError) as error:
        await job_service.submit_ai_job(db, tenant_id=tenant, user_id=actor, course_id=None,
            params={"documents": ["source"], "reference_decisions": ["synthetic"]},
            task_name="generate_course", task_kwargs=lambda active: {"job_id": active.id},
            active_limit=2, worker_concurrency=1, historical_estimate_seconds=1,
            generation=True, reserve_course_generation=True, dispatcher=Dispatcher())
    assert error.value.job_id == "job" and len(sent) == 1 and sent[0][1] == "job"
    assert job.params["generation_reservation_released"] is False
    assert job.params["reference_decisions"] == ["synthetic"] and job.params["generation_budget_month"]
    db.commit.assert_awaited_once()
    reserve.assert_awaited_once()
    charge.assert_awaited_once()
    release.assert_not_awaited()
    refund.assert_not_awaited()
    update.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_unknown_keeps_new_delivery_and_existing_checkpoint(monkeypatch):
    tenant = uuid4()
    job = SimpleNamespace(id="job", tenant_id=tenant, status="interrupted", stage="interrupted",
        params={"source_analysis": {"analysis_mode": "direct_source", "generation_engine": "evidence_v3"},
                "generation_reservation_released": False, "reference_decisions": ["synthetic"]},
        result={"saved_checkpoint": {"synthetic": True}, "resume_count": 1},
        message="", errors=[], completed_at=None, started_at=datetime.now(UTC), updated_at=datetime.now(UTC))
    before = deepcopy(job.result)
    db, sent = AsyncMock(), []
    monkeypatch.setattr(job_service, "_lock_tenant_row", AsyncMock())
    monkeypatch.setattr(job_service, "get_ai_job", AsyncMock(return_value=job))
    monkeypatch.setattr(job_service, "count_active_ai_jobs", AsyncMock(return_value=0))
    monkeypatch.setattr(job_service, "build_ai_job_queue_metadata", AsyncMock(return_value={}))
    update = AsyncMock()
    monkeypatch.setattr(job_service, "update_ai_job", update)
    class Dispatcher:
        def dispatch(self, name, *, task_id, kwargs):
            sent.append((name, task_id, kwargs))
            raise job_service.AIJobDispatchOutcomeUnknownError("")
    with pytest.raises(job_service.AIJobDispatchOutcomeUnknownError) as error:
        await job_service.resume_interrupted_ai_job(db, job=job, tenant_id=tenant,
            task_kwargs={"job_id": job.id}, active_limit=2, worker_concurrency=1,
            historical_estimate_seconds=1, dispatcher=Dispatcher())
    assert error.value.job_id == "job" and len(sent) == 1
    assert job.status == "pending" and job.result["delivery_task_id"] == sent[0][1]
    assert job.result["resume_count"] == 2 and job.result["saved_checkpoint"] == before["saved_checkpoint"]
    assert job.params["generation_reservation_released"] is False and job.params["reference_decisions"] == ["synthetic"]
    update.assert_not_awaited()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_resume_http_unknown_exposes_only_reconciliation_job_id(monkeypatch):
    tenant, actor = uuid4(), uuid4()
    job = SimpleNamespace(id="job", user_id=actor, course_id=None, result={}, status="interrupted",
        params={"documents": ["source"], "course_structure": {"lessons_per_module": 1},
                "source_analysis": {"analysis_mode": "direct_source", "generation_engine": "evidence_v3"}})
    monkeypatch.setattr(router, "get_ai_job", AsyncMock(return_value=job))
    monkeypatch.setattr(router, "is_resumable_generation_job", lambda _job: True)
    monkeypatch.setattr(router, "resolve_tenant_ai_active_limit", AsyncMock(return_value=2))
    monkeypatch.setattr(router, "resume_interrupted_ai_job", AsyncMock(
        side_effect=job_service.AIJobDispatchOutcomeUnknownError("job")))
    with pytest.raises(HTTPException) as error:
        await router.resume_generation("job", AsyncMock(), SimpleNamespace(id=actor, tenant_id=tenant))
    assert error.value.status_code == 503
    assert error.value.detail == {"code": "ai_job_dispatch_outcome_unknown", "job_id": "job"}


@pytest.mark.asyncio
async def test_initial_http_unknown_does_not_release_already_reserved_quota(monkeypatch):
    from app.modules.ai.schemas import AIGenerateRequest
    from tests.unit.test_ai_router_admission import _lenient_db

    tenant, actor, job = uuid4(), uuid4(), str(uuid4())
    analysis = SimpleNamespace(status="compatible", score=1.0, requires_decision=False, clusters=[])
    monkeypatch.setattr("app.modules.ai.source_analysis.analyze_document_set", AsyncMock(return_value=analysis))
    monkeypatch.setattr("app.modules.ai.source_analysis.document_chunk_totals", AsyncMock(return_value={}))
    monkeypatch.setattr("app.modules.ai.source_analysis.document_script_languages", AsyncMock(return_value={}))
    check, release = AsyncMock(), AsyncMock()
    monkeypatch.setattr("app.core.demo_limits.check_ai_generation_quota", check)
    monkeypatch.setattr("app.core.demo_limits.release_ai_generation_quota", release)
    monkeypatch.setattr(router, "resolve_tenant_ai_active_limit", AsyncMock(return_value=2))
    monkeypatch.setattr(router, "submit_ai_job", AsyncMock(side_effect=job_service.AIJobDispatchOutcomeUnknownError(job)))
    with pytest.raises(HTTPException) as error:
        await router.generate_course(AIGenerateRequest(documents=[uuid4()]), db=_lenient_db(),
            user=SimpleNamespace(id=actor, tenant_id=tenant))
    assert error.value.status_code == 503
    assert error.value.detail == {"code": "ai_job_dispatch_outcome_unknown", "job_id": job}
    check.assert_awaited_once()
    release.assert_not_awaited()


@pytest.mark.asyncio
async def test_late_delivery_can_claim_matching_pending_job():
    from sqlalchemy.dialects import postgresql

    db = AsyncMock()
    db.execute.side_effect = [None, SimpleNamespace(rowcount=1)]
    assert await job_service.claim_generation_execution(db, "job", str(uuid4()), "delivery")
    query = db.execute.await_args_list[1].args[0].compile(dialect=postgresql.dialect())
    assert "pending" in query.params.values() and "delivery" in query.params.values()
