"""Bounded pre-tenant resolution and server-owned creation context.

No commit, token issuance or authorization decision. Callers retain their
existing login/registration verification; DB helpers never expose a Tenant row.
"""

from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenants import Tenant


async def lookup_tenant_id_by_slug(db: AsyncSession, slug: str) -> UUID | None:
    result = await db.execute(text("SELECT lookup_tenant_id_by_slug(:slug)"), {"slug": slug})
    value = result.scalar_one_or_none()
    return UUID(str(value)) if value is not None else None


async def get_bootstrap_tenant(db: AsyncSession, slug: str) -> Tenant | None:
    tenant_id = await lookup_tenant_id_by_slug(db, slug)
    if tenant_id is None:
        return None
    await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)})
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    return result.scalar_one_or_none()


async def bind_new_tenant(db: AsyncSession, tenant: Tenant) -> None:
    """Allocate server ID and bind context BEFORE caller adds/flushes new row."""
    if tenant.id is not None:
        raise ValueError("New tenant ID must be server allocated")
    tenant.id = uuid4()
    await db.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant.id)})
