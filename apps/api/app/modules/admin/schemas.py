"""Admin dashboard schemas"""
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class TenantStats(BaseModel):
    total_users: int = 0
    active_users: int = 0
    total_courses: int = 0
    published_courses: int = 0
    ai_generated_courses: int = 0
    total_enrollments: int = 0
    completed_enrollments: int = 0
    total_quizzes_taken: int = 0
    average_quiz_score: float = 0.0
    certificates_issued: int = 0
    documents_uploaded: int = 0
    storage_used_bytes: int = 0


class UserListItem(BaseModel):
    id: UUID
    email: str
    first_name: str
    last_name: str
    role: str
    is_active: bool
    last_login: datetime | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


class CourseListItem(BaseModel):
    id: UUID
    title: str
    status: str
    ai_generated: bool
    created_by: UUID | None = None
    created_at: datetime
    published_at: datetime | None = None
    enrollment_count: int = 0
    model_config = {"from_attributes": True}


class EnrollmentStats(BaseModel):
    course_id: UUID
    course_title: str
    total_enrolled: int = 0
    completed: int = 0
    in_progress: int = 0
    not_started: int = 0
    average_progress: float = 0.0


class ActivitySummary(BaseModel):
    date: str
    new_users: int = 0
    new_enrollments: int = 0
    quizzes_taken: int = 0
    certificates_issued: int = 0


class AdminDashboard(BaseModel):
    stats: TenantStats
    recent_users: list[UserListItem]
    recent_courses: list[CourseListItem]
    enrollment_by_course: list[EnrollmentStats]
    activity_summary: list[ActivitySummary]
