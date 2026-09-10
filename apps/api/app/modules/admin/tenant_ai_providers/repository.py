"""Tenant-scoped persistence operations for BYOK settings."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.tenant_ai_providers.models import TenantAIProvider


async def list_for_tenant(db: AsyncSession, tenant_id: uuid.UUID) -> list[TenantAIProvider]:
    result = await db.execute(select(TenantAIProvider).where(TenantAIProvider.tenant_id == tenant_id).order_by(TenantAIProvider.purpose))
    return list(result.scalars().all())


async def get_for_tenant(db: AsyncSession, tenant_id: uuid.UUID, purpose: str) -> TenantAIProvider | None:
    result = await db.execute(select(TenantAIProvider).where(TenantAIProvider.tenant_id == tenant_id, TenantAIProvider.purpose == purpose))
    return result.scalar_one_or_none()


async def upsert_for_tenant(db: AsyncSession, *, tenant_id: uuid.UUID, purpose: str, values: dict[str, object]) -> TenantAIProvider:
    statement = insert(TenantAIProvider).values(tenant_id=tenant_id, purpose=purpose, **values).on_conflict_do_update(
        constraint="uq_tenant_ai_providers_tenant_purpose",
        set_={**values, "updated_at": func.now()},
    ).returning(TenantAIProvider)
    return (await db.execute(statement)).scalar_one()


async def delete_for_tenant(db: AsyncSession, tenant_id: uuid.UUID, purpose: str) -> bool:
    row = await get_for_tenant(db, tenant_id, purpose)
    if row is None:
        return False
    await db.delete(row)
    return True
