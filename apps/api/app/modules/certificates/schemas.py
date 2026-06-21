"""Certificate schemas"""
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class CertificateResponse(BaseModel):
    id: UUID
    course_id: UUID
    certificate_number: str
    issued_at: datetime
    expires_at: datetime | None = None
    model_config = {"from_attributes": True}


class CertificateGenerateRequest(BaseModel):
    course_id: UUID
