"""Documents — schemas"""
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class DocumentResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    uploaded_by: UUID
    title: str
    filename: str
    content_type: str
    size: int
    s3_key: str
    created_at: datetime
    model_config = {"from_attributes": True}
