"""User management schemas"""
from pydantic import BaseModel, Field, EmailStr
from uuid import UUID
from datetime import datetime


class UserCreate(BaseModel):
    email: str
    first_name: str
    last_name: str
    role: str = "student"
    password: str = Field(min_length=8)
    is_active: bool = True


class UserUpdate(BaseModel):
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    role: str | None = None
    is_active: bool | None = None


class TenantSummary(BaseModel):
    """Lightweight tenant info embedded in user/auth responses so the
    frontend knows the sandbox/plan context without a separate fetch."""
    id: UUID
    name: str
    slug: str
    is_demo: bool = False
    plan: str = "free"


class UserResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    email: str | None = None
    personnel_number: str | None = None
    first_name: str
    last_name: str
    role: str
    is_active: bool
    position_id: UUID | None = None
    telegram_id: int | None = None
    last_login: datetime | None = None
    created_at: datetime
    # Optional tenant context — populated by routers that load Tenant.
    tenant: TenantSummary | None = None
    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int
    page: int
    per_page: int


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=8)


# ── Invitations (Phase 1 of employee onboarding epic) ──────────


class InvitationCreateItem(BaseModel):
    """One email to invite. first_name/last_name collected at accept time, not now."""
    email: str = Field(..., max_length=320)


class InvitationBulkCreateRequest(BaseModel):
    """Bulk-create invitations. Max 200 per request."""
    items: list[InvitationCreateItem] = Field(..., min_length=1, max_length=200)


class InvitationCreated(BaseModel):
    """Successfully created invitation."""
    email: str
    invitation_id: UUID
    invite_url: str
    expires_at: datetime
    personnel_number: str | None = None  # included if HR provided one (used as soft 2FA)


class InvitationSkipped(BaseModel):
    """Email not invited because of a conflict."""
    email: str
    reason: str  # 'already_in_tenant' | 'pending_invite_exists' | 'email_taken_other_tenant'


class InvitationInvalid(BaseModel):
    """Email failed validation."""
    input: str
    reason: str  # 'invalid_email'


class InvitationBulkCreateResponse(BaseModel):
    created: list[InvitationCreated] = []
    skipped_existing: list[InvitationSkipped] = []
    invalid: list[InvitationInvalid] = []


class InvitationListItem(BaseModel):
    """One row for /users/invitations listing."""
    id: UUID
    email: str
    personnel_number: str | None = None
    role: str
    status: str
    invited_by: UUID
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None = None
    accepted_ip: str | None = None
    accepted_user_agent: str | None = None
    user_id: UUID | None = None


class InvitationListResponse(BaseModel):
    items: list[InvitationListItem]
    total: int
    page: int
    per_page: int


class InvitationResendResponse(BaseModel):
    """Response to /users/invitations/{id}/resend — new token row created."""
    invitation_id: UUID
    invite_url: str
    expires_at: datetime
    superseded_old_id: UUID


class InvitationPublicView(BaseModel):
    """Public view of an invitation (no auth). Used by /accept-invite page."""
    email: str
    tenant_name: str
    role: str
    expires_at: datetime
    valid: bool
    reason_if_invalid: str | None = None
    requires_personnel_number: bool = False  # True if HR set personnel_number (soft 2FA)


class InvitationAcceptRequest(BaseModel):
    """Body of POST /invitations/{token}/accept (public)."""
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)
    personnel_number: str | None = Field(default=None, max_length=64)  # required only if invitation has it


class InvitationAcceptResponse(BaseModel):
    """After successful accept — auto-login tokens."""
    user_id: UUID
    tenant_id: UUID
    role: str
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
