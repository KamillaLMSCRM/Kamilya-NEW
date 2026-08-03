"""API contracts for retention policy management and purge execution."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

ProcedureType = Literal[
    "acknowledgement",
    "training",
    "knowledge_check",
    "internal_attestation",
    "admission_decision",
]
PURGE_CONFIRMATION_TOKEN = "PURGE_TRAINING_EVIDENCE"


class TrainingRetentionPolicyCreate(BaseModel):
    procedure_type: ProcedureType
    retention_days: int = Field(ge=1, le=36500)
    legal_basis: str | None = Field(default=None, max_length=5000)
    local_basis: str | None = Field(default=None, max_length=5000)
    active: bool = False

    @model_validator(mode="after")
    def active_policy_requires_basis(self) -> TrainingRetentionPolicyCreate:
        if self.active and not (self.legal_basis and self.legal_basis.strip()) and not (
            self.local_basis and self.local_basis.strip()
        ):
            raise ValueError("Active retention policy requires legal_basis or local_basis")
        return self


class TrainingRetentionPolicyUpdate(BaseModel):
    retention_days: int | None = Field(default=None, ge=1, le=36500)
    legal_basis: str | None = Field(default=None, max_length=5000)
    local_basis: str | None = Field(default=None, max_length=5000)
    active: bool | None = None


class TrainingRetentionPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    procedure_type: ProcedureType
    retention_days: int
    legal_basis: str | None
    local_basis: str | None
    active: bool
    created_by_user_id: UUID
    updated_by_user_id: UUID
    created_at: datetime
    updated_at: datetime


class TrainingRetentionPolicyListResponse(BaseModel):
    items: list[TrainingRetentionPolicyResponse]
    total: int


class RetentionPurgeRequest(BaseModel):
    dry_run: bool = True
    confirmation_token: str | None = Field(default=None, max_length=100)
    reauth_password: str | None = Field(default=None, min_length=1, max_length=256)
    max_roots: int = Field(default=100, ge=1, le=100)


class RetentionPurgeResponse(BaseModel):
    dry_run: bool
    scan_budget: int = 0
    roots_scanned: int
    truncated: bool = False
    eligible_roots: int
    purged_roots: int
    purged_events: int
    purged_confirmations: int
    purged_hold_history: int
    purged_shares: int
    reason_counts: dict[str, int]
    generated_at: datetime

    @property
    def aggregate(self) -> dict[str, Any]:
        return {
            "scan_budget": self.scan_budget,
            "roots_scanned": self.roots_scanned,
            "truncated": self.truncated,
            "eligible_roots": self.eligible_roots,
            "purged_roots": self.purged_roots,
        }
