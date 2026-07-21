"""Staff import mappings CRUD router — P0.4 first-tenant hardening.

Reusable per-tenant column mappings. After a methodologist verifies a
mapping for one Excel file, they save it under a memorable name (e.g.
"Штатка АО КазМунайГаз") and the next upload of the same file
template skips the column-picking step entirely.

Endpoints (all under /admin/staff/import/mappings):

  GET    /                  list mappings for current tenant (default first)
  POST   /                  create new mapping
  GET    /{mapping_id}      read one mapping
  PATCH  /{mapping_id}      update name / mapping_json / is_default
  DELETE /{mapping_id}      delete mapping

Auth: admin / org_admin / methodologist.
Tenant scope: from JWT, never from URL/body.
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User
from app.modules.users.staff_import_mapping_schemas import (
    StaffImportMappingCreate,
    StaffImportMappingResponse,
    StaffImportMappingUpdate,
)
from app.modules.users.staff_import_mapping_service import (
    MappingNameConflict,
    create_mapping,
    delete_mapping,
    list_mappings,
    update_mapping,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/staff/import/mappings",
    tags=["staff-import"],
)

_MAPPING_ROLES = ("superadmin", "methodologist")


@router.get("", response_model=list[StaffImportMappingResponse])
async def list_staff_import_mappings(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_MAPPING_ROLES)),
):
    """List all saved column mappings for the current tenant.

    Default mapping (if any) is returned first, then newest first.
    """
    if user.tenant_id is None:
        return []
    mappings = await list_mappings(db, user.tenant_id)
    return mappings


@router.post("", response_model=StaffImportMappingResponse, status_code=status.HTTP_201_CREATED)
async def create_staff_import_mapping(
    body: StaffImportMappingCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_MAPPING_ROLES)),
):
    if user.tenant_id is None:
        raise HTTPException(status_code=400, detail="superadmin cannot save mappings")
    try:
        m = await create_mapping(
            db,
            tenant_id=user.tenant_id,
            created_by=user.id,
            name=body.name,
            mapping_json=body.mapping_json,
            is_default=body.is_default,
        )
        await db.commit()
        return m
    except MappingNameConflict:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Mapping with name «{body.name}» already exists for this tenant",
        )


@router.get("/{mapping_id}", response_model=StaffImportMappingResponse)
async def get_staff_import_mapping(
    mapping_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_MAPPING_ROLES)),
):
    from app.models.staff_import_mapping import StaffImportMapping
    from sqlalchemy import select

    if user.tenant_id is None:
        raise HTTPException(status_code=404, detail="Mapping not found")
    result = await db.execute(
        select(StaffImportMapping).where(
            StaffImportMapping.id == mapping_id,
            StaffImportMapping.tenant_id == user.tenant_id,
        )
    )
    m = result.scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="Mapping not found")
    return m


@router.patch("/{mapping_id}", response_model=StaffImportMappingResponse)
async def update_staff_import_mapping(
    mapping_id: UUID,
    body: StaffImportMappingUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_MAPPING_ROLES)),
):
    if user.tenant_id is None:
        raise HTTPException(status_code=404, detail="Mapping not found")
    patch = body.model_dump(exclude_unset=True)
    try:
        m = await update_mapping(db, user.tenant_id, mapping_id, patch)
    except MappingNameConflict as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Mapping with name «{e}» already exists for this tenant",
        )
    if m is None:
        raise HTTPException(status_code=404, detail="Mapping not found")
    await db.commit()
    return m


@router.delete("/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_staff_import_mapping(
    mapping_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_MAPPING_ROLES)),
):
    if user.tenant_id is None:
        raise HTTPException(status_code=404, detail="Mapping not found")
    ok = await delete_mapping(db, user.tenant_id, mapping_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Mapping not found")
    await db.commit()
    return None
