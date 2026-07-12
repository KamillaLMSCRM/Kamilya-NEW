from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LearningPathCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    status: str = Field(default="draft", pattern="^(draft|published|archived)$")


class LearningPathUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    status: str | None = Field(default=None, pattern="^(draft|published|archived)$")


class LearningPathCourseReplace(BaseModel):
    course_ids: list[UUID] = Field(default_factory=list, max_length=100)


class LearningPathCourseItem(BaseModel):
    course_id: UUID
    title: str
    order_index: int
    required: bool


class LearningPathSummary(BaseModel):
    id: UUID
    title: str
    description: str
    status: str
    course_count: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LearningPathDetail(LearningPathSummary):
    courses: list[LearningPathCourseItem]


class LearnerPathItem(BaseModel):
    id: UUID
    title: str
    description: str
    total_courses: int
    completed_courses: int
    progress_percent: int
