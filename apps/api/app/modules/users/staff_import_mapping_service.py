"""Service layer for staff_import_mappings CRUD.

Per AGENTS.md architecture:
- Repository → SQL helpers (this file)
- Service → business rules (tenant scope, unique name per tenant)
- Router → HTTP envelope

We only enforce uniqueness on (tenant_id, name) here. The DB has the
unique index as a second line of defense — if the service layer
somehow misses a race, the DB rejects and we surface a 409.
"""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.staff_import_mapping import StaffImportMapping

logger = logging.getLogger(__name__)


class MappingNameConflict(Exception):
    """Raised when a mapping with the same name already exists for the tenant."""


async def list_mappings(
    db: AsyncSession,
    tenant_id: UUID,
) -> list[StaffImportMapping]:
    """List all mappings for a tenant, default first, then newest first."""
    result = await db.execute(
        select(StaffImportMapping)
        .where(StaffImportMapping.tenant_id == tenant_id)
        .order_by(
            StaffImportMapping.is_default.desc(),
            StaffImportMapping.created_at.desc(),
        )
    )
    return result.scalars().all()


async def get_default_mapping(
    db: AsyncSession,
    tenant_id: UUID,
) -> StaffImportMapping | None:
    """Return the default mapping for a tenant, if any."""
    result = await db.execute(
        select(StaffImportMapping)
        .where(
            StaffImportMapping.tenant_id == tenant_id,
            StaffImportMapping.is_default.is_(True),
        )
        .order_by(StaffImportMapping.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_mapping(
    db: AsyncSession,
    tenant_id: UUID,
    created_by: UUID,
    name: str,
    mapping_json: dict,
    is_default: bool = False,
) -> StaffImportMapping:
    """Create a new mapping. If is_default=True, demote any previous default."""
    if is_default:
        await _clear_default_flag(db, tenant_id)

    m = StaffImportMapping(
        tenant_id=tenant_id,
        name=name.strip(),
        mapping_json=mapping_json or {},
        is_default=is_default,
        created_by=created_by,
    )
    db.add(m)
    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        raise MappingNameConflict(name) from e
    await db.refresh(m)
    return m


async def update_mapping(
    db: AsyncSession,
    tenant_id: UUID,
    mapping_id: UUID,
    patch: dict,
) -> StaffImportMapping | None:
    """Apply a partial update. None if mapping doesn't exist for tenant."""
    result = await db.execute(
        select(StaffImportMapping).where(
            StaffImportMapping.id == mapping_id,
            StaffImportMapping.tenant_id == tenant_id,
        )
    )
    m = result.scalar_one_or_none()
    if m is None:
        return None

    new_is_default = patch.get("is_default")
    if new_is_default is True:
        await _clear_default_flag(db, tenant_id)

    for field in ("name", "mapping_json", "is_default"):
        if field in patch and patch[field] is not None:
            setattr(m, field, patch[field])
    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        raise MappingNameConflict(patch.get("name", m.name)) from e
    await db.refresh(m)
    return m


async def delete_mapping(
    db: AsyncSession,
    tenant_id: UUID,
    mapping_id: UUID,
) -> bool:
    """Delete a mapping. Returns False if not found for tenant."""
    result = await db.execute(
        select(StaffImportMapping).where(
            StaffImportMapping.id == mapping_id,
            StaffImportMapping.tenant_id == tenant_id,
        )
    )
    m = result.scalar_one_or_none()
    if m is None:
        return False
    await db.delete(m)
    await db.flush()
    return True


async def _clear_default_flag(db: AsyncSession, tenant_id: UUID) -> None:
    """Demote any existing default mapping for the tenant.

    Done as a single UPDATE rather than fetching + setting in Python so
    it scales even if a tenant accumulates many mappings.
    """
    from sqlalchemy import update

    await db.execute(
        update(StaffImportMapping)
        .where(
            StaffImportMapping.tenant_id == tenant_id,
            StaffImportMapping.is_default.is_(True),
        )
        .values(is_default=False)
    )