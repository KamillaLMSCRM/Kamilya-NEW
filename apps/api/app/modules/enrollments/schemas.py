"""Enrollments — schemas"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EnrollmentCreate(BaseModel):
    user_ids: list[UUID]


class EnrollmentResponse(BaseModel):
    id: UUID
    course_id: UUID
    user_id: UUID
    tenant_id: UUID
    status: str
    source: str = "manual"
    enrolled_at: datetime
    completed_at: datetime | None = None
    notification_status: str | None = None
    notification_attempt_count: int = 0
    notification_delivered_at: datetime | None = None
    notification_error: str | None = None
    model_config = {"from_attributes": True}


class EnrollmentAccessResponse(BaseModel):
    """Methodologist-only delivery/access view for one assignment.

    This deliberately does not turn a personnel number into a credential.  A
    learner with no email remains blocked until a separately designed secure
    second-factor flow exists.
    """

    enrollment_id: UUID
    user_id: UUID
    access_kind: str  # course_access | account_activation | access_without_email
    state: str  # available | needs_activation | blocked
    access_url: str | None = None
    expires_at: datetime | None = None
    message: str


class EnrollmentNotificationResponse(BaseModel):
    enrollment_id: UUID
    notification_id: UUID
    status: str = "pending"


class AssignmentAccessIssueResponse(BaseModel):
    enrollment_id: UUID
    access_url: str
    temporary_pin: str
    expires_at: datetime


class AssignmentAccessExchangeRequest(BaseModel):
    pin: str = Field(pattern=r"^\d{6}$")


class AssignmentAccessExchangeResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]
