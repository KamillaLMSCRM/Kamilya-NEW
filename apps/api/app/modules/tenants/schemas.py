from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


TenantIntent = Literal["try", "demo", "buy"]
EmployeeCountRange = Literal["1-10", "11-50", "51-200", "201-1000", "1000+"]


class TenantRegisterRequest(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=200)
    contact_name: str = Field(..., min_length=2, max_length=160)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    phone: str | None = Field(None, max_length=80)
    telegram_username: str | None = Field(None, max_length=80)
    employee_count_range: EmployeeCountRange | None = None
    preferred_language: Literal["ru", "kk", "en"] = "ru"
    intent: TenantIntent = "try"
    billing_identifier: str | None = Field(None, max_length=64)
    message: str | None = Field(None, max_length=2000)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower().strip()


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
    refresh_token: str
    expires_in: int
    user: dict
    trial_started_at: datetime
    trial_ends_at: datetime
    limits: TrialLimits
    next_step: str = "trial_onboarding"


class PublicLeadRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    company: str = Field(..., min_length=2, max_length=200)
    email: EmailStr
    phone: str | None = Field(None, max_length=50)
    companySize: int | None = Field(None, ge=1, le=100000)
    industry: str | None = Field(None, max_length=80)
    interest: str = Field(..., max_length=40)
    message: str | None = Field(None, max_length=1000)
    locale: Literal["ru", "kk"] = "ru"
    utm_source: str | None = Field(None, max_length=100)
    utm_medium: str | None = Field(None, max_length=100)
    utm_campaign: str | None = Field(None, max_length=100)
    referrer: str | None = Field(None, max_length=500)
    website: str | None = Field(None, max_length=0)

    @field_validator("email")
    @classmethod
    def normalize_public_email(cls, value: str) -> str:
        return value.lower().strip()


class PublicLeadResponse(BaseModel):
    id: UUID
    ok: bool = True
