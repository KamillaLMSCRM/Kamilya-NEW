from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.modules.enrollments.access_service import AssignmentWindowExpiredError
from app.modules.learner_assistant import router as assistant_router
from app.modules.learner_assistant.schemas import LearnerAssistantChatRequest
from app.modules.scorm import router as scorm_router
from app.modules.scorm.schemas import ScormCommitRequest
from app.modules.surveys import router as surveys_router
from app.modules.surveys.schemas import SurveyAnswerSubmit
from app.modules.training_evidence import router as evidence_router


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


def test_scorm_launch_token_carries_current_enrollment(monkeypatch):
    enrollment_id = uuid4()
    captured = {}

    def create_token(payload, **kwargs):
        captured.update(payload)
        return "token"

    monkeypatch.setattr(scorm_router, "create_scoped_token", create_token)
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), assignment_access_enrollment_id=None)
    package = SimpleNamespace(id=uuid4(), course_id=uuid4())

    assert scorm_router._make_launch_token(user, package, enrollment_id=enrollment_id) == "token"
    assert captured["enrollment_id"] == str(enrollment_id)


def test_survey_enrollment_migration_preserves_legacy_rows_and_enforces_scope():
    source = Path("alembic/versions/0118_survey_response_enrollment_scope.py").read_text(encoding="utf-8")

    assert 'down_revision = "0117"' in source
    assert "fk_survey_responses_enrollment_id" in source
    assert "uq_survey_response_legacy_user" in source
    assert "uq_survey_response_enrollment" in source
    assert "validate_survey_response_enrollment_scope" in source
    separate_trigger_statement = (
        "$$ LANGUAGE plpgsql;\n        \"\"\"\n    )\n"
        "    op.execute(\n        \"\"\"\n        CREATE TRIGGER"
    )
    assert separate_trigger_statement in source
    assert "e.status = 'completed'" in source
    assert "0118 downgrade refused" in source


