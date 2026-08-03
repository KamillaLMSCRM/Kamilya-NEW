"""API contracts for tenant-configurable procedure definitions."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProcedureType = Literal["acknowledgement", "internal_attestation", "admission_decision"]
ProcedureStatus = Literal["draft", "active", "retired"]
ConfirmationMethod = Literal["manual_record", "email_otp"]


_PROCEDURE_CODE_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,99}\Z")


def _clean_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    return value


def _normalize_code(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("code must be a string")
    normalized = re.sub(r"\s+", "-", value.strip().lower())
    if not _PROCEDURE_CODE_PATTERN.fullmatch(normalized):
        raise ValueError("code must match [a-z0-9][a-z0-9._-]{0,99}; use lowercase ASCII and hyphens")
    return normalized


class TrainingProcedureCreate(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    procedure_type: ProcedureType
    confirmation_method: ConfirmationMethod
    approval_reference: str | None = Field(default=None, max_length=255)
    approval_date: date | None = None
    approved_by_name: str | None = Field(default=None, max_length=255)
    legal_basis: str | None = Field(default=None, max_length=5000)
    local_basis: str | None = Field(default=None, max_length=5000)
    retention_class: str | None = Field(default=None, max_length=100)
    retention_days: int | None = Field(default=None, ge=1)
    commission_snapshot_rules: dict[str, Any] | None = None
    authorized_decision_rules: dict[str, Any] | None = None

    _normalize_procedure_code = field_validator("code", mode="before")(_normalize_code)
    _strip_title = field_validator("title", mode="before")(_clean_text)


class TrainingProcedureUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    confirmation_method: ConfirmationMethod | None = None
    approval_reference: str | None = Field(default=None, max_length=255)
    approval_date: date | None = None
    approved_by_name: str | None = Field(default=None, max_length=255)
    legal_basis: str | None = Field(default=None, max_length=5000)
    local_basis: str | None = Field(default=None, max_length=5000)
    retention_class: str | None = Field(default=None, max_length=100)
    retention_days: int | None = Field(default=None, ge=1)
    commission_snapshot_rules: dict[str, Any] | None = None
    authorized_decision_rules: dict[str, Any] | None = None


class TrainingProcedureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    code: str
    version: int
    title: str
    description: str
    procedure_type: ProcedureType
    status: ProcedureStatus
    approval_reference: str | None
    approval_date: date | None
    approved_by_name: str | None
    legal_basis: str | None
    local_basis: str | None
    confirmation_method: ConfirmationMethod
    retention_class: str | None
    retention_days: int | None
    commission_snapshot_rules: dict[str, Any] | None
    authorized_decision_rules: dict[str, Any] | None
    created_by_user_id: UUID
    updated_by_user_id: UUID
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None
    retired_at: datetime | None


class TrainingProcedureListResponse(BaseModel):
    items: list[TrainingProcedureResponse]
    total: int
