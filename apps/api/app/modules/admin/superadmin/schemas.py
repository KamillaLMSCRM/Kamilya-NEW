"""Pydantic schemas for superadmin endpoints.

Plan whitelist (enforced here, not in DB) — keep in sync with the
allowlist inside TenantUpdate below. Adding a new plan = one line here
and on the frontend.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


PLAN_NAMES = Literal["free", "trial", "pro", "enterprise"]
TENANT_STATUSES = Literal["active", "trial", "suspended", "archived"]
ADMIN_ROLES = Literal["admin", "org_admin", "teacher"]


# ── Tenant ────────────────────────────────────────────────────────────


class SubscriptionInfo(BaseModel):
    """Billing-relevant fields for the tenant detail view."""

    plan: str
    status: str
    trial_ends_at: datetime | None
    paid_until: datetime | None
    max_users: int | None
    max_courses_per_month: int | None


class TenantStats(BaseModel):
    """Per-tenant usage counters surfaced in the superadmin UI."""

    user_count: int = 0
    active_user_count: int = 0
    admin_count: int = 0
    course_count: int = 0
    published_course_count: int = 0
    document_count: int = 0
    enrollment_count: int = 0
    last_activity_at: datetime | None = None


class TenantResponse(BaseModel):
    """Tenant detail (used for list + detail endpoints)."""

    id: uuid.UUID
    name: str
    slug: str
    status: str
    plan: str
    trial_ends_at: datetime | None
    paid_until: datetime | None
    max_users: int | None
    max_courses_per_month: int | None
    notes: str | None
    settings: dict
    created_at: datetime
    updated_at: datetime
    stats: TenantStats | None = None

    model_config = {"from_attributes": True}


class TenantListResponse(BaseModel):
    """GET /v1/admin/super/tenants — paged list of tenants."""

    tenants: list[TenantResponse]
    total: int


class TenantCreate(BaseModel):
    """POST /v1/admin/super/tenants — create a new tenant."""

    name: str = Field(..., min_length=2, max_length=200)
    slug: str = Field(..., min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    plan: PLAN_NAMES = "trial"
    status: TENANT_STATUSES = "trial"
    trial_ends_at: datetime | None = None
    paid_until: datetime | None = None
    max_users: int | None = Field(None, ge=1)
    max_courses_per_month: int | None = Field(None, ge=0)
    notes: str | None = Field(None, max_length=2000)


class TenantUpdate(BaseModel):
    """PATCH /v1/admin/super/tenants/{id} — partial update."""

    name: str | None = Field(None, min_length=2, max_length=200)
    slug: str | None = Field(None, min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    status: TENANT_STATUSES | None = None
    plan: PLAN_NAMES | None = None
    trial_ends_at: datetime | None = None
    paid_until: datetime | None = None
    max_users: int | None = Field(None, ge=1)
    max_courses_per_month: int | None = Field(None, ge=0)
    notes: str | None = Field(None, max_length=2000)
    settings: dict | None = None


# ── Admins (per-tenant users with elevated roles) ─────────────────────


class AdminCreate(BaseModel):
    """POST /v1/admin/super/tenants/{id}/admins — add a user to a tenant.

    Provide exactly one of: email, telegram_id. (Both is fine too — that
    user can log in either way.) If a user with the given identifier
    already exists in this tenant, we promote them; otherwise we create
    a fresh row. Setting a password_hash is optional — if neither email
    nor telegram can log the user in yet, the superadmin must share
    an invite URL manually.
    """

    email: EmailStr | None = None
    telegram_id: int | None = Field(None, ge=1)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    role: ADMIN_ROLES = "admin"
    is_active: bool = True
    send_invite: bool = Field(
        False,
        description=(
            "If true and `email` is set, generate a UserInvitation so the"
            " new admin receives an invite URL. Telegram-only admins are"
            " skipped — they log in directly via the bot."
        ),
    )

    @field_validator("email", "telegram_id")
    @classmethod
    def at_least_one_identifier(cls, v, info):
        # Only the first failing field raises — Pydantic runs validators
        # in order. We check both inside this validator by reading the
        # already-validated sibling via info.data.
        if info.field_name == "telegram_id" and not info.data.get("email") and v is None:
            raise ValueError("Either email or telegram_id is required")
        return v


class AdminUpdate(BaseModel):
    """PATCH /v1/admin/super/tenants/{id}/admins/{user_id}."""

    role: ADMIN_ROLES | None = None
    is_active: bool | None = None
    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)


class AdminResponse(BaseModel):
    """Admin user as shown in the tenant detail page."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str | None
    telegram_id: int | None
    first_name: str
    last_name: str
    role: str
    is_active: bool
    status: str
    created_at: datetime
    last_login: datetime | None

    model_config = {"from_attributes": True}