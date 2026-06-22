"""User management schemas"""
from pydantic import BaseModel, Field
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


class UserResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    email: str
    first_name: str
    last_name: str
    role: str
    is_active: bool
    position_id: UUID | None = None
    telegram_id: str | None = None
    last_login: datetime | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int
    page: int
    per_page: int


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=8)
