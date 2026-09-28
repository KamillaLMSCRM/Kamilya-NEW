from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

ActualityState = Literal["unassigned", "current", "due_soon", "overdue"]
ChangeReviewStatus = Literal["pending", "processing", "ready", "resolved", "failed"]
ChangeDecision = Literal[
    "no_learning_impact",
    "update_future",
    "update_and_retrain",
    "suspend_old_assignments",
]


def _is_aware(value: datetime | None) -> bool:
    return value is None or (value.tzinfo is not None and value.utcoffset() is not None)


class SourcePolicyUpdate(BaseModel):
    owner_id: UUID | None = None
    reviewed_at: datetime | None = None
    next_review_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_review_window(self) -> Self:
        if not _is_aware(self.reviewed_at) or not _is_aware(self.next_review_at):
            raise ValueError("review timestamps must include a timezone")
        if self.reviewed_at and self.next_review_at and self.next_review_at < self.reviewed_at:
            raise ValueError("next_review_at cannot precede reviewed_at")
        return self


class SourcePolicyRecord(SourcePolicyUpdate):
    id: UUID
    tenant_id: UUID
    source_family_id: UUID
    actuality_state: ActualityState
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ImpactedCourse(BaseModel):
    course_id: UUID
    title: str
    status: str
    impacted_lesson_ids: list[UUID] = Field(default_factory=list)
    assessment_questions_requiring_review: int = Field(ge=0)
    active_enrollments: int = Field(ge=0)
    completed_enrollments: int = Field(ge=0)
    assessment_scope: Literal["impacted_lessons"] = "impacted_lessons"


class FactChange(BaseModel):
    change_kind: Literal["added", "removed", "metadata_changed"]
    subject: str
    attribute: str
    old_value: str | None = None
    new_value: str | None = None
    old_locator: str | None = None
    new_locator: str | None = None
    old_confidence: float | None = None
    new_confidence: float | None = None
    old_uncertainty: str | None = None
    new_uncertainty: str | None = None


class SourceChangeReviewRecord(BaseModel):
    id: UUID
    tenant_id: UUID
    source_family_id: UUID
    previous_document_id: UUID
    new_document_id: UUID
    status: ChangeReviewStatus
    added_fact_count: int = Field(ge=0)
    removed_fact_count: int = Field(ge=0)
    changed_fact_count: int = Field(ge=0)
    unchanged_fact_count: int = Field(ge=0)
    impacted_course_count: int = Field(ge=0)
    impacted_lesson_count: int = Field(ge=0)
    assessment_questions_requiring_review: int = Field(ge=0)
    impacted_courses: list[ImpactedCourse] = Field(default_factory=list)
    added_facts: list[FactChange] = Field(default_factory=list)
    removed_facts: list[FactChange] = Field(default_factory=list)
    changed_facts: list[FactChange] = Field(default_factory=list)
    analysis_truncated: bool = False
    analysis_error_code: str | None = None
    analysis_error_message: str | None = None
    decision: ChangeDecision | None = None
    decision_reason: str | None = None
    decision_snapshot: dict[str, Any] | None = None
    decided_by: UUID | None = None
    decided_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SourceChangeDecisionRequest(BaseModel):
    decision: ChangeDecision
    reason: str = Field(min_length=20, max_length=4000)
    retraining_due_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if not _is_aware(self.retraining_due_at):
            raise ValueError("retraining_due_at must include a timezone")
        if self.retraining_due_at is not None and self.decision != "update_and_retrain":
            raise ValueError("retraining_due_at is only valid for update_and_retrain")
        return self


class SourceActualityItem(BaseModel):
    source_family_id: UUID
    latest_document_id: UUID
    latest_version: int = Field(gt=0)
    title: str
    filename: str
    actuality_state: ActualityState
    owner_id: UUID | None = None
    owner_name: str | None = None
    reviewed_at: datetime | None = None
    next_review_at: datetime | None = None
    pending_review_id: UUID | None = None
    pending_review_status: ChangeReviewStatus | None = None


class SourceActualityList(BaseModel):
    items: list[SourceActualityItem]
    due_soon_count: int = Field(ge=0)
    overdue_count: int = Field(ge=0)
    pending_decision_count: int = Field(ge=0)
