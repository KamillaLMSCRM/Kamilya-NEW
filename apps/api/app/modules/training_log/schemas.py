"""Training log schemas — Pydantic v2 models for /admin/training-log.

Page[T] envelope for list endpoint (per api-design skill convention).
TrainingLogRow is the flat row that joins User, Course, Enrollment, Position,
Department, Progress (best score for SCORM/native aggregated from Progress),
Certificate, and the latest KioskAccessLog timestamp.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# Filters for the query string. The repository builds SQL from these.
# Keep names snake_case and short — they hit the wire as ?course_id=&department_id=...
class TrainingLogFilter(BaseModel):
    """Filter params for /admin/training-log (used as a typed dep)."""

    course_id: UUID | None = None
    department_id: UUID | None = None
    position_id: UUID | None = None
    # enrollment status derived from `enrollments.status` plus date rules:
    #   assigned  = enrollment exists, not completed
    #   in_progress = enrollment exists, progress > 0
    #   completed = enrollment.status='completed' OR enrollment.completed_at IS NOT NULL
    #   overdue    = (deadline IS NOT NULL AND deadline < now() AND not completed) — no
    #                deadline column today, so we expose the slot but always return None
    status: Literal["assigned", "in_progress", "completed", "overdue"] | None = None
    delivery_type: Literal["native", "scorm"] | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    # Free-text search across first_name, last_name, email, personnel_number.
    search: str | None = Field(default=None, max_length=200)

    model_config = ConfigDict(extra="forbid")


class TrainingLogRow(BaseModel):
    """One flat row of the training log.

    All IDs as UUIDs, all timestamps UTC.
    The frontend shows this 1:1; CSV export reuses the same fields.
    """

    # User identity
    user_id: UUID
    full_name: str
    email: str | None = None
    personnel_number: str | None = None

    # Org structure (nullable: a user without a position/department still appears)
    department_id: UUID | None = None
    department_name: str | None = None
    position_id: UUID | None = None
    position_name: str | None = None

    # Course
    course_id: UUID
    course_title: str
    delivery_type: Literal["native", "scorm"]

    # Enrollment
    enrollment_status: str  # raw: enrolled / completed
    enrollment_source: str  # manual / position / department
    enrolled_at: datetime | None = None
    completed_at: datetime | None = None

    # Progress
    progress_percent: int  # 0..100, computed from `progress` table for native
    # For SCORM: derived from scorm_attempts.lesson_status / completion_status.
    # We surface both: `progress_percent` is the unified 0/100 view for HR.

    # Quiz (native only; SCORM has its own score_raw stored on scorm_attempts)
    best_score: int | None = None  # 0..100
    quiz_attempts_count: int = 0

    # Certificate
    certificate_id: UUID | None = None
    certificate_number: str | None = None
    certificate_issued_at: datetime | None = None

    # Source channel
    kiosk_last_seen_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class TrainingLogPage(BaseModel):
    """Page[T] envelope (api-design convention)."""

    items: list[TrainingLogRow]
    total: int
    limit: int
    offset: int


class TrainingLogCSVResponse(BaseModel):
    """Not actually returned by CSV endpoint (text/csv), but documents the
    contract for tests. The endpoint returns raw CSV with UTF-8 BOM."""

    fields: list[str] = [
        "user_id",
        "full_name",
        "email",
        "personnel_number",
        "department_id",
        "department_name",
        "position_id",
        "position_name",
        "course_id",
        "course_title",
        "delivery_type",
        "enrollment_status",
        "enrollment_source",
        "enrolled_at",
        "completed_at",
        "progress_percent",
        "best_score",
        "quiz_attempts_count",
        "certificate_id",
        "certificate_number",
        "certificate_issued_at",
        "kiosk_last_seen_at",
    ]