from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class AnnouncementCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1, max_length=10000)
    course_id: UUID | None = None


class AnnouncementSummary(BaseModel):
    id: UUID
    title: str
    body: str
    course_id: UUID | None
    status: str
    recipients_count: int
    sent_count: int
    failed_count: int
    sent_at: datetime | None
    created_at: datetime


class AnnouncementSendResult(BaseModel):
    announcement: AnnouncementSummary
    sent_count: int
    failed_count: int
