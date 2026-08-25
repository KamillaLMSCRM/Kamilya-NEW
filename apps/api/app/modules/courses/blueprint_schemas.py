"""Public contracts for versioned industry course blueprints."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

BlueprintLocale = Literal["ru", "kk"]
BlueprintComplianceMode = Literal["lms_only", "blended", "external_certified"]


class BlueprintChecklistItemResponse(BaseModel):
    id: str
    title: str
    description: str
    required: bool = True
    answer_placeholder: str
    example_answer: str


class BlueprintLegalBasisResponse(BaseModel):
    title: str
    act_id: str
    url: str
    reviewed_at: str


class CourseBlueprintResponse(BaseModel):
    id: str
    version: str
    locale: BlueprintLocale
    title: str
    description: str
    audience: str
    estimated_ready_percent: int = 70
    customization_percent: int = 30
    module_count: int
    lesson_count: int
    quiz_question_count: int
    checklist: list[BlueprintChecklistItemResponse]
    limitations: list[str]
    compliance_mode: BlueprintComplianceMode
    applicability: str
    tags: list[str]
    legal_basis: list[BlueprintLegalBasisResponse]
    base_blueprint_id: str | None = None


class BlueprintInstantiationRequest(BaseModel):
    locale: BlueprintLocale = "ru"
    title: str | None = Field(default=None, min_length=3, max_length=255)
    answers: dict[str, str] = Field(default_factory=dict)
    source_document_ids: list[UUID] = Field(default_factory=list, max_length=20)

    @field_validator("answers")
    @classmethod
    def validate_answers(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 20:
            raise ValueError("Too many adaptation answers")
        normalized: dict[str, str] = {}
        for key, answer in value.items():
            normalized_key = key.strip()
            normalized_answer = answer.strip()
            if not normalized_key or len(normalized_key) > 80:
                raise ValueError("Invalid adaptation answer key")
            if len(normalized_answer) > 4000:
                raise ValueError("Adaptation answer is too long")
            if normalized_answer:
                normalized[normalized_key] = normalized_answer
        return normalized

    @field_validator("source_document_ids")
    @classmethod
    def deduplicate_document_ids(cls, value: list[UUID]) -> list[UUID]:
        return list(dict.fromkeys(value))


class BlueprintAdaptationRequest(BlueprintInstantiationRequest):
    locale: BlueprintLocale
    title: str | None = Field(default=None, min_length=3, max_length=255)


class BlueprintInstantiationResponse(BaseModel):
    course_id: UUID
    blueprint_id: str
    blueprint_version: str
    locale: BlueprintLocale
    readiness_percent: int
    completed_checklist_items: list[str]
    missing_checklist_items: list[str]
    edit_url: str
    adaptation_url: str


class BlueprintAlreadyInstantiatedDetail(BaseModel):
    code: Literal["blueprint_already_instantiated"] = "blueprint_already_instantiated"
    message: str
    existing_course_id: UUID


class BlueprintAdaptationSnapshot(BaseModel):
    blueprint_id: str
    blueprint_version: str
    locale: BlueprintLocale
    readiness_percent: int
    answers: dict[str, str]
    source_document_ids: list[UUID]
    completed_checklist_items: list[str]
    missing_checklist_items: list[str]

    @model_validator(mode="after")
    def readiness_range(self) -> "BlueprintAdaptationSnapshot":
        if not 0 <= self.readiness_percent <= 100:
            raise ValueError("readiness_percent must be between 0 and 100")
        return self
