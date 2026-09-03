from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ApprovalPolicyRequest(BaseModel):
    requires_approval: bool
    review_enabled: bool = True


class ApprovalPolicyResponse(BaseModel):
    course_id: UUID
    requires_approval: bool
    review_enabled: bool = True
    updated_at: datetime | None = None


class ApprovalRevisionResponse(BaseModel):
    id: UUID
    course_id: UUID
    revision_number: int
    snapshot_sha256: str
    state: str
    created_at: datetime


class GuestReviewer(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    name: str | None = Field(default=None, max_length=200)


class ApprovalRequestCreate(BaseModel):
    reviewer_user_ids: list[UUID] = Field(default_factory=list)
    guest_reviewers: list[GuestReviewer] = Field(default_factory=list)
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


class ReviewerStatusResponse(BaseModel):
    reviewer_id: UUID | None = None
    reviewer_name: str | None = None
    reviewer_email: str | None = None
    decision: str
    decision_at: datetime | None = None
    required: bool
    delivery_state: str
    access_state: str
    activity_state: str
    deadline_state: str
    outcome: str
    progress: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class ScopedReviewRequestResponse(BaseModel):
    request_id: UUID
    revision_id: UUID
    outcome: str
    delivery_mode: str
    due_at: datetime | None = None
    reviewer: ReviewerStatusResponse
    all_required_approved: bool


class ResendAccessRequest(BaseModel):
    rotate_credentials: bool = False


class ReviewProgressRequest(BaseModel):
    sequence: int = Field(ge=1)
    lesson_position: int | None = Field(default=None, ge=0)
    event_type: str = Field(min_length=1, max_length=48)
    payload: dict[str, Any] = Field(default_factory=dict)
    # Kept for wire compatibility; the server ignores "completed" claims and
    # derives completion from validated checkpoints/test diagnostics.
    activity_state: str = Field(default="in_progress", pattern="^(not_started|in_progress|completed)$")


class ReviewDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(approve|return)$")
    reason: str | None = Field(default=None, max_length=4000)
    acknowledge_incomplete_warning: bool = False


class ReviewTestSubmission(BaseModel):
    question_id: UUID
    selected_choice_ids: list[UUID] = Field(default_factory=list)


class ReviewPinRequest(BaseModel):
    pin: str = Field(pattern=r"^\d{6}$")
