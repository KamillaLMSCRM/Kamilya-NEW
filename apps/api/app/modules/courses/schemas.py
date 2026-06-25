from pydantic import BaseModel, Field, ConfigDict
from typing import Literal
from uuid import UUID
from datetime import datetime

class CourseCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., max_length=5000)
    status: str = "draft"

class CourseUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None

class CourseReviewer(BaseModel):
    """Small projection of the user who reviewed (name + role) — embedded
    in CourseResponse when available so the UI doesn't need a second request."""
    id: UUID
    full_name: str | None = None
    role: str | None = None

    model_config = ConfigDict(from_attributes=True)

class CourseResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    title: str
    description: str
    status: str
    thumbnail_url: str | None = None
    ai_generated: bool = False
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None

    # Approval workflow fields (methodologist sign-off).
    review_status: Literal["pending", "approved", "needs_changes"] = "pending"
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    review_comment: str | None = None
    reviewer: CourseReviewer | None = None

    model_config = {'from_attributes': True}


class CourseReviewRequest(BaseModel):
    """Body for POST /courses/{id}/review."""
    review_status: Literal["approved", "needs_changes"]
    comment: str | None = Field(default=None, max_length=2000)


class CoursePreviewLesson(BaseModel):
    id: UUID
    title: str
    content_type: str = "text"
    content_preview: str  # first ~240 chars for inline preview
    duration_seconds: int | None = None
    order_index: int
    has_quiz: bool = False
    quiz_id: UUID | None = None
    quiz_title: str | None = None
    quiz_question_count: int = 0


class CoursePreviewModule(BaseModel):
    id: UUID
    title: str
    description: str = ""
    order_index: int
    lessons: list[CoursePreviewLesson] = []


class CoursePreviewResponse(BaseModel):
    id: UUID
    title: str
    description: str
    status: str
    modules_count: int
    lessons_count: int
    quizzes_count: int
    modules: list[CoursePreviewModule] = []


class CoursePreviewRequest(BaseModel):
    max_lesson_preview_chars: int = Field(default=240, ge=80, le=2000)
