from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class RuleCreate(BaseModel):
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
    cadence_days: int | None = Field(None, ge=1, le=3660)
    due_days: int | None = Field(None, ge=0, le=3650)


class RuleResponse(BaseModel):
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
    scheduled_for: datetime
    due_at: datetime
    completed_at: datetime | None
    status: str
