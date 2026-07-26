"""API DTOs for the position qualification card."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QualificationProfile(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    department: str | None = None
    level: str
    responsibilities: str
    requirements: str
    employee_count: int
    current_employee_count: int
    created_at: datetime | None = None


class QualificationInstruction(BaseModel):
    document_id: UUID
    filename: str
    index_status: str
    index_error_code: str | None = None
    updated_at: datetime | None = None
    version: int


class QualificationCompetency(BaseModel):
    id: UUID
    name: str
    description: str
    required_level: int
    course_ids: list[UUID]


class CourseRule(BaseModel):
    course_id: UUID
    title: str
    status: str
    required: bool
    source: str


class EffectiveCourse(BaseModel):
    course_id: UUID
    title: str
    status: str
    required: bool
    sources: list[str]


class QualificationTraining(BaseModel):
    position_courses: list[CourseRule]
    department_courses: list[CourseRule]
    competency_courses: list[CourseRule]
    effective_courses: list[EffectiveCourse]


class QualificationOnboardingQuiz(BaseModel):
    id: UUID
    title: str
    pass_score: int
    time_limit: int | None = None
    is_active: bool
    question_count: int
    questions: list[dict[str, Any]]
    updated_at: datetime | None = None


class QualificationEmployees(BaseModel):
    active_count: int


class QualificationHistoryItem(BaseModel):
    id: UUID
    version_no: int
    change_kind: str
    change_reason: str | None = None
    created_by: UUID | None = None
    created_at: datetime


class QualificationHistoryResponse(BaseModel):
    items: list[QualificationHistoryItem]


class PositionQualificationCard(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    profile: QualificationProfile
    instruction: QualificationInstruction | None
    competencies: list[QualificationCompetency]
    training: QualificationTraining
    onboarding_quiz: QualificationOnboardingQuiz | None
    employees: QualificationEmployees
    latest_version: int | None
    history_count: int


class QualificationProfilePatch(BaseModel):
    name: str | None = None
    department: str | None = None
    level: str | None = None
    responsibilities: str | None = None
    requirements: str | None = None
    change_reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_profile_change(self) -> "QualificationProfilePatch":
        if not any(
            getattr(self, field) is not None
            for field in ("name", "department", "level", "responsibilities", "requirements")
        ):
            raise ValueError("At least one profile field is required")
        return self


class QualificationCompetencyItem(BaseModel):
    competency_id: UUID
    required_level: int = Field(ge=1, le=5)


class QualificationCompetenciesPut(BaseModel):
    items: list[QualificationCompetencyItem] = Field(default_factory=list)
    change_reason: str | None = Field(default=None, max_length=1000)


class QualificationTrainingItem(BaseModel):
    course_id: UUID
    required: bool = True


class QualificationTrainingPut(BaseModel):
    items: list[QualificationTrainingItem] = Field(default_factory=list)
    change_reason: str | None = Field(default=None, max_length=1000)


class QualificationRestoreRequest(BaseModel):
    change_reason: str | None = Field(default=None, max_length=1000)
