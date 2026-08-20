from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User

from .domain import OrganizationHierarchyError
from .schemas import (
    OrganizationUnitArchive,
    OrganizationUnitCreate,
    OrganizationUnitResponse,
    OrganizationUnitTreeResponse,
    OrganizationUnitUpdate,
)
from .service import (
    UNASSIGNED_LEGACY_UNIT_ID,
    archive_organization_unit,
    build_tree,
    create_organization_unit,
    get_organization_unit,
    list_organization_units,
    load_structure_projections,
    update_organization_unit,
)

router = APIRouter(prefix="/organization-units", tags=["organization-units"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
Methodologist = Annotated[User, Depends(require_role("methodologist"))]


@router.get("/tree", response_model=OrganizationUnitTreeResponse)
async def get_organization_tree(
    db: DbSession,
    user: Methodologist,
):
    units = await list_organization_units(db, user.tenant_id)
    projections = await load_structure_projections(
        db,
        tenant_id=user.tenant_id,
        units=units,
    )
    unassigned_legacy_positions = projections.pop(UNASSIGNED_LEGACY_UNIT_ID, [])
    branches, legacy_roots = build_tree(units, positions_by_unit=projections)
    return OrganizationUnitTreeResponse(
        branches=branches,
        legacy_roots=legacy_roots,
        unassigned_legacy_positions=unassigned_legacy_positions,
        summary={
            "total_branches": len(branches),
            # ``department_count`` includes nested children; legacy roots are
            # counted as departments for compatibility with the old flat
            # structure endpoint.
            "total_departments": sum(branch["department_count"] for branch in branches) + len(legacy_roots),
            "total_positions": sum(node["position_count"] for node in (*branches, *legacy_roots))
            + len(unassigned_legacy_positions),
            "total_employees": sum(node["employee_count"] for node in (*branches, *legacy_roots))
            + sum(item["employee_count"] for item in unassigned_legacy_positions),
            "legacy_roots": len(legacy_roots),
            "unassigned_positions": len(unassigned_legacy_positions),
        },
    )


@router.post("", response_model=OrganizationUnitResponse, status_code=status.HTTP_201_CREATED)
async def create_unit(
    body: OrganizationUnitCreate,
    db: DbSession,
    user: Methodologist,
):
    try:
        unit = await create_organization_unit(
            db,
            tenant_id=user.tenant_id,
            name=body.name,
            unit_type=body.unit_type,
            parent_id=body.parent_id,
            external_key=body.external_key,
            description=body.description,
            code=body.code,
        )
    except OrganizationHierarchyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Organization unit already exists") from exc
    await db.commit()
    return unit


@router.get("/{unit_id}", response_model=OrganizationUnitResponse)
async def get_unit(
    unit_id: UUID,
    db: DbSession,
    user: Methodologist,
):
    try:
        return await get_organization_unit(db, user.tenant_id, unit_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Organization unit not found") from exc


@router.patch("/{unit_id}", response_model=OrganizationUnitResponse)
async def update_unit(
    unit_id: UUID,
    body: OrganizationUnitUpdate,
    db: DbSession,
    user: Methodologist,
):
    try:
        unit = await update_organization_unit(
            db,
            tenant_id=user.tenant_id,
            unit_id=unit_id,
            patch=body.model_dump(exclude_unset=True),
        )
        await db.commit()
        return unit
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail="Organization unit not found") from exc
    except (OrganizationHierarchyError, ValueError) as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Organization unit already exists") from exc


@router.post("/{unit_id}/archive", response_model=OrganizationUnitResponse)
async def archive_unit(
    unit_id: UUID,
    body: OrganizationUnitArchive,
    db: DbSession,
    user: Methodologist,
):
    try:
        unit = await archive_organization_unit(
            db,
            tenant_id=user.tenant_id,
            unit_id=unit_id,
            reason=body.reason,
        )
        await db.commit()
        return unit
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail="Organization unit not found") from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
