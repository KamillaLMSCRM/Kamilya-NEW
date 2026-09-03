from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ApprovalPolicyRequest(BaseModel):
    requires_approval: bool


class ApprovalPolicyResponse(BaseModel):
    course_id: UUID
    requires_approval: bool
    updated_at: datetime | None = None


class ApprovalRevisionResponse(BaseModel):
    id: UUID
    course_id: UUID
    revision_number: int
    snapshot_sha256: str
    state: str
    created_at: datetime


class ApprovalRequestCreate(BaseModel):
    reviewer_user_ids: list[UUID] = Field(min_length=1)
    delivery_mode: str = Field(pattern="^(email|personal_link)$")
    due_at: datetime | None = None


class ReviewerAccessSecret(BaseModel):
    reviewer_id: UUID
    access_url: str
    temporary_pin: str
    expires_at: datetime


class ApprovalRequestResponse(BaseModel):
    request_id: UUID | None = None
    revision_id: UUID
    reviewer_ids: list[UUID]
    outcome: str
    delivery_mode: str
    access_url: str | None = None
    temporary_pin: str | None = None
    access_credentials: list[ReviewerAccessSecret] = Field(default_factory=list)


class ReviewProgressRequest(BaseModel):
    sequence: int = Field(ge=1)
    lesson_position: int | None = Field(default=None, ge=0)
    event_type: str = Field(min_length=1, max_length=48)
    payload: dict = Field(default_factory=dict)
    activity_state: str = Field(default="in_progress", pattern="^(not_started|in_progress|completed)$")


class ReviewDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(approve|return)$")
    reason: str | None = Field(default=None, max_length=4000)
    acknowledge_incomplete_warning: bool = False


class ReviewPinRequest(BaseModel):
    pin: str = Field(pattern=r"^\d{6}$")
