"""Quiz Assignment schemas"""
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field


class QuizAssignmentCreate(BaseModel):
    quiz_id: UUID
    user_ids: list[UUID]
    due_date: datetime | None = None


class QuizAssignmentByPositionsCreate(BaseModel):
    """Bulk-assign by position. Backend expands position_ids into user_ids
    (all users currently on those positions in the tenant). Useful for
    "назначить всем кассирам" workflows — the methodologist doesn't have
    to handpick 30 names.

    auto_invite=True: if a position has an email template, send invitations
    to non-registered emails too. Currently a no-op until invitation
    integration is wired; left in schema so the UI can opt in early.
    """
    quiz_id: UUID
    position_ids: list[UUID] = Field(..., min_length=1, max_length=50)
    due_date: datetime | None = None
    auto_invite: bool = False


class QuizAssignmentResponse(BaseModel):
    id: UUID
    quiz_id: UUID
    quiz_title: str | None = None
    user_id: UUID
    user_name: str | None = None
    user_email: str | None = None
    assigned_by: UUID
    due_date: datetime | None = None
    status: str
    score_percent: int | None = None
    completed_at: datetime | None = None
    created_at: datetime
    # Position context — set when assignment was created via by-positions
    # and the user's position hasn't changed since. Helps the UI show
    # "назначено как <PositionName>" instead of just user name.
    position_id: UUID | None = None
    position_name: str | None = None

    class Config:
        from_attributes = True


class QuizAssignmentBulkResponse(BaseModel):
    created: int
    skipped: int


class PositionAssignmentSummary(BaseModel):
    """Returned by the by-positions endpoint so the UI can show
    'expanded from 3 positions, 47 employees, 12 already had this quiz'."""
    positions_requested: int
    users_targeted: int
    users_assigned: int
    users_skipped: int
    positions_not_found: list[UUID] = []
