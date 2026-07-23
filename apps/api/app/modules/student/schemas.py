"""Student dashboard schemas"""
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class LessonProgress(BaseModel):
    lesson_id: UUID
    title: str
    completed: bool
    progress_percent: int = 0


class ModuleProgress(BaseModel):
    module_id: UUID
    title: str
    lessons: list[LessonProgress]


class EnrolledCourse(BaseModel):
    course_id: UUID
    title: str
    description: str
    status: str
    enrollment_status: str
    progress_percent: int = 0
    total_lessons: int = 0
    completed_lessons: int = 0
    enrolled_at: datetime
    last_accessed_at: datetime | None = None
    thumbnail_url: str | None = None


class StudentDashboard(BaseModel):
    user_id: UUID
    full_name: str
    enrolled_courses: list[EnrolledCourse]
    total_courses: int = 0
    completed_courses: int = 0
    total_progress_percent: int = 0
    certificates_count: int = 0
    recent_activity: list[dict] = []


class CourseProgress(BaseModel):
    course_id: UUID
    title: str
    modules: list[ModuleProgress]
