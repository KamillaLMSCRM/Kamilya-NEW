from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, Field


class CompetencyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)


class CompetencyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)


class CompetencyLinks(BaseModel):
    position_ids: list[UUID] = Field(default_factory=list, max_length=200)
    course_ids: list[UUID] = Field(default_factory=list, max_length=200)


class CompetencySummary(BaseModel):
    id: UUID
    name: str
    description: str
    created_at: datetime
    position_count: int
    course_count: int


class CompetencyDetail(CompetencySummary):
    position_ids: list[UUID]
    course_ids: list[UUID]
