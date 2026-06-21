from pydantic import BaseModel, EmailStr, Field
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
    tenant_id: UUID


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
    refresh_token: str
