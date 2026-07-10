"""Audit log schemas"""
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Any


class AuditLogResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    user_id: UUID | None = None
    action: str
    resource_type: str
    # resource_id is stored as UUID in the DB but historically callers
    # pass non-UUID slugs (e.g. tenant slugs) which the service layer
    # normalizes to None. Accept either type so we don't 500 on serialize.
    resource_id: UUID | str | None = None
    details: dict[str, Any] | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


class AuditLogFilter(BaseModel):
    user_id: UUID | None = None
    action: str | None = None
    resource_type: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    limit: int = 100
    offset: int = 0
