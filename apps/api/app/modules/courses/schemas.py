from pydantic import BaseModel, Field
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

class CourseResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    title: str
    description: str
    status: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None

    model_config = {'from_attributes': True}
