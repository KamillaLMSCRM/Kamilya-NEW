from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class PositionCreate(BaseModel):
    name: str
    department: str = ""
    level: str = ""
    responsibilities: str = ""
    requirements: str = ""


class PositionUpdate(BaseModel):
    name: str | None = None
    department: str | None = None
    level: str | None = None
    responsibilities: str | None = None
    requirements: str | None = None
    course_id: UUID | None = None


class PositionResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    department: str
    level: str
    responsibilities: str
    requirements: str
    course_id: UUID | None
    employee_count: int
    created_at: datetime

    class Config:
        from_attributes = True
