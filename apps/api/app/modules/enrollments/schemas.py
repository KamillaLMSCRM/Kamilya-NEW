"""Enrollments — schemas"""
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class EnrollmentCreate(BaseModel):
    user_ids: list[UUID]


class EnrollmentResponse(BaseModel):
    id: UUID
    course_id: UUID
    user_id: UUID
    tenant_id: UUID
    status: str
    enrolled_at: datetime
    completed_at: datetime | None = None
    model_config = {"from_attributes": True}
