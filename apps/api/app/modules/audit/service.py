"""Audit log service"""
from uuid import UUID
from datetime import datetime
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from app.modules.audit.models import AuditLog


async def log_action(
    db: AsyncSession,
    tenant_id: UUID,
    action: str,
    resource_type: str,
    resource_id: str | UUID | None = None,
    user_id: UUID | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    """Log an audit event."""
    rid = None
    if resource_id is not None:
        if isinstance(resource_id, UUID):
            rid = resource_id
        else:
            # Try to parse as UUID; fallback to None so non-UUID ids (e.g. slugs) still log
            try:
                rid = UUID(str(resource_id))
            except (ValueError, TypeError):
                rid = None
    entry = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=rid,
        details=details,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(entry)
    await db.flush()
    return entry


async def get_audit_logs(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditLog]:
    """Get audit logs with filters."""
    query = select(AuditLog).where(AuditLog.tenant_id == tenant_id)

    if user_id:
        query = query.where(AuditLog.user_id == user_id)
    if action:
        query = query.where(AuditLog.action == action)
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    if start_date:
        query = query.where(AuditLog.created_at >= start_date)
    if end_date:
        query = query.where(AuditLog.created_at <= end_date)

    query = query.order_by(desc(AuditLog.created_at)).offset(offset).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()


async def get_audit_stats(db: AsyncSession, tenant_id: UUID) -> dict:
    """Get audit statistics for a tenant."""
    total_result = await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.tenant_id == tenant_id)
    )
    total = total_result.scalar() or 0

    # Top actions
    actions_result = await db.execute(
        select(AuditLog.action, func.count(AuditLog.id).label("count"))
        .where(AuditLog.tenant_id == tenant_id)
        .group_by(AuditLog.action)
        .order_by(desc("count"))
        .limit(10)
    )
    top_actions = [{"action": row[0], "count": row[1]} for row in actions_result.all()]

    # Top resources
    resources_result = await db.execute(
        select(AuditLog.resource_type, func.count(AuditLog.id).label("count"))
        .where(AuditLog.tenant_id == tenant_id)
        .group_by(AuditLog.resource_type)
        .order_by(desc("count"))
        .limit(10)
    )
    top_resources = [{"resource": row[0], "count": row[1]} for row in resources_result.all()]

    # Recent activity (last 24h)
    from datetime import timedelta
    yesterday = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_result = await db.execute(
        select(func.count(AuditLog.id)).where(
            AuditLog.tenant_id == tenant_id,
            AuditLog.created_at >= yesterday,
        )
    )
    recent_24h = recent_result.scalar() or 0

    return {
        "total_events": total,
        "recent_24h": recent_24h,
        "top_actions": top_actions,
        "top_resources": top_resources,
    }
