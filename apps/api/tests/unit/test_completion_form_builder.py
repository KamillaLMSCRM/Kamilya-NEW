"""Field selection must not change evidence or misrepresent missing test results."""

import io
from datetime import UTC, datetime
from typing import get_args

import pytest
from pydantic import ValidationError
from pypdf import PdfReader

from app.modules.evidence_export import (
    AttemptEvidence,
    CourseEvidence,
    EmployeeEvidence,
    IndividualEvidenceInput,
    ProcedureEvidence,
    TenantEvidence,
    render_completion_form_pdf,
    render_individual_act_pdf,
)
from app.modules.evidence_export.form_fields import (
    DEFAULT_FORM_FIELDS,
    FORM_FIELD_CATALOG,
    REQUIRED_FORM_FIELDS,
    CompletionFormField,
)
from app.modules.training_evidence.form_settings import (
    TrainingEvidenceFormSettings,
    render_training_evidence_form_preview,
)


@pytest.mark.asyncio
async def test_completion_workflow_snapshots_selection_independently(monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4

    from app.modules.training_evidence import workflow

    tenant_id, user_id, course_id, enrollment_id, release_id = [uuid4() for _ in range(5)]
    settings = TrainingEvidenceFormSettings(
        selected_fields=["employee_name", "course_title", "test_results", "test_title"]
    )
    captured = {}

    class Database:
        async def scalar(self, _query):
            return SimpleNamespace(id=release_id, version=3, snapshot_sha256="a" * 64)

    async def get_settings(*_args):
        return settings

    async def record(*_args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr(workflow, "get_training_evidence_form_settings", get_settings)
    monkeypatch.setattr(workflow, "record_event", record)
    await workflow.record_course_completion(
        Database(),
        user=SimpleNamespace(id=user_id, tenant_id=tenant_id),
        course=SimpleNamespace(id=course_id, tenant_id=tenant_id, current_release_id=release_id, title="QA Course"),
        enrollment=SimpleNamespace(
            id=enrollment_id, tenant_id=tenant_id, user_id=user_id, course_id=course_id, content_release_id=release_id
        ),
        certificate=SimpleNamespace(
            id=uuid4(), tenant_id=tenant_id, user_id=user_id, course_id=course_id, certificate_number="QA001"
        ),
    )
    settings.selected_fields.append("position")
    assert captured["tenant_id"] == tenant_id
    assert captured["payload_snapshot"]["print_form"]["selected_fields"] == [
        "employee_name",
        "course_title",
        "test_results",
        "test_title",
    ]


def _text(content):
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)


def _sample(fields=None, *, attempts=None):
    settings = TrainingEvidenceFormSettings(
        selected_fields=fields if fields is not None else list(REQUIRED_FORM_FIELDS),
        organization_name="ТОО Учебная компания",
        representative_name="Представитель QA",
        confirmation_text="Текст для подписи, а не электронная подпись.",
        footer_note="Примечание QA",
    )
    return IndividualEvidenceInput(
        tenant=TenantEvidence(name="Tenant"),
        employee=EmployeeEvidence(
            full_name="Айжан Сотрудникова",
            personnel_number="QA-001",
            department="Учебный отдел",
            position="Специалист",
            email="do-not-print@example.com",
            phone="do-not-print-phone",
        ),
        procedure=ProcedureEvidence(type="training", title="Прохождение курса"),
        course=CourseEvidence(title="Рабочие процедуры", release_version=3),
        attempts=attempts
        if attempts is not None
        else [
            AttemptEvidence(quiz_title="Тест рабочих процедур", score_percent=0, threshold_percent=80, passed=False),
            AttemptEvidence(quiz_title="Тест рабочих процедур", score_percent=90, threshold_percent=80, passed=True),
        ],
        print_form=settings.to_print_form(),
        generated_at=datetime(2026, 10, 18, 7, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    "fields",
    [
        [],
        ["employee_name", "course_title", "position"],
        ["employee_name", "course_title", "test_results", "unknown"],
        ["employee_name", "course_title", "test_results", "employee_name"],
    ],
)
def test_invalid_selections_are_rejected(fields):
    with pytest.raises(ValidationError):
        TrainingEvidenceFormSettings(selected_fields=fields)


def test_catalog_matches_validation_and_defaults():
    ids = [item[0] for item in FORM_FIELD_CATALOG]
    assert len(ids) == len(set(ids)) == 20
    assert set(ids) == set(get_args(CompletionFormField))
    assert REQUIRED_FORM_FIELDS.issubset(DEFAULT_FORM_FIELDS)
    assert set(DEFAULT_FORM_FIELDS).issubset(ids)


def test_minimal_form_excludes_optional_fields_but_never_hides_failed_attempt():
    pdf = render_completion_form_pdf(_sample())
    text = _text(pdf)
    assert "Айжан Сотрудникова" in text and "Рабочие процедуры" in text
    assert "Итог (попытка 1): Не пройдено" in text
    assert "Итог (попытка 2): Пройдено" in text
    for excluded in (
        "QA-001",
        "Учебный отдел",
        "Специалист",
        "90%",
        "Дата формирования:",
        "Текст для подписи",
        "Представитель QA",
        "Примечание QA",
        "Тест рабочих процедур",
        "do-not-print",
        "Акт результата обучения",
    ):
        assert excluded not in text
    assert len(PdfReader(io.BytesIO(pdf)).pages) == 1


def test_all_fields_render_zero_scores_and_current_profile_note():
    text = _text(render_completion_form_pdf(_sample([item[0] for item in FORM_FIELD_CATALOG])))
    for expected in (
        "QA-001",
        "Учебный отдел",
        "Специалист",
        "0%",
        "90%",
        "80%",
        "Нет данных",
        "на момент выгрузки",
        "Представитель QA",
        "Примечание QA",
        "Тест рабочих процедур",
    ):
        assert expected in text
    assert "do-not-print" not in text


@pytest.mark.parametrize(
    "attempts, expected", [([], "прохождение теста не подтверждено"), ([AttemptEvidence()], "Не подтверждено")]
)
def test_missing_outcome_is_not_a_pass(attempts, expected):
    assert expected in _text(render_completion_form_pdf(_sample(attempts=attempts)))


def test_selection_roundtrip_and_legacy_serialization():
    legacy = TrainingEvidenceFormSettings().to_print_form()
    assert legacy.selected_fields is None
    assert "selected_fields" not in legacy.model_dump(exclude_none=True)
    configured = _sample().print_form
    assert configured is not None
    assert type(configured).model_validate(configured.model_dump()).selected_fields == configured.selected_fields


def test_full_audit_remains_complete_and_public_omits_custom_form():
    data = _sample()
    private_text = _text(render_individual_act_pdf(data))
    assert "Акт результата обучения" in private_text
    assert "QA-001" in private_text and "90%" in private_text
    public_text = _text(render_individual_act_pdf(data, public=True))
    assert data.print_form.title not in public_text
    assert "do-not-print" not in public_text


def test_preview_is_the_selected_form_not_full_unfiltered_audit():
    text = _text(
        render_training_evidence_form_preview(TrainingEvidenceFormSettings(selected_fields=list(REQUIRED_FORM_FIELDS)))
    )
    assert "Акт результата обучения" not in text
    assert "Александр Сотрудников" in text
    assert "60%" not in text and "90%" not in text


def test_field_order_is_respected():
    text = _text(render_completion_form_pdf(_sample(["course_title", "employee_name", "test_results"])))
    assert text.index("Курс:") < text.index("Сотрудник:") < text.index("Итог (попытка 1)")


def test_renderer_rejects_unconfigured_or_wrong_procedure():
    data = _sample()
    with pytest.raises(ValueError):
        render_completion_form_pdf(data.model_copy(update={"print_form": None}))
    with pytest.raises(ValueError):
        render_completion_form_pdf(
            data.model_copy(update={"procedure": ProcedureEvidence(type="attestation", title="Other")})
        )


@pytest.mark.parametrize("field", ["organization_name", "title", "confirmation_text", "employee_signature_label"])
def test_whitespace_is_not_a_required_text_value(field):
    with pytest.raises(ValidationError):
        TrainingEvidenceFormSettings.model_validate({field: "   "})
