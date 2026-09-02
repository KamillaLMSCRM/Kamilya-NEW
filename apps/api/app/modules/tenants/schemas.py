from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.legal_versions import (
    CURRENT_PRIVACY_CONSENT_VERSION,
    CURRENT_PUBLIC_LEAD_CONSENT_VERSION,
    CURRENT_TERMS_VERSION,
)

TenantIntent = Literal["try", "demo", "buy"]
EmployeeCountRange = Literal["1-10", "11-50", "51-200", "201-1000", "1000+"]


class PublicRegistrationLegalAcceptance(BaseModel):
    """Versioned legal acceptance supplied only by public self-registration."""

    model_config = ConfigDict(extra="forbid")

    privacy_consent_version: str = Field(..., min_length=1, max_length=80)
    privacy_consent_locale: Literal["ru"]
    privacy_consent_surface: str = Field(..., min_length=1, max_length=80)
    terms_version: str = Field(..., min_length=1, max_length=80)

    @field_validator("privacy_consent_version", "privacy_consent_surface", "terms_version")
    @classmethod
    def normalize_evidence_value(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("privacy_consent_version")
    @classmethod
    def require_current_privacy_version(cls, value: str) -> str:
        if value != CURRENT_PRIVACY_CONSENT_VERSION:
            raise ValueError("is not the current privacy consent version")
        return value

    @field_validator("terms_version")
    @classmethod
    def require_current_terms_version(cls, value: str) -> str:
        if value != CURRENT_TERMS_VERSION:
            raise ValueError("is not the current terms version")
        return value


class TenantRegisterRequest(PublicRegistrationLegalAcceptance):
    company_name: str = Field(..., min_length=2, max_length=200)
    contact_name: str = Field(..., min_length=2, max_length=160)
    email: EmailStr
    email_code: str = Field(..., pattern=r"^\d{6}$")
    # Optional for backward compatibility with older web deployments. New
    # self-service registrations prove address ownership with the purpose-bound
    # email code and intentionally create a passwordless first user.
    password: str | None = Field(None, min_length=8, max_length=128)
    phone: str | None = Field(None, max_length=80)
    telegram_username: str | None = Field(None, max_length=80)
    employee_count_range: EmployeeCountRange | None = None
    preferred_language: Literal["ru", "kk", "en"] = "ru"
    intent: TenantIntent = "try"
    billing_identifier: str | None = Field(None, max_length=64)
    message: str | None = Field(None, max_length=2000)
    utm_source: str | None = Field(None, max_length=100)
    utm_medium: str | None = Field(None, max_length=100)
    utm_campaign: str | None = Field(None, max_length=100)
    utm_content: str | None = Field(None, max_length=100)
    utm_term: str | None = Field(None, max_length=100)
    referrer: str | None = Field(None, max_length=500)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower().strip()


class TenantRegistrationCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower().strip()


class TenantRegistrationCodeResponse(BaseModel):
    ok: bool = True
    expires_in: int


class TrialLimits(BaseModel):
    ai_course_generations_limit: int
    jd_course_generations_limit: int
    max_students: int
    system_users_limit: int
    trial_days: int


class TenantRegisterResponse(BaseModel):
    tenant_id: UUID
    tenant_slug: str
    tenant_name: str
    lead_id: UUID
    user_id: UUID
    role: str
    access_token: str
    expires_in: int
    user: dict
    trial_started_at: datetime
    trial_ends_at: datetime
    limits: TrialLimits
    next_step: str = "trial_onboarding"


class PublicLeadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=2, max_length=100)
    company: str = Field(..., min_length=2, max_length=200)
    email: EmailStr
    phone: str | None = Field(None, max_length=50)
    companySize: int | None = Field(None, ge=1, le=100000)  # noqa: N815
    industry: str | None = Field(None, max_length=80)
    interest: str = Field(..., max_length=40)
    message: str | None = Field(None, max_length=1000)
    locale: Literal["ru", "kk"] = "ru"
    utm_source: str | None = Field(None, max_length=100)
    utm_medium: str | None = Field(None, max_length=100)
    utm_campaign: str | None = Field(None, max_length=100)
    utm_content: str | None = Field(None, max_length=100)
    utm_term: str | None = Field(None, max_length=100)
    gclid: str | None = Field(None, max_length=200)
    referrer: str | None = Field(None, max_length=500)
    landing_page: str | None = Field(None, max_length=1000)
    attribution_captured_at: datetime | None = None
    consent_version: str = Field(..., min_length=1, max_length=50)
    source_section: str | None = Field(None, max_length=100)
    plan: str | None = Field(None, max_length=100)
    roi_employees: int | None = Field(None, ge=1, le=100000)
    roi_industry: str | None = Field(None, max_length=100)
    roi_employee_band: str | None = Field(None, max_length=50)
    roi_formula_version: str | None = Field(None, max_length=50)
    website: str | None = Field(None, max_length=0)

    @field_validator("email")
    @classmethod
    def normalize_public_email(cls, value: str) -> str:
        return value.lower().strip()

    @field_validator("consent_version")
    @classmethod
    def require_current_lead_consent_version(cls, value: str) -> str:
        if value.strip() != CURRENT_PUBLIC_LEAD_CONSENT_VERSION:
            raise ValueError("is not the current public lead consent version")
        return CURRENT_PUBLIC_LEAD_CONSENT_VERSION


class PublicLeadResponse(BaseModel):
    id: UUID
    ok: bool = True
