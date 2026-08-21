from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

SupportCategory = Literal["access", "technical", "learning", "staff", "billing", "other"]
SupportDeliveryStatus = Literal["pending", "sent", "deferred", "failed"]


class SupportRequestCreate(BaseModel):
    category: SupportCategory
    subject: str = Field(..., min_length=3, max_length=160)
    message: str = Field(..., min_length=10, max_length=4000)
    current_path: str | None = Field(default=None, max_length=500)

    @field_validator("subject", "message", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            raise ValueError("value must contain non-whitespace characters")
        return value

    @field_validator("current_path")
    @classmethod
    def normalize_current_path(cls, value: str | None) -> str | None:
        value = value.strip() if value else None
        return value or None


class SupportRequestCreated(BaseModel):
    id: UUID
    reference: str
    delivery_status: SupportDeliveryStatus
    created_at: datetime
