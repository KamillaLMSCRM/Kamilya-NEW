from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest


def _job(course_id):
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


@pytest.mark.asyncio
async def test_module_regeneration_is_dispatched_to_celery_with_job_task_id():
    from app.modules.ai.router import regenerate_module
    from app.modules.ai.schemas import AIRegenerateModuleRequest

    tenant_id = uuid4()
    user_id = uuid4()
    module_id = uuid4()
    course_id = uuid4()
    user = SimpleNamespace(id=user_id, tenant_id=tenant_id)
    module = SimpleNamespace(id=module_id, tenant_id=tenant_id, course_id=course_id)
    db = AsyncMock()
    db.get.return_value = module
    task = SimpleNamespace(apply_async=Mock())

    with (
        patch("app.modules.ai.router.create_admitted_ai_job", AsyncMock(return_value=_job(course_id))),
        patch(
            "app.modules.ai.router.build_ai_job_queue_metadata",
            AsyncMock(
                return_value={
                    "queue_position": 1,
                    "estimated_wait_seconds": 0,
                    "tenant_active_jobs": 1,
                    "tenant_active_limit": 2,
                }
            ),
        ),
        patch("app.modules.ai.tasks.regenerate_module_task", task),
    ):
        response = await regenerate_module(
            module_id,
            AIRegenerateModuleRequest(guidance="Shorter", language="ru"),
            db=db,
            user=user,
        )

    assert response.id == "job-1"
    task.apply_async.assert_called_once_with(
        task_id="job-1",
        kwargs={
            "job_id": "job-1",
            "module_id": str(module_id),
            "guidance": "Shorter",
            "language": "ru",
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
        },
    )


@pytest.mark.asyncio
async def test_lesson_regeneration_is_dispatched_to_celery_with_job_task_id():
    from app.modules.ai.router import regenerate_lesson
    from app.modules.ai.schemas import AIRegenerateLessonRequest

    tenant_id = uuid4()
    user_id = uuid4()
    lesson_id = uuid4()
    module_id = uuid4()
    course_id = uuid4()
    user = SimpleNamespace(id=user_id, tenant_id=tenant_id)
    lesson = SimpleNamespace(id=lesson_id, tenant_id=tenant_id, module_id=module_id)
    module = SimpleNamespace(id=module_id, tenant_id=tenant_id, course_id=course_id)
    db = AsyncMock()
    db.get.side_effect = [lesson, module]
    task = SimpleNamespace(apply_async=Mock())

    with (
        patch("app.modules.ai.router.create_admitted_ai_job", AsyncMock(return_value=_job(course_id))),
        patch(
            "app.modules.ai.router.build_ai_job_queue_metadata",
            AsyncMock(
                return_value={
                    "queue_position": 1,
                    "estimated_wait_seconds": 0,
                    "tenant_active_jobs": 1,
                    "tenant_active_limit": 2,
                }
            ),
        ),
        patch("app.modules.ai.tasks.regenerate_lesson_task", task),
    ):
        response = await regenerate_lesson(
            lesson_id,
            AIRegenerateLessonRequest(guidance="Add examples", regenerate_quiz=False),
            db=db,
            user=user,
        )

    assert response.id == "job-1"
    task.apply_async.assert_called_once_with(
        task_id="job-1",
        kwargs={
            "job_id": "job-1",
            "lesson_id": str(lesson_id),
            "guidance": "Add examples",
            "regenerate_quiz": False,
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
        },
    )


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
