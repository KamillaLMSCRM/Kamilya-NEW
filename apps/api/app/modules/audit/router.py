"""Audit log API router"""
from datetime import datetime
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User
from app.modules.audit.models import AuditLog
from app.modules.audit.schemas import AuditLogResponse
from app.modules.audit.service import get_audit_logs, get_audit_stats

router = APIRouter(prefix="/audit", tags=["audit"])
AuditSession = Annotated[AsyncSession, Depends(get_db)]
AuditAdmin = Annotated[User, Depends(require_role("admin"))]


@router.get("/logs", response_model=list[AuditLogResponse])
async def list_logs(
    db: AuditSession,
    user: AuditAdmin,
    user_id: UUID | None = Query(None),
    action: str | None = Query(None),
    resource_type: str | None = Query(None),
    start_date: datetime | None = Query(None),
    end_date: datetime | None = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
) -> list[AuditLog]:
    """Get audit logs with filters."""
    return await get_audit_logs(
        db=db,
        tenant_id=cast(UUID, user.tenant_id),
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )


@router.get("/stats")
async def stats(
    db: AuditSession,
    user: AuditAdmin,
) -> dict[str, Any]:
    """Get audit statistics."""
    return await get_audit_stats(db, cast(UUID, user.tenant_id))
