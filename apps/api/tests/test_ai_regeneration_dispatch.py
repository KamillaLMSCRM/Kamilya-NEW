from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

from app.modules.ai import job_service


def _job(course_id=None):
    return SimpleNamespace(id="job-1", course_id=course_id, status="pending")


def _router_job(course_id):
    now = datetime.now(UTC)
    return SimpleNamespace(
        id="job-1",
        course_id=course_id,
        status="pending",
        progress=0,
        stage="queued",
        message="Job queued",
        errors=None,
        created_at=now,
        updated_at=now,
        started_at=None,
    )


def test_celery_dispatcher_maps_task_and_preserves_job_id():
    task = SimpleNamespace(apply_async=Mock())
    with patch("app.modules.ai.tasks.regenerate_module_task", task):
        job_service.CeleryAIJobDispatcher().dispatch(
            "regenerate_module",
            task_id="job-1",
            kwargs={"module_id": "module-1"},
        )

    task.apply_async.assert_called_once_with(
        task_id="job-1",
        kwargs={"module_id": "module-1"},
    )


def test_celery_dispatcher_wraps_enqueue_failure():
    task = SimpleNamespace(apply_async=Mock(side_effect=RuntimeError("broker down")))
    with (
        patch("app.modules.ai.tasks.generate_course_task", task),
        pytest.raises(job_service.AIJobSubmissionUnavailableError) as error,
    ):
        job_service.CeleryAIJobDispatcher().dispatch(
            "generate_course",
            task_id="job-1",
            kwargs={},
        )

    assert error.value.detail == "AI job could not be queued"


@pytest.mark.asyncio
async def test_submission_commits_then_dispatches_maintenance_without_generation_charges():
    db = AsyncMock()
    dispatcher = job_service.InMemoryAIJobDispatcher()
    tenant_id, user_id, course_id = uuid4(), uuid4(), uuid4()

    with (
        patch.object(job_service, "create_admitted_ai_job", AsyncMock(return_value=_job(course_id))) as admit,
        patch.object(job_service, "build_ai_job_queue_metadata", AsyncMock(return_value={"queue_position": 1})),
    ):
        job, metadata = await job_service.submit_ai_job(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            course_id=course_id,
            params={"action": "regenerate_module"},
            task_name="regenerate_module",
            task_kwargs=lambda admitted: {"job_id": admitted.id, "module_id": "module-1"},
            active_limit=2,
            worker_concurrency=2,
            historical_estimate_seconds=510,
            dispatcher=dispatcher,
        )

    assert job.id == "job-1"
    assert metadata == {"queue_position": 1}
    admit.assert_awaited_once()
    db.commit.assert_awaited_once()
    assert dispatcher.submissions == [
        ("regenerate_module", "job-1", {"job_id": "job-1", "module_id": "module-1"})
    ]


@pytest.mark.asyncio
async def test_generation_enqueue_failure_marks_job_failed_and_compensates_charges():
    db = AsyncMock()
    tenant_id = uuid4()

    class FailingDispatcher:
        def dispatch(self, *args, **kwargs):
            raise job_service.AIJobSubmissionUnavailableError("AI job could not be queued")

    with (
        patch.object(job_service, "create_admitted_ai_job", AsyncMock(return_value=_job())),
        patch.object(job_service, "build_ai_job_queue_metadata", AsyncMock(return_value={})),
        patch.object(job_service, "update_ai_job", AsyncMock()) as update_job,
        patch("app.core.trial_limits.reserve_ai_course_generation", AsyncMock()) as reserve,
        patch("app.core.trial_limits.release_ai_course_generation", AsyncMock()) as release,
        patch("app.modules.ai.budget.check_and_charge_llm_budget", AsyncMock()) as charge,
        patch("app.modules.ai.budget.refund_llm_budget", AsyncMock()) as refund,
        pytest.raises(job_service.AIJobSubmissionUnavailableError),
    ):
        await job_service.submit_ai_job(
            db,
            tenant_id=tenant_id,
            user_id=uuid4(),
            course_id=None,
            params={},
            task_name="generate_course",
            task_kwargs=lambda job: {"job_id": job.id},
            active_limit=2,
            worker_concurrency=2,
            historical_estimate_seconds=510,
            generation=True,
            reserve_course_generation=True,
            dispatcher=FailingDispatcher(),
        )

    reserve.assert_awaited_once_with(db, tenant_id)
    charge.assert_awaited_once_with(db, str(tenant_id), operation="generate_course")
    update_job.assert_awaited_once()
    release.assert_awaited_once_with(db, tenant_id)
    refund.assert_awaited_once_with(db, str(tenant_id), "generate_course")
    assert db.commit.await_count == 2