@pytest.mark.asyncio
async def test_impersonation_cannot_append_immutable_signed_scan(monkeypatch):
    append = AsyncMock()
    monkeypatch.setattr(evidence_router, "append_signed_scan", append)

    with pytest.raises(HTTPException) as exc_info:
        await evidence_router.attach_returned_signed_scan(
            uuid4(),
            file=SimpleNamespace(),
            db=SimpleNamespace(),
            user=SimpleNamespace(id=uuid4(), tenant_id=uuid4(), is_impersonating=True),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "impersonation_cannot_append_evidence"
    append.assert_not_awaited()


@pytest.mark.asyncio
async def test_scorm_commit_rejects_attempt_from_another_package(monkeypatch):
    tenant_id = uuid4()
    user_id = uuid4()
    enrollment_id = uuid4()
    token_package_id = uuid4()
    attempt = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        enrollment_id=enrollment_id,
        package_id=uuid4(),
        course_id=uuid4(),
        cmi_json={},
        lesson_status=None,
        score_raw=None,
        lesson_location=None,
        total_time=None,
        suspend_data=None,
        completed_at=None,
    )
    payload = {
        "tenant_id": str(tenant_id),
        "sub": str(user_id),
        "package_id": str(token_package_id),
        "course_id": str(attempt.course_id),
    }
    db = SimpleNamespace(execute=AsyncMock(), get=AsyncMock(return_value=attempt), commit=AsyncMock())
    monkeypatch.setattr(scorm_router, "_decode_launch_token", lambda token: payload)
    monkeypatch.setattr(
        scorm_router,
        "_require_scorm_token_enrollment",
        AsyncMock(return_value=enrollment_id),
    )

    with pytest.raises(HTTPException) as exc_info:
        await scorm_router.commit_scorm_attempt(
            str(attempt.id),
            ScormCommitRequest(cmi={"cmi.core.lesson_status": "incomplete"}),
            Request(
                {
                    "type": "http",
                    "method": "POST",
                    "scheme": "http",
                    "path": "/api/v1/scorm/attempts/test/commit",
                    "raw_path": b"/api/v1/scorm/attempts/test/commit",
                    "query_string": b"",
                    "headers": [(b"host", b"testserver")],
                    "server": ("testserver", 80),
                    "client": ("127.0.0.1", 50000),
                }
            ),
            token="signed-package-a-token",
            db=db,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "SCORM token does not match attempt"
    db.execute.assert_awaited_once()
    assert db.execute.await_args.args[1] == {"tid": str(tenant_id)}
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_scorm_attempt_without_enrollment_cannot_complete():
    db = SimpleNamespace(get=AsyncMock())
    attempt = SimpleNamespace(enrollment_id=None)

    with pytest.raises(HTTPException) as exc_info:
        await scorm_router._complete_from_scorm(db, attempt, str(uuid4()))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "legacy_scorm_attempt_not_bound"
    db.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_assignment_cannot_create_learner_assistant_messages(monkeypatch):
    tenant_id = uuid4()
    user_id = uuid4()
    course_id = uuid4()
    enrollment_id = uuid4()
    user = SimpleNamespace(
        id=user_id,
        tenant_id=tenant_id,
        assignment_access_enrollment_id=enrollment_id,
    )
    db = SimpleNamespace(add=lambda item: None, commit=AsyncMock())
    monkeypatch.setattr(
        assistant_router,
        "_assert_course_access",
        AsyncMock(return_value=SimpleNamespace(id=course_id, title="Курс", description="")),
    )
    monkeypatch.setattr(
        assistant_router,
        "require_active_enrollment_window",
        AsyncMock(
            side_effect=AssignmentWindowExpiredError(
                "assignment_enrollment_not_active",
                datetime.now(UTC),
            )
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await assistant_router.learner_chat(
            LearnerAssistantChatRequest(course_id=course_id, message="Можно задать вопрос после завершения?"),
            db=db,
            user=user,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "assignment_enrollment_not_active"
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_survey_feedback_is_recorded_per_completed_enrollment():
    tenant_id = uuid4()
    user_id = uuid4()
    course_id = uuid4()
    survey_id = uuid4()
    question_id = "usefulness"
    survey = SimpleNamespace(
        id=survey_id,
        tenant_id=tenant_id,
        course_id=course_id,
        status="published",
        questions=[{"id": question_id}],
    )
    user = SimpleNamespace(id=user_id, tenant_id=tenant_id, assignment_access_enrollment_id=None)
    created_responses = []

    async def submit_for(enrollment_id):
        db = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    _ScalarResult(survey),
                    _ScalarResult(enrollment_id),
                    _ScalarResult(None),
                ]
            ),
            add=created_responses.append,
            commit=AsyncMock(),
        )
        result = await surveys_router.submit_response(
            survey_id,
            SurveyAnswerSubmit(answers={question_id: 5}),
            db=db,
            user=user,
        )
        assert result == {"submitted": True}

    first_enrollment_id = uuid4()
    second_enrollment_id = uuid4()
    await submit_for(first_enrollment_id)
    await submit_for(second_enrollment_id)

    assert [response.enrollment_id for response in created_responses] == [
        first_enrollment_id,
        second_enrollment_id,
    ]


@pytest.mark.asyncio
async def test_assignment_survey_does_not_treat_legacy_unscoped_feedback_as_submitted():
    tenant_id = uuid4()
    user_id = uuid4()
    course_id = uuid4()
    survey_id = uuid4()
    enrollment_id = uuid4()
    survey = SimpleNamespace(
        id=survey_id,
        tenant_id=tenant_id,
        course_id=course_id,
        status="published",
        questions=[{"id": "usefulness"}],
    )
    user = SimpleNamespace(
        id=user_id,
        tenant_id=tenant_id,
        assignment_access_enrollment_id=enrollment_id,
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _ScalarResult(survey),
                _ScalarResult(enrollment_id),
                _ScalarResult(None),
            ]
        ),
        add=lambda item: None,
        commit=AsyncMock(),
    )

    await surveys_router.submit_response(
        survey_id,
        SurveyAnswerSubmit(answers={"usefulness": 5}),
        db=db,
        user=user,
    )

    existing_response_query = str(db.execute.await_args_list[2].args[0])
    assert "survey_responses.enrollment_id IS NULL" not in existing_response_query
