from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RuleCreate(BaseModel):
    course_id: UUID
    user_id: UUID
    cadence_days: int = Field(ge=1, le=3660)
    due_days: int = Field(ge=0, le=365)


class RuleUpdate(BaseModel):
    cadence_days: int | None = Field(None, ge=1, le=3660)
    due_days: int | None = Field(None, ge=0, le=365)


class RuleResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    course_id: UUID
    user_id: UUID
    cadence_days: int
    due_days: int
    status: str
    next_run_at: datetime | None
    last_run_at: datetime | None

    model_config = {"from_attributes": True}


class OccurrenceResponse(BaseModel):
    id: UUID
    rule_id: UUID
    user_id: UUID
    course_id: UUID
    enrollment_id: UUID | None
    scheduled_for: datetime
    due_at: datetime
    completed_at: datetime | None
    status: str
