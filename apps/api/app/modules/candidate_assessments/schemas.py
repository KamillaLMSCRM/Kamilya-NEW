from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CampaignCreate(BaseModel):
    content_release_id: UUID
    title: str = Field(min_length=1, max_length=255)
    instructions: str = Field(default="", max_length=5000)
    expires_at: datetime
    attempt_limit: int = Field(default=1, ge=1, le=10)
    retention_days: int = Field(default=180, ge=1, le=3650)


class CampaignUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    instructions: str | None = Field(default=None, max_length=5000)
    status: str | None = Field(default=None, pattern="^(draft|active|closed)$")
    expires_at: datetime | None = None
    attempt_limit: int | None = Field(default=None, ge=1, le=10)
    retention_days: int | None = Field(default=None, ge=1, le=3650)


class CandidateCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(default="", max_length=120)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=64)


class CandidateStatusUpdate(BaseModel):
    status: str = Field(pattern="^(invited|active|completed|withdrawn)$")


class PinRequest(BaseModel):
    pin: str = Field(pattern=r"^\d{6}$")
    consent: bool


class Answer(BaseModel):
    question_id: UUID
    selected_choice_ids: list[UUID]


class Submission(BaseModel):
    attempt_id: UUID
    answers: list[Answer] = Field(min_length=1, max_length=500)
