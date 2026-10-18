"""A separate-test document is bound to one persisted attempt, never a whole course."""

import io
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pypdf import PdfReader

from app.modules.courses.release_service import canonical_json_sha256
from app.modules.evidence_export import (
    AttemptEvidence,
    CourseEvidence,
    EmployeeEvidence,
    IndividualEvidenceInput,
    ProcedureEvidence,
    TenantEvidence,
    render_completion_form_pdf,
)
from app.modules.training_evidence import export_router, export_service, workflow
from app.modules.training_evidence.form_settings import (
    TrainingEvidenceFormSettings,
    render_training_evidence_form_preview,
)


def _settings():
    return TrainingEvidenceFormSettings(selected_fields=["employee_name", "course_title", "test_results", "test_score"])


def _text(pdf):
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)


def test_quiz_text_is_separate_from_course_and_preview_is_honest():
    settings = _settings()
    snapshot = settings.to_print_form(for_quiz=True)
    assert snapshot.title == settings.quiz_title
    assert snapshot.intro_text == settings.quiz_intro_text
    assert "quiz_title" not in snapshot.model_dump()
    text = _text(render_training_evidence_form_preview(settings, for_quiz=True))
    assert "Результат отдельного теста" in text
    assert "Итоговый тест по внутренним процедурам" in text
    assert "QA-preview-attempt" in text
    assert "Завершение всего курса этим документом не подтверждается" in " ".join(text.split())


@pytest.mark.parametrize("passed", [False, True])
def test_quiz_document_identifies_attempt_even_with_minimal_fields(passed):
    data = IndividualEvidenceInput(
        tenant=TenantEvidence(name="QA"),
        employee=EmployeeEvidence(full_name="QA Learner"),
        course=CourseEvidence(title="QA Course"),
        procedure=ProcedureEvidence(type="knowledge_check", title="Exact test"),
        attempts=[AttemptEvidence(id="exact-attempt", passed=passed, score_percent=100 if passed else 0)],
        print_form=_settings().to_print_form(for_quiz=True),
    )
    text = _text(render_completion_form_pdf(data))
    assert "Exact test" in text and "exact-attempt" in text
    assert ("Итог (попытка 1): Пройдено" if passed else "Итог (попытка 1): Не пройдено") in text
    with pytest.raises(ValueError):
        render_completion_form_pdf(data.model_copy(update={"attempts": data.attempts * 2}))


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [False, True])
async def test_submission_snapshots_quiz_template_only_when_configured(monkeypatch, configured):
    tenant_id, learner_id, enrollment_id, release_id, quiz_id, attempt_id = [uuid4() for _ in range(6)]
    snapshot = {
        "attempt": {
            "id": str(attempt_id),
            "tenant_id": str(tenant_id),
            "user_id": str(learner_id),
            "enrollment_id": str(enrollment_id),
            "content_release_id": str(release_id),
            "content_release_sha256": "a" * 64,
        }
    }
    attempt = SimpleNamespace(
        id=attempt_id,
        tenant_id=tenant_id,
        user_id=learner_id,
        enrollment_id=enrollment_id,
        content_release_id=release_id,
        quiz_id=quiz_id,
        evidence_snapshot=snapshot,
        evidence_sha256=canonical_json_sha256(snapshot),
        score_percent=0,
        passed=False,
    )
    settings = _settings() if configured else TrainingEvidenceFormSettings()
    captured = {}

    class Database:
        def __init__(self):
            self.rows = iter(
                [SimpleNamespace(snapshot_sha256="a" * 64, version=3), SimpleNamespace(title="Exact quiz"), None]
            )

        async def scalar(self, _query):
            return next(self.rows)

    async def get_settings(*_args):
        return settings

    async def record(*_args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr(workflow, "get_training_evidence_form_settings", get_settings)
    monkeypatch.setattr(workflow, "record_event", record)
    await workflow.record_quiz_submission(
        Database(), user=SimpleNamespace(id=learner_id, tenant_id=tenant_id), attempt=attempt
    )
    payload = captured["payload_snapshot"]
    assert ("print_form" in payload) is configured
    assert payload["passed"] is False
    if configured:
        assert payload["print_form"]["title"] == settings.quiz_title
        assert export_service._configured_quiz_binding(
            SimpleNamespace(id=uuid4(), procedure_type="knowledge_check", payload_snapshot=payload)
        ) == (attempt_id, quiz_id, attempt.evidence_sha256)
        settings.selected_fields.append("department")
        assert "department" not in payload["print_form"]["selected_fields"]
        existing = SimpleNamespace(
            id=uuid4(),
            user_id=learner_id,
            enrollment_id=enrollment_id,
            content_release_id=release_id,
            procedure_type="knowledge_check",
            record_type="original",
            payload_snapshot=payload,
            payload_sha256=workflow.evidence_payload_sha256(payload),
        )
        retry_db = Database()
        retry_db.rows = iter(
            [SimpleNamespace(snapshot_sha256="a" * 64, version=3), SimpleNamespace(title="Renamed quiz"), existing]
        )

        async def settings_must_not_be_loaded(*_args):
            raise AssertionError("retry must use original snapshot, not current template")

        monkeypatch.setattr(workflow, "get_training_evidence_form_settings", settings_must_not_be_loaded)
        repeated = await workflow.record_quiz_submission(
            retry_db, user=SimpleNamespace(id=learner_id, tenant_id=tenant_id), attempt=attempt
        )
        assert repeated is existing


@pytest.mark.parametrize("bad_key", ["attempt_id", "quiz_id", "evidence_sha256"])
def test_bad_quiz_binding_refuses_export(bad_key):
    payload = {
        "source": "quiz_attempt",
        "print_form": _settings().to_print_form().model_dump(),
        "quiz_id": str(uuid4()),
        "attempt_evidence": {"attempt_id": str(uuid4()), "evidence_sha256": "a" * 64},
    }
    if bad_key == "quiz_id":
        payload[bad_key] = "invalid"
    else:
        payload["attempt_evidence"][bad_key] = "invalid"
    with pytest.raises(HTTPException) as exc:
        export_service._configured_quiz_binding(
            SimpleNamespace(id=uuid4(), procedure_type="knowledge_check", payload_snapshot=payload)
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [False, True])
async def test_attempt_route_refuses_missing_or_historical_template(missing):
    class Database:
        async def scalar(self, _query):
            return None if missing else SimpleNamespace(payload_snapshot={})

    with pytest.raises(HTTPException) as exc:
        await export_router.export_my_quiz_attempt(
            uuid4(), db=Database(), tenant_user=SimpleNamespace(tenant_id=uuid4()), user=SimpleNamespace(id=uuid4())
        )
    assert exc.value.status_code == (404 if missing else 409)


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [False, True])
async def test_scoped_assignment_denial_precedes_template_availability(configured):
    class Database:
        async def scalar(self, _query):
            return SimpleNamespace(
                enrollment_id=uuid4(),
                payload_snapshot={"print_form": _settings().to_print_form(for_quiz=True).model_dump()}
                if configured
                else {},
            )

    with pytest.raises(HTTPException) as exc:
        await export_router.export_my_quiz_attempt(
            uuid4(),
            db=Database(),
            tenant_user=SimpleNamespace(tenant_id=uuid4()),
            user=SimpleNamespace(id=uuid4(), assignment_access_enrollment_id=uuid4()),
        )
    assert exc.value.status_code == 404
