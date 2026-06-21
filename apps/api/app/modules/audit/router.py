"""Audit log API router"""
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.auth import get_current_user
from app.core.db import get_db
from app.modules.audit.schemas import AuditLogResponse, AuditLogFilter
from app.modules.audit.service import get_audit_logs, get_audit_stats

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/logs", response_model=list[AuditLogResponse])
async def list_logs(
    user_id: Optional[UUID] = Query(None),
    action: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get audit logs with filters."""
    return await get_audit_logs(
        db=db,
        tenant_id=user.tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        limit=limit,
        offset=offset,
    )


@router.get("/stats")
async def stats(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get audit statistics."""
    return await get_audit_stats(db, user.tenant_id)
