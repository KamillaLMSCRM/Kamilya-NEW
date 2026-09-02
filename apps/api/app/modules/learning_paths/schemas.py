from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _validate_policy_values(values: dict[str, Any]) -> dict[str, Any]:
    certificate_mode = values.get("certificate_mode", "none")
    certificate_validity_months = values.get("certificate_validity_months")
    recurrence_mode = values.get("recurrence_mode", "none")
    recurrence_cadence_days = values.get("recurrence_cadence_days")
    recurrence_due_days = values.get("recurrence_due_days")

    if certificate_mode == "none" and certificate_validity_months is not None:
        raise ValueError("certificate_validity_months must be null when certificate_mode is none")
    if recurrence_mode == "none" and (
        recurrence_cadence_days is not None or recurrence_due_days is not None
    ):
        raise ValueError("recurrence cadence and due days must be null when recurrence_mode is none")
    if recurrence_mode == "fixed_interval_after_completion":
        if recurrence_cadence_days is None or recurrence_due_days is None:
            raise ValueError("recurrence cadence and due days are required for fixed recurrence")
        if recurrence_due_days > recurrence_cadence_days:
            raise ValueError("recurrence_due_days must not exceed recurrence_cadence_days")
    return values


class LearningPathCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    sequencing_mode: str = Field(default="linear", pattern="^(linear|open)$")
    scenario: str = Field(
        default="custom",
        pattern="^(onboarding|mandatory_training|process_update|product_certification|knowledge_refresh|custom)$",
    )
    responsible_user_id: UUID | None = None
    default_due_days: int | None = Field(default=None, ge=1, le=3650)
    certificate_mode: str = Field(default="none", pattern="^(none|final_course)$")
    certificate_validity_months: int | None = Field(default=None, ge=1, le=120)
    recurrence_mode: str = Field(default="none", pattern="^(none|fixed_interval_after_completion)$")
    recurrence_cadence_days: int | None = Field(default=None, ge=1, le=3650)
    recurrence_due_days: int | None = Field(default=None, ge=1, le=3650)

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        _validate_policy_values(self.model_dump())
        return self


class LearningPathUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    sequencing_mode: str | None = Field(default=None, pattern="^(linear|open)$")
    scenario: str | None = Field(
        default=None,
        pattern="^(onboarding|mandatory_training|process_update|product_certification|knowledge_refresh|custom)$",
    )
    responsible_user_id: UUID | None = None
    default_due_days: int | None = Field(default=None, ge=1, le=3650)
    certificate_mode: str | None = Field(default=None, pattern="^(none|final_course)$")
    certificate_validity_months: int | None = Field(default=None, ge=1, le=120)
    recurrence_mode: str | None = Field(default=None, pattern="^(none|fixed_interval_after_completion)$")
    recurrence_cadence_days: int | None = Field(default=None, ge=1, le=3650)
    recurrence_due_days: int | None = Field(default=None, ge=1, le=3650)

    @model_validator(mode="after")
    def validate_explicit_policy(self) -> Self:
        values = self.model_dump(exclude_unset=True)
        if "certificate_mode" in values and values["certificate_mode"] == "none":
            if values.get("certificate_validity_months") is not None:
                raise ValueError("certificate_validity_months must be null when certificate_mode is none")
        if "recurrence_mode" in values and values["recurrence_mode"] == "none":
            if values.get("recurrence_cadence_days") is not None or values.get("recurrence_due_days") is not None:
                raise ValueError("recurrence cadence and due days must be null when recurrence_mode is none")
        if values.get("recurrence_mode") == "fixed_interval_after_completion":
            if values.get("recurrence_cadence_days") is None or values.get("recurrence_due_days") is None:
                raise ValueError("recurrence cadence and due days are required for fixed recurrence")
            if values["recurrence_due_days"] > values["recurrence_cadence_days"]:
                raise ValueError("recurrence_due_days must not exceed recurrence_cadence_days")
        return self


class LearningPathStepInput(BaseModel):
    course_id: UUID
    required: bool = True


class LearningPathCurriculumReplace(BaseModel):
    steps: list[LearningPathStepInput] = Field(default_factory=list, max_length=100)


class LearningPathCourseItem(BaseModel):
    course_id: UUID
    title: str
    order_index: int
    required: bool


class LearningPathSummary(BaseModel):
    id: UUID
    family_id: UUID
    version: int
    title: str
    description: str
    status: str
    sequencing_mode: str
    scenario: str = "custom"
    responsible_user_id: UUID | None = None
    default_due_days: int | None = None
    certificate_mode: str = "none"
    certificate_validity_months: int | None = None
    recurrence_mode: str = "none"
    recurrence_cadence_days: int | None = None
    recurrence_due_days: int | None = None
    course_count: int
    assignment_count: int = 0
    published_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LearningPathDetail(LearningPathSummary):
    courses: list[LearningPathCourseItem]


class LearningPathAssignmentAudience(BaseModel):
    user_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    cohort_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    department_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    position_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    starts_at: datetime | None = None
    due_at: datetime | None = None


class LearningPathAssignmentResponse(BaseModel):
    id: UUID
    path_id: UUID
    user_id: UUID
    source: str
    source_ref_id: UUID | None = None
    assigned_by: UUID | None = None
    starts_at: datetime | None = None
    due_at: datetime | None = None
    status: str
    created_at: datetime
    cancelled_at: datetime | None = None
    completed_at: datetime | None = None
    user_name: str | None = None
    user_email: str | None = None

    model_config = ConfigDict(from_attributes=True)


class LearningPathAssignmentResult(BaseModel):
    added: int
    skipped: int
    total: int
    assignments: list[LearningPathAssignmentResponse]


class LearnerPathStep(BaseModel):
    course_id: UUID
    title: str
    order_index: int
    required: bool
    state: str = Field(pattern="^(locked|available|completed)$")


class LearnerPathItem(BaseModel):
    id: UUID
    assignment_id: UUID
    family_id: UUID
    version: int
    title: str
    description: str
    sequencing_mode: str
    starts_at: datetime | None = None
    due_at: datetime | None = None
    total_required_courses: int
    completed_required_courses: int
    progress_percent: int
    current_course_id: UUID | None = None
    steps: list[LearnerPathStep]
