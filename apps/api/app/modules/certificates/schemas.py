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


class CertificateSettings(BaseModel):
    organization_name: str = "Kamilya LMS"
    signer_name: str = ""
    signer_title: str = ""
    validity_months: int | None = None
    footer_note: str = ""
    verification_base_url: str = "https://app.kml.kz/certificates"
    show_verification_url: bool = True
