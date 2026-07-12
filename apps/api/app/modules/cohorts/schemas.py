from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class CohortCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)


class CohortLinks(BaseModel):
    user_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    course_ids: list[UUID] = Field(default_factory=list, max_length=200)


class CohortSummary(BaseModel):
    id: UUID
    name: str
    description: str
    is_active: bool
    member_count: int
    course_count: int
    created_at: datetime


class LearnerCohort(BaseModel):
    id: UUID
    name: str
    description: str
    course_ids: list[UUID]
