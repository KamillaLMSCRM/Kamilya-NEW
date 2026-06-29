from pydantic import BaseModel, EmailStr, Field, field_validator
from uuid import UUID
from datetime import datetime


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=63)


class TenantResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    status: str
    plan: str
    settings: dict
    created_at: datetime
    updated_at: datetime

    model_config = {'from_attributes': True}


class UserCreate(BaseModel):
    email: EmailStr
    telegram_id: int | None = None
    password: str = Field(..., min_length=8)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    email: str | None
    telegram_id: int | None
    first_name: str
    last_name: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {'from_attributes': True}


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = 'bearer'
    expires_in: int


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TelegramLoginRequest(BaseModel):
    telegram_id: int = Field(..., gt=0)
    first_name: str = Field(..., min_length=1)
    last_name: str | None = None
    auth_date: datetime


class RefreshRequest(BaseModel):
    # Optional because the httpOnly refresh cookie carries the token by
    # default (see apps/api/app/modules/auth/router.py::_read_refresh_cookie_or_body).
    # The body field is kept only as a legacy fallback for clients that
    # don't share the cookie origin.
    refresh_token: str | None = None
