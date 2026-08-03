"""User management schemas"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class UserCreate(BaseModel):
    email: str
    first_name: str | None = None
    last_name: str | None = None
    role: str = "student"
    password: str | None = Field(default=None, min_length=8)
    is_active: bool = True

    @field_validator("password", mode="before")
    @classmethod
    def empty_password_is_missing(cls, value: object) -> object:
        """Let the router distinguish role assignment from account creation.

        The team form historically sent empty hidden fields while adding a
        role to an existing account. New accounts still require an eight
        character password through the field constraint and router check.
        """
        return None if value == "" else value


class UserUpdate(BaseModel):
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
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
    roles: list[str] = Field(default_factory=list)
    is_active: bool
    position_id: UUID | None = None
    telegram_id: int | None = None
    has_login_access: bool = False
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


class RoleAssignmentRequest(BaseModel):
    role: str


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
    delivery_status: str = "pending"
    delivery_message_id: str | None = None
    delivery_last_attempt_at: datetime | None = None
    delivery_attempt_count: int = 0
    delivery_failure_category: str | None = None
    delivery_failure_message: str | None = None


class InvitationSkipped(BaseModel):
    """Email not invited because of a conflict."""
    email: str
    reason: str  # 'already_has_access' | 'already_in_tenant' | 'pending_invite_exists' | 'email_taken_other_tenant'


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
    verification_method: str | None = None
    user_id: UUID | None = None
    delivery_status: str = "pending"
    delivery_message_id: str | None = None
    delivery_last_attempt_at: datetime | None = None
    delivery_attempt_count: int = 0
    delivery_failure_category: str | None = None
    delivery_failure_message: str | None = None


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
    email: str
    delivery_status: str = "pending"
    delivery_message_id: str | None = None
    delivery_last_attempt_at: datetime | None = None
    delivery_attempt_count: int = 0
    delivery_failure_category: str | None = None
    delivery_failure_message: str | None = None


class UserInvitationLinkResponse(BaseModel):
    """Fresh activation link bound to one exact tenant learner identity."""
    email: str
    invitation_id: UUID
    invite_url: str
    expires_at: datetime
    superseded_old_id: UUID | None = None
    delivery_status: str = "pending"
    delivery_message_id: str | None = None
    delivery_last_attempt_at: datetime | None = None
    delivery_attempt_count: int = 0
    delivery_failure_category: str | None = None
    delivery_failure_message: str | None = None


class InvitationPublicView(BaseModel):
    """Public view of an invitation (no auth). Used by /accept-invite page."""
    masked_email: str
    tenant_name: str
    role: str
    first_name: str
    last_name: str
    position_name: str | None = None
    course_titles: list[str] = Field(default_factory=list)
    expires_at: datetime
    valid: bool
    reason_if_invalid: str | None = None


class InvitationAcceptRequest(BaseModel):
    """Body of POST /invitations/{token}/accept (public)."""
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class InvitationCodeResponse(BaseModel):
    ok: bool = True
    expires_in: int = 300
    retry_after: int = 60


class InvitationAcceptResponse(BaseModel):
    """After successful accept — auto-login tokens."""
    user_id: UUID
    tenant_id: UUID
    role: str
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    user: dict
    next_url: str = "/student"
