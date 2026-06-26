"""Pydantic schemas for provider_keys endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class ProviderKeyCreate(BaseModel):
    """POST /v1/admin/provider-keys — create a new key."""

    provider: str = Field(..., description="One of: 'deepseek', 'voyage'")
    api_key: str = Field(..., min_length=8, max_length=512)
    label: str | None = Field(None, max_length=128)
    is_active: bool = True

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        allowed = {"deepseek", "voyage"}
        if v not in allowed:
            raise ValueError(f"provider must be one of {sorted(allowed)}")
        return v


class ProviderKeyUpdate(BaseModel):
    """PATCH /v1/admin/provider-keys/{id} — partial update."""

    api_key: str | None = Field(None, min_length=8, max_length=512)
    label: str | None = Field(None, max_length=128)
    is_active: bool | None = None


class ProviderKeyResponse(BaseModel):
    """Single provider key. The plaintext key is NEVER returned."""

    id: uuid.UUID
    provider: str
    label: str | None
    is_active: bool
    key_preview: str = Field(
        ..., description="Masked preview, e.g. 'sk-***def456'"
    )
    source: str = Field(
        ...,
        description="Where the key comes from: 'db' (this row) or 'env' (env var)",
    )
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None
    last_error: str | None

    model_config = {"from_attributes": True}


class ProviderKeyListResponse(BaseModel):
    """GET /v1/admin/provider-keys — list of known providers with status."""

    providers: list[ProviderKeyResponse]


class ProviderKeyTestResult(BaseModel):
    """POST /v1/admin/provider-keys/{id}/test — probe the key against the API."""

    ok: bool
    latency_ms: int | None = None
    error: str | None = None
    provider: str