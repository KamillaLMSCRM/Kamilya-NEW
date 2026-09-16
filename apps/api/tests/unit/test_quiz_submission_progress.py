from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from starlette.requests import Request

from app.modules.quizzes import assignment_service, router
from app.modules.quizzes.schemas import QuizSubmission


@pytest.mark.asyncio
async def test_passed_quiz_persists_lesson_before_returning_success(monkeypatch):
    tenant_id, user_id, quiz_id, lesson_id = (uuid4() for _ in range(4))
    attempt = SimpleNamespace(
        id=uuid4(),
        quiz_id=quiz_id,
        user_id=user_id,
        enrollment_id=uuid4(),
        content_release_id=uuid4(),
        score_percent=100,
        total_points=1,
        earned_points=1,
        passed=True,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        time_spent_seconds=15,
        evidence_sha256="a" * 64,
    )
    quiz = SimpleNamespace(id=quiz_id, lesson_id=lesson_id)
    evidence_event = SimpleNamespace(id=uuid4())
    user = SimpleNamespace(id=user_id, tenant_id=tenant_id)
    db = SimpleNamespace()
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})

    require_access = AsyncMock(return_value=quiz)
    grade = AsyncMock(return_value={"attempt": attempt, "passed": True, "message": "ok"})
    persist_progress = AsyncMock(return_value={"completed": True})
    update_assignment = AsyncMock()
    record_evidence = AsyncMock(return_value=evidence_event)
    audit = AsyncMock()

    monkeypatch.setattr(router, "_require_quiz_access", require_access)
    monkeypatch.setattr(router, "grade_quiz", grade)
    monkeypatch.setattr(assignment_service, "update_assignment_status", update_assignment)

    from app.modules.audit import service as audit_service
    from app.modules.progress import service as progress_service
    from app.modules.training_evidence import workflow

    monkeypatch.setattr(progress_service, "update_lesson_progress", persist_progress)
    monkeypatch.setattr(workflow, "record_quiz_submission", record_evidence)
    monkeypatch.setattr(audit_service, "log_action", audit)

    response = await router.submit_quiz(
        quiz_id=quiz_id,
        req=QuizSubmission(answers=[], time_spent_seconds=15),
        request=request,
        db=db,  # type: ignore[arg-type]
        user=user,
    )

    assert response.passed is True
    persist_progress.assert_awaited_once_with(
        db,
        user_id,
        lesson_id,
        tenant_id,
        completed=True,
    )
