"""Documents — schemas"""
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Literal


class DocumentResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    uploaded_by: UUID
    title: str
    filename: str
    content_type: str
    size: int
    s3_key: str
    description: str = ""
    category: Literal["general", "job_instruction"] = "general"
    embedding_status: Literal["pending", "success", "failed"] = "pending"
    embedding_error: str | None = None
    created_at: datetime
    updated_at: datetime
    # Populated by router._hydrate when educational summary is available.
    summary_ready: bool = False
    short_summary: str | None = None
    model_config = {"from_attributes": True}
