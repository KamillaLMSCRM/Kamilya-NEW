"""Public contracts for tenant Staff Sync."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

StaffSyncAction = Literal["upsert", "terminate", "reactivate"]


class StaffSyncEmployeeInput(BaseModel):
    personnel_number: str = Field(..., min_length=1, max_length=64)
    first_name: str = Field(..., min_length=1, max_length=120)
    last_name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=64)
    hire_date: date | None = None
    position_external_key: str | None = Field(default=None, min_length=1, max_length=200)

    model_config = ConfigDict(extra="forbid")


class StaffSyncEventRequest(BaseModel):
    event_id: str = Field(..., min_length=1, max_length=200)
    source: str = Field(..., min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    action: StaffSyncAction
    external_employee_id: str = Field(..., min_length=1, max_length=200)
    effective_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    employee: StaffSyncEmployeeInput | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_action_payload(self) -> StaffSyncEventRequest:
        if self.action == "upsert" and self.employee is None:
            raise ValueError("employee is required for upsert")
        return self


class StaffSyncEventResponse(BaseModel):
    event_id: str
    action: StaffSyncAction
    status: str
    employee_id: UUID | None = None
    external_employee_id: str
    changed_fields: list[str] = Field(default_factory=list)
    error_code: str | None = None
    message: str | None = None
    replayed: bool = False


class StaffSyncCredentialCreate(BaseModel):
    name: str = Field(default="HR integration", min_length=3, max_length=120)
    expires_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class StaffSyncCredentialCreated(BaseModel):
    id: UUID
    name: str
    token: str
    scopes: list[str]
    expires_at: datetime | None = None
    created_at: datetime


class StaffSyncCredentialStatus(BaseModel):
    id: UUID
    name: str
    scopes: list[str]
    is_active: bool
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
