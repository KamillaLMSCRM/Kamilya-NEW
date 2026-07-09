"""Schemas for /admin/staff/import/mappings CRUD."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StaffImportMappingCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    mapping_json: dict[str, Any] = Field(
        ...,
        description="Canonical field → raw column name. Example: {'personnel_number': 'Табельный №'}",
    )
    is_default: bool = False

    model_config = ConfigDict(extra="forbid")


class StaffImportMappingUpdate(BaseModel):
    """PATCH body. All fields optional."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    mapping_json: dict[str, Any] | None = None
    is_default: bool | None = None

    model_config = ConfigDict(extra="forbid")


class StaffImportMappingResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    mapping_json: dict[str, Any]
    is_default: bool
    created_by: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)