"""AI Generation — schemas"""
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional, List


class AIGenerateRequest(BaseModel):
    course_id: UUID | None = None
    documents: List[str] = Field(default=[], description="Document IDs or text content")
    target_audience: str = Field(default="", description="Target audience description")
    num_modules: int = Field(default=3, ge=1, le=10)
    language: str = Field(default="ru")
    tone: str = Field(default="professional")


class AIJobResponse(BaseModel):
    id: str
    status: str
    course_id: UUID | None
    created_at: datetime
    progress: int = 0
    stage: str = ""
    message: str = ""


class AIJobProgress(BaseModel):
    job_id: str
    status: str
    stage: str
    progress: int
    message: str
    course_id: UUID | None = None
