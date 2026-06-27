"""Pydantic schemas for tenant_integrations API."""

from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr
from typing import Literal, Optional


Channel = Literal["smtp", "telegram", "whatsapp"]


# ── WhatsApp ──────────────────────────────────────────────────────────────


class WhatsAppStatus(BaseModel):
    """Status of tenant's WhatsApp connection — returned by GET /status."""
    status: str  # not_started | persisted | initializing | qr_pending | connected | disconnected | logged_out
    phone_number: Optional[str] = None
    qr: Optional[str] = None  # base64 PNG
    qr_expires_at: Optional[datetime] = None


# ── SMTP ─────────────────────────────────────────────────────────────────


class SMTPConfig(BaseModel):
    """SMTP credentials supplied by the tenant admin.

    `password` is required on create (we encrypt + store).
    On update it's optional — if omitted, we keep the existing encrypted password.
    """
    host: str = Field(..., min_length=3, max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=1024)
    from_addr: EmailStr
    from_name: str = Field(default="", max_length=255)
    use_tls: bool = True


class SMTPConfigUpdate(BaseModel):
    """Update payload — password optional."""
    host: Optional[str] = Field(None, min_length=3, max_length=255)
    port: Optional[int] = Field(None, ge=1, le=65535)
    username: Optional[str] = Field(None, min_length=1, max_length=255)
    password: Optional[str] = Field(None, min_length=1, max_length=1024)
    from_addr: Optional[EmailStr] = None
    from_name: Optional[str] = Field(None, max_length=255)
    use_tls: Optional[bool] = None


# ── Telegram ─────────────────────────────────────────────────────────────


class TelegramConfig(BaseModel):
    """Telegram bot token — created by the tenant via @BotFather."""
    bot_token: str = Field(..., min_length=20, max_length=200,
                           pattern=r"^\d+:[A-Za-z0-9_-]+$")


# ── Common ───────────────────────────────────────────────────────────────


class IntegrationSummary(BaseModel):
    """Lightweight view for the integrations list page."""
    channel: Channel
    is_active: bool
    last_test_at: Optional[datetime] = None
    last_test_status: Optional[str] = None
    has_secret: bool = False  # whether password/token is configured
    updated_at: datetime
    # Channel-specific status (e.g. WhatsApp connected/disconnected)
    extra: dict = Field(default_factory=dict)


class TestResult(BaseModel):
    """Result of a test connection."""
    ok: bool
    detail: str = ""
    timestamp: datetime


class WhatsAppInitResult(BaseModel):
    """Returned by POST /integrations/whatsapp/init."""
    status: str  # connected | qr_pending | initializing
    qr: Optional[str] = None
    phone_number: Optional[str] = None
    mock: bool = False