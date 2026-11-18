from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LearnerAssistantChatRequest(BaseModel):
    course_id: UUID
    lesson_id: UUID
    message: str = Field(..., min_length=1, max_length=1200)
    provider: Literal["chatgpt_reserve"] | None = None


class LearnerAssistantChatResponse(BaseModel):
    reply: str
    sources: list[str] = []


class LearnerAssistantMessageResponse(BaseModel):
    id: UUID
    role: str
    content: str
    lesson_id: UUID | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

