"""Contracts for restricted external training-evidence package links."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ShareFormat = Literal["zip", "pdf"]


class EvidenceShareCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_ids: list[UUID] = Field(min_length=1, max_length=200)
    format: ShareFormat = "zip"
    expires_at: datetime
    max_downloads: int = Field(default=3, ge=1, le=100)


class EvidenceShareResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    format: ShareFormat
    package_sha256: str
    package_size_bytes: int
    source_event_count: int
    expires_at: datetime
    max_downloads: int
    download_count: int
    revoked_at: datetime | None
    created_at: datetime
    url: str | None = None


class EvidenceShareRevokeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    revoked_at: datetime


__all__ = [
    "EvidenceShareCreateRequest",
    "EvidenceShareResponse",
    "EvidenceShareRevokeResponse",
    "ShareFormat",
]
