"""Quiz Assignment schemas"""
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel


class QuizAssignmentCreate(BaseModel):
    quiz_id: UUID
    user_ids: list[UUID]
    due_date: datetime | None = None


class QuizAssignmentResponse(BaseModel):
    id: UUID
    quiz_id: UUID
    quiz_title: str | None = None
    user_id: UUID
    user_name: str | None = None
    assigned_by: UUID
    due_date: datetime | None = None
    status: str
    score_percent: int | None = None
    completed_at: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class QuizAssignmentBulkResponse(BaseModel):
    created: int
    skipped: int
