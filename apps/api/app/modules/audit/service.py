"""Audit log service"""
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.users import User
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
    # audit_logs.resource_id is VARCHAR(100) by contract because audited
    # resources are not uniformly UUID-backed.  Normalising to text preserves
    # UUIDs and external/string identifiers without weakening query typing.
    rid = str(resource_id) if resource_id is not None else None
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
    query = (
        select(AuditLog, User.email, User.first_name, User.last_name)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(AuditLog.tenant_id == tenant_id)
    )

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
    entries: list[AuditLog] = []
    for entry, email, first_name, last_name in result.all():
        entry.actor_email = email
        entry.actor_name = f"{first_name or ''} {last_name or ''}".strip() or None
        entries.append(entry)
    return entries


async def get_audit_stats(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
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
    yesterday = datetime.now(UTC) - timedelta(hours=24)
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
