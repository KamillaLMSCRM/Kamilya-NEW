"""Progress — schemas"""
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class ProgressUpdate(BaseModel):
    completed: bool = True
    completion_percent: int = 100


class ProgressResponse(BaseModel):
    id: UUID
    user_id: UUID
    lesson_id: UUID
    tenant_id: UUID
    completed: bool
    completion_percent: int
    started_at: datetime
    completed_at: datetime | None = None
    last_accessed_at: datetime | None = None
    model_config = {"from_attributes": True}


class CourseProgressResponse(BaseModel):
    course_id: UUID
    total_lessons: int
    completed_lessons: int
    percent: float


class UserProgressResponse(BaseModel):
    user_id: UUID
    courses: list[CourseProgressResponse]
