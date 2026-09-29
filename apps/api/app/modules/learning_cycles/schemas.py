from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class RuleCreate(BaseModel):
    reminder_enabled: bool = False
    reminder_days_before_due: int = Field(1, ge=1, le=30)
    course_id: UUID | None = None
    learning_path_id: UUID | None = None
    user_id: UUID
    cadence_days: int | None = Field(None, ge=1, le=3660)
    due_days: int | None = Field(None, ge=0, le=3650)

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if (self.course_id is None) == (self.learning_path_id is None):
            raise ValueError("exactly one recurring rule target is required")
        if self.learning_path_id is not None and (self.cadence_days is not None or self.due_days is not None):
            raise ValueError("LearningPath recurrence cadence and due are source-controlled")
        if self.course_id is not None and (self.cadence_days is None or self.due_days is None):
            raise ValueError("course recurrence cadence and due are required")
        if (
            self.course_id is not None
            and self.due_days is not None
            and self.cadence_days is not None
            and self.due_days > self.cadence_days
        ):
            raise ValueError("due_days must not exceed cadence_days")
        return self


class RuleUpdate(BaseModel):
    reminder_enabled: bool | None = None
    reminder_days_before_due: int | None = Field(None, ge=1, le=30)
    cadence_days: int | None = Field(None, ge=1, le=3660)
    due_days: int | None = Field(None, ge=0, le=3650)


class RuleResponse(BaseModel):
    reminder_enabled: bool = False
    reminder_days_before_due: int = 1
    id: UUID
    tenant_id: UUID
    target_type: Literal["course", "learning_path"]
    course_id: UUID | None
    learning_path_id: UUID | None
    user_id: UUID
    cadence_days: int
    due_days: int
    status: str
    next_run_at: datetime | None
    last_run_at: datetime | None

    model_config = {"from_attributes": True}


class LearningPathSyncResponse(BaseModel):
    path_id: UUID
    created: int
    reconciled: int
    skipped: int
    total: int


class OccurrenceResponse(BaseModel):
    id: UUID
    rule_id: UUID
    user_id: UUID
    target_type: Literal["course", "learning_path"]
    course_id: UUID | None
    learning_path_id: UUID | None
    enrollment_id: UUID | None
    sequence_no: int
    content_release_id: UUID | None = None
    scheduled_for: datetime
    original_due_at: datetime
    effective_due_at: datetime
    due_at: datetime
    completed_at: datetime | None
    status: str


class DeadlineOverrideRequest(BaseModel):
    effective_due_at: datetime
    reason: str = Field(min_length=20, max_length=1000)

    @field_validator("effective_due_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("effective_due_at must include a timezone")
        return value

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 20:
            raise ValueError("reason must contain at least 20 meaningful characters")
        return normalized


class ParticipantEventResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    course_occurrence_id: UUID | None
    path_cycle_instance_id: UUID | None
    user_id: UUID
    event_type: Literal["deadline_override"]
    previous_effective_due_at: datetime
    effective_due_at: datetime
    reason: str
    actor_id: UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}
