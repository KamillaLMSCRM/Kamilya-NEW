"""Tenant-owned settings for the printable course-completion form."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.tenants import Tenant
from app.modules.evidence_export import (
    AssignmentEvidence,
    CourseEvidence,
    EmployeeEvidence,
    IndividualEvidenceInput,
    PrintFormEvidence,
    ProcedureEvidence,
    TenantEvidence,
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
    )
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    def to_print_form(self) -> PrintFormEvidence:
        return PrintFormEvidence.model_validate(self.model_dump())


async def get_training_evidence_form_settings(
    db: AsyncSession,
    tenant_id: UUID,
) -> TrainingEvidenceFormSettings:
    tenant = await db.get(Tenant, tenant_id)
    raw = ((tenant.settings or {}) if tenant else {}).get(_SETTINGS_KEY) or {}
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
    settings = dict(tenant.settings or {})
    settings[_SETTINGS_KEY] = normalized.model_dump()
    tenant.settings = settings
    flag_modified(tenant, "settings")
    await db.flush()
    return normalized


def render_training_evidence_form_preview(settings: TrainingEvidenceFormSettings) -> bytes:
    """Render the editable template with safe sample data using the production renderer."""

    sample = IndividualEvidenceInput(
        tenant=TenantEvidence(name=settings.organization_name),
        employee=EmployeeEvidence(full_name="Александр Сотрудников"),
        procedure=ProcedureEvidence(
            type="training",
            title="Прохождение курса",
            version="3",
            purpose="course_completion",
        ),
        course=CourseEvidence(
            title="Безопасная работа и внутренние процедуры",
            release_version=3,
        ),
        assignment=AssignmentEvidence(source="manual", assigned_at=datetime.now(UTC)),
        print_form=settings.to_print_form(),
        generated_at=datetime.now(UTC),
    )
    return render_individual_act_pdf(sample)


__all__ = [
    "TrainingEvidenceFormSettings",
    "get_training_evidence_form_settings",
    "render_training_evidence_form_preview",
    "update_training_evidence_form_settings",
]
