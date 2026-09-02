"""Certificate schemas."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

PUBLIC_CERTIFICATE_VERIFICATION_BASE_URL = "https://app.kml.kz/verify/certificate"


class CertificateResponse(BaseModel):
    id: UUID
    course_id: UUID
    learning_path_assignment_id: UUID | None = None
    certificate_number: str
    issued_at: datetime
    expires_at: datetime | None = None
    status: Literal["active", "expired", "revoked"]
    user_name: str = ""
    course_title: str = ""
    model_config = {"from_attributes": True}


class CertificateGenerateRequest(BaseModel):
    course_id: UUID


class CertificateSettings(BaseModel):
    organization_name: str = Field(default="Kamilya LMS", min_length=1, max_length=160)
    signer_name: str = Field(default="", max_length=160)
    signer_title: str = Field(default="", max_length=160)
    validity_months: int | None = Field(default=None, ge=0, le=120)
    footer_note: str = Field(default="", max_length=500)
    verification_base_url: str = PUBLIC_CERTIFICATE_VERIFICATION_BASE_URL
    show_verification_url: bool = True

    @field_validator("organization_name", "signer_name", "signer_title", "footer_note")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("verification_base_url", mode="before")
    @classmethod
    def use_canonical_verification_url(cls, _value: object) -> str:
        return PUBLIC_CERTIFICATE_VERIFICATION_BASE_URL


class CertificatePreviewRequest(BaseModel):
    settings: CertificateSettings
    sample_user_name: str = Field(default="Александр Сотрудников", min_length=1, max_length=160)
    sample_course_title: str = Field(
        default="Безопасная работа и внутренние процедуры",
        min_length=1,
        max_length=300,
    )


class CertificateVerificationResponse(BaseModel):
    valid: bool
    status: Literal["active", "expired", "revoked"]
    certificate_number: str
    issued_at: datetime
    expires_at: datetime | None = None
    user_name: str
    course_title: str
    organization_name: str
    revoked_reason: str | None = None


class CertificateRevocationRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Reason must contain at least 3 characters")
        return value