@pytest.mark.asyncio
async def test_submission_rejects_before_generation_reservation_or_budget_charge():
    db = AsyncMock()
    tenant_id = uuid4()
    admission_error = job_service.AIJobAdmissionLimitReachedError(
        tenant_id=tenant_id,
        active_count=2,
        active_limit=2,
    )

    with (
        patch.object(
            job_service,
            "create_admitted_ai_job",
            AsyncMock(side_effect=admission_error),
        ),
        patch("app.core.trial_limits.reserve_ai_course_generation", AsyncMock()) as reserve,
        patch("app.modules.ai.budget.check_and_charge_llm_budget", AsyncMock()) as charge,
        pytest.raises(job_service.AIJobAdmissionLimitReachedError),
    ):
        await job_service.submit_ai_job(
            db,
            tenant_id=tenant_id,
            user_id=uuid4(),
            course_id=None,
            params={},
            task_name="generate_course",
            task_kwargs=lambda job: {"job_id": job.id},
            active_limit=2,
            worker_concurrency=2,
            historical_estimate_seconds=510,
            generation=True,
            reserve_course_generation=True,
        )

    reserve.assert_not_awaited()
    charge.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_module_endpoint_maps_request_to_submission_interface():
    from app.modules.ai import router
    from app.modules.ai.schemas import AIRegenerateModuleRequest

    tenant_id, user_id, module_id, course_id = uuid4(), uuid4(), uuid4(), uuid4()
    user = SimpleNamespace(id=user_id, tenant_id=tenant_id)
    module = SimpleNamespace(id=module_id, tenant_id=tenant_id, course_id=course_id)
    db = AsyncMock()
    db.get.return_value = module
    captured = {}

    async def submit(db_arg, **kwargs):
        captured.update(kwargs)
        return _router_job(course_id), {"queue_position": 1}

    with patch.object(router, "submit_ai_job", side_effect=submit):
        await router.regenerate_module(
            module_id,
            AIRegenerateModuleRequest(guidance="Shorter", language="ru"),
            db=db,
            user=user,
        )

    assert captured["task_name"] == "regenerate_module"
    assert captured["params"] == {
        "action": "regenerate_module",
        "module_id": str(module_id),
        "guidance": "Shorter",
        "language": "ru",
    }
    assert captured["task_kwargs"](_router_job(course_id)) == {
        "job_id": "job-1",
        "module_id": str(module_id),
        "guidance": "Shorter",
        "language": "ru",
        "tenant_id": str(tenant_id),
        "user_id": str(user_id),
    }


@pytest.mark.asyncio
async def test_lesson_endpoint_maps_request_to_submission_interface():
    from app.modules.ai import router
    from app.modules.ai.schemas import AIRegenerateLessonRequest

    tenant_id, user_id = uuid4(), uuid4()
    lesson_id, module_id, course_id = uuid4(), uuid4(), uuid4()
    user = SimpleNamespace(id=user_id, tenant_id=tenant_id)
    lesson = SimpleNamespace(id=lesson_id, tenant_id=tenant_id, module_id=module_id)
    module = SimpleNamespace(id=module_id, tenant_id=tenant_id, course_id=course_id)
    db = AsyncMock()
    db.get.side_effect = [lesson, module]
    captured = {}

    async def submit(db_arg, **kwargs):
        captured.update(kwargs)
        return _router_job(course_id), {"queue_position": 1}

    with patch.object(router, "submit_ai_job", side_effect=submit):
        await router.regenerate_lesson(
            lesson_id,
            AIRegenerateLessonRequest(guidance="Add examples", regenerate_quiz=False),
            db=db,
            user=user,
        )

    assert captured["task_name"] == "regenerate_lesson"
    assert captured["params"] == {
        "action": "regenerate_lesson",
        "lesson_id": str(lesson_id),
        "guidance": "Add examples",
        "regenerate_quiz": False,
    }
    assert captured["task_kwargs"](_router_job(course_id)) == {
        "job_id": "job-1",
        "lesson_id": str(lesson_id),
        "guidance": "Add examples",
        "regenerate_quiz": False,
        "tenant_id": str(tenant_id),
        "user_id": str(user_id),
    }


@pytest.mark.asyncio
async def test_regeneration_completion_rolls_back_when_job_was_cancelled():
    from app.modules.ai.router import _finish_regeneration_job

    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(rowcount=0)

    completed = await _finish_regeneration_job(
        session,
        "job-1",
        uuid4(),
        status="completed",
        progress=100,
    )

    assert completed is False
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
