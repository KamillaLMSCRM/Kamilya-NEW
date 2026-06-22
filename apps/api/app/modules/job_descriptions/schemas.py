from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class JobDescriptionCreate(BaseModel):
    title: str
    department: str = ""
    position: str = ""
    description: str = ""
    requirements: str = ""


class JobDescriptionResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    title: str
    department: str
    position: str
    description: str
    requirements: str
    status: str
    course_id: UUID | None
    created_at: datetime

    class Config:
        from_attributes = True
