"""Tenant-owned settings for the printable course-completion form."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from pydantic import Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.tenants import Tenant
from app.modules.evidence_export import (
    AssignmentEvidence,
    AttemptEvidence,
    CourseEvidence,
    EmployeeEvidence,
    IndividualEvidenceInput,
    PrintFormEvidence,
    ProcedureEvidence,
    TenantEvidence,
    render_completion_form_pdf,
    render_individual_act_pdf,
)

_SETTINGS_KEY = "training_evidence_form_settings"


class TrainingEvidenceFormSettings(PrintFormEvidence):
    """Editable tenant template that is snapshotted at course completion."""

    organization_name: str = Field(default="Kamilya LMS", min_length=1, max_length=160)
    title: str = Field(default="Подтверждение прохождения курса", min_length=1, max_length=160)
    intro_text: str = Field(
        default="Документ подтверждает завершение сотрудником опубликованной версии курса.",
        max_length=1000,
    )
    confirmation_text: str = Field(
        default=(
            "Я подтверждаю, что завершил(а) указанный курс, ознакомился(лась) с его материалами "
            "и самостоятельно прошел(ла) обязательное тестирование."
        ),
        min_length=1,
        max_length=1500,
    )
    employee_signature_label: str = Field(default="Подпись сотрудника", min_length=1, max_length=120)
    employee_date_label: str = Field(default="Дата", min_length=1, max_length=120)
    representative_signature_label: str = Field(
        default="Подпись представителя работодателя", min_length=1, max_length=120
    )
    representative_date_label: str = Field(default="Дата проверки", min_length=1, max_length=120)
    quiz_title: str = Field(default="Результат отдельного теста", min_length=1, max_length=160)
    quiz_intro_text: str = Field(
        default="Документ фиксирует результат отдельного теста и не подтверждает завершение курса.", max_length=1000
    )
    quiz_confirmation_text: str = Field(
        default="Подтверждаю самостоятельное выполнение указанного теста. Результат приведён в документе.",
        min_length=1,
        max_length=1500,
    )

    @field_validator(
        "organization_name",
        "title",
        "intro_text",
        "confirmation_text",
        "employee_signature_label",
        "employee_date_label",
        "representative_signature_label",
        "representative_date_label",
        "representative_name",
        "representative_title",
        "footer_note",
        "quiz_title",
        "quiz_intro_text",
        "quiz_confirmation_text",
        mode="before",
    )
    @classmethod
    def strip_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    def to_print_form(self, *, for_quiz: bool = False) -> PrintFormEvidence:
        data = self.model_dump(exclude={"quiz_title", "quiz_intro_text", "quiz_confirmation_text"})
        if for_quiz:
            data.update(
                title=self.quiz_title, intro_text=self.quiz_intro_text, confirmation_text=self.quiz_confirmation_text
            )
        return PrintFormEvidence.model_validate(data)


async def get_training_evidence_form_settings(
    db: AsyncSession,
    tenant_id: UUID,
) -> TrainingEvidenceFormSettings:
    tenant = await db.get(Tenant, tenant_id)
    tenant_settings = cast(dict[str, Any], tenant.settings or {}) if tenant else {}
    raw = tenant_settings.get(_SETTINGS_KEY) or {}
    if tenant and not raw:
        raw = {"organization_name": tenant.name}
    return TrainingEvidenceFormSettings.model_validate(raw)


async def update_training_evidence_form_settings(
    db: AsyncSession,
    tenant_id: UUID,
    payload: TrainingEvidenceFormSettings,
) -> TrainingEvidenceFormSettings:
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise ValueError("Tenant not found")
    normalized = TrainingEvidenceFormSettings.model_validate(payload.model_dump())
    settings = dict(cast(dict[str, Any], tenant.settings or {}))
    settings[_SETTINGS_KEY] = normalized.model_dump()
    runtime_tenant = cast(Any, tenant)
    runtime_tenant.settings = settings
    flag_modified(tenant, "settings")
    await db.flush()
    return normalized


def render_training_evidence_form_preview(settings: TrainingEvidenceFormSettings, *, for_quiz: bool = False) -> bytes:
    """Render the editable template with safe sample data using the production renderer."""

    sample = IndividualEvidenceInput(
        tenant=TenantEvidence(name=settings.organization_name),
        employee=EmployeeEvidence(
            full_name="Александр Сотрудников",
            personnel_number="QA-001",
            department="Учебный отдел",
            position="Специалист",
        ),
        procedure=ProcedureEvidence(
            type="knowledge_check" if for_quiz else "training",
            title="Итоговый тест по внутренним процедурам" if for_quiz else "Прохождение курса",
            version="3",
            purpose="course_completion",
        ),
        course=CourseEvidence(
            title="Безопасная работа и внутренние процедуры",
            release_version=3,
        ),
        assignment=AssignmentEvidence(source="manual", assigned_at=datetime.now(UTC), due_at=datetime.now(UTC)),
        attempts=[
            AttemptEvidence(
                quiz_title="Итоговый тест по внутренним процедурам",
                score_percent=60,
                threshold_percent=80,
                passed=False,
                completed_at=datetime.now(UTC),
                time_spent_seconds=180,
            ),
            AttemptEvidence(
                quiz_title="Итоговый тест по внутренним процедурам",
                score_percent=90,
                threshold_percent=80,
                passed=True,
                completed_at=datetime.now(UTC),
                time_spent_seconds=240,
            ),
        ]
        if settings.selected_fields is not None
        else [],
        print_form=settings.to_print_form(for_quiz=for_quiz),
        generated_at=datetime.now(UTC),
    )
    if for_quiz:
        sample = sample.model_copy(
            update={
                "attempts": [sample.attempts[-1].model_copy(update={"id": "QA-preview-attempt"})]
                if sample.attempts
                else []
            }
        )
    return (
        render_completion_form_pdf(sample)
        if settings.selected_fields is not None
        else render_individual_act_pdf(sample)
    )


__all__ = [
    "TrainingEvidenceFormSettings",
    "get_training_evidence_form_settings",
    "render_training_evidence_form_preview",
    "update_training_evidence_form_settings",
]
