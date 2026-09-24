from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.learning_insights.schemas import QuestionStats
from app.modules.training_log.schemas import TrainingLogRow, TrainingLogSummary

TargetType = Literal["enrollment", "question"]
IssueType = Literal["not_started", "stalled", "overdue", "failed_required_quiz", "weak_question"]
ActionType = Literal["reminder", "reassignment", "supplemental_material", "manual_review"]
ActionStatus = Literal["open", "completed", "cancelled"]
Resolution = Literal["observed", "manual", "cancelled"]


class LearningActionCreate(BaseModel):
    target_type: TargetType
    enrollment_id: UUID | None = None
    course_id: UUID | None = None
    quiz_id: UUID | None = None
    content_release_id: UUID | None = None
    question_id: UUID | None = None
    question_key: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    issue_type: IssueType
    action_type: ActionType
    owner_id: UUID | None = None
    due_at: datetime | None = None
    comment: str | None = Field(default=None, max_length=4000)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if self.due_at is not None and self.due_at.tzinfo is None:
            raise ValueError("due_at must include a timezone")
        if self.target_type == "enrollment":
            if self.enrollment_id is None or any(
                value is not None
                for value in (
                    self.course_id,
                    self.quiz_id,
                    self.content_release_id,
                    self.question_id,
                    self.question_key,
                )
            ):
                raise ValueError("Enrollment targets require only enrollment_id")
            if self.issue_type == "weak_question":
                raise ValueError("weak_question requires a question target")
        else:
            if (
                any(value is None for value in (self.course_id, self.quiz_id, self.question_id, self.question_key))
                or self.enrollment_id is not None
            ):
                raise ValueError("Question targets require course, quiz, question and question_key identities")
            if self.issue_type != "weak_question":
                raise ValueError("Question targets require the weak_question issue type")
        return self


class LearningActionClose(BaseModel):
    resolution: Resolution
    note: str | None = Field(default=None, max_length=4000)

    model_config = ConfigDict(extra="forbid")


class LearningActionRecord(BaseModel):
    id: UUID
    tenant_id: UUID
    target_type: TargetType
    target_key: str
    enrollment_id: UUID | None
    course_id: UUID
    quiz_id: UUID | None
    content_release_id: UUID | None
    question_id: UUID | None
    question_key: str | None
    issue_type: IssueType
    action_type: ActionType
    owner_id: UUID | None
    created_by: UUID | None
    due_at: datetime | None
    comment: str | None
    baseline_snapshot: dict[str, Any]
    outcome_snapshot: dict[str, Any] | None
    status: ActionStatus
    resolution: Resolution | None
    resolution_note: str | None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class TrainingActionSuggestion(TrainingLogRow):
    issue_type: Literal["not_started", "stalled", "overdue", "failed_required_quiz"]
    active_action_id: UUID | None = None
    active_action_types: list[ActionType] = Field(default_factory=list)


class WeakQuestionSuggestion(QuestionStats):
    active_action_id: UUID | None = None
    active_action_types: list[ActionType] = Field(default_factory=list)


class LearningActionSummary(BaseModel):
    training_log: TrainingLogSummary
    training_issue_count: int
    training_issue_counts: dict[str, int]
    training_items_truncated: bool
    weak_question_count: int
    action_count: int
    actions_truncated: bool
    open_action_count: int
    overdue_action_count: int


class LearningActionList(BaseModel):
    summary: LearningActionSummary
    training_items: list[TrainingActionSuggestion]
    weak_questions: list[WeakQuestionSuggestion]
    actions: list[LearningActionRecord]
