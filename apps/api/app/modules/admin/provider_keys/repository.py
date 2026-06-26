"""DB queries for provider_keys — keeps SQL in one place."""
from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.provider_keys.models import ProviderKey


async def list_global_keys(db: AsyncSession) -> list[ProviderKey]:
    """Return all global (tenant_id IS NULL) keys, newest first."""
    result = await db.execute(
        select(ProviderKey)
        .where(ProviderKey.tenant_id.is_(None))
        .order_by(ProviderKey.created_at.desc())
    )
    return list(result.scalars().all())


async def get_key_by_id(db: AsyncSession, key_id: uuid.UUID) -> ProviderKey | None:
    result = await db.execute(
        select(ProviderKey).where(ProviderKey.id == key_id)
    )
    return result.scalar_one_or_none()


async def get_active_global_key(
    db: AsyncSession, provider: str
) -> ProviderKey | None:
    """Return the active global key for a provider, or None."""
    result = await db.execute(
        select(ProviderKey)
        .where(
            ProviderKey.tenant_id.is_(None),
            ProviderKey.provider == provider,
            ProviderKey.is_active.is_(True),
        )
        .order_by(ProviderKey.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def deactivate_existing(
    db: AsyncSession, provider: str, tenant_id: uuid.UUID | None
) -> None:
    """Mark any existing active key for this provider/tenant as inactive.

    Called when creating a new active key to enforce the
    'one active per (tenant, provider)' invariant.
    """
    await db.execute(
        update(ProviderKey)
        .where(
            ProviderKey.provider == provider,
            ProviderKey.tenant_id.is_(None) if tenant_id is None
            else ProviderKey.tenant_id == tenant_id,
            ProviderKey.is_active.is_(True),
        )
        .values(is_active=False)
    )


async def insert_key(db: AsyncSession, key: ProviderKey) -> ProviderKey:
    db.add(key)
    await db.flush()
    return key


async def delete_key(db: AsyncSession, key: ProviderKey) -> None:
    await db.delete(key)
    await db.flush()