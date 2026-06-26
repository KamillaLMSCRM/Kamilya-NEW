"""HTTP endpoints for superadmin tenant + admin management.

All endpoints require role=superadmin. Tenant IDs are path params (UUID).

Action audit logging uses prefix `superadmin.*` so they're filterable
from the standard /v1/audit endpoint.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User
from app.modules.admin.superadmin.schemas import (
    AdminCreate,
    AdminResponse,
    AdminUpdate,
    TenantCreate,
    TenantListResponse,
    TenantResponse,
    TenantStats,
    TenantUpdate,
)
from app.modules.admin.superadmin.service import SuperadminService
from app.modules.audit.service import log_action

router = APIRouter(
    prefix="/admin/super",
    tags=["admin", "superadmin"],
)


def _service(db: AsyncSession = Depends(get_db)) -> SuperadminService:
    return SuperadminService(db)


# ── Tenants ────────────────────────────────────────────────────────────


@router.get("/tenants", response_model=TenantListResponse)
async def list_tenants(
    search: Annotated[str | None, Query(description="Search by name or slug")] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_role("superadmin")),
    svc: SuperadminService = Depends(_service),
):
    tenants, total = await svc.list_tenants(search=search, limit=limit, offset=offset)
    return TenantListResponse(
        tenants=[TenantResponse.model_validate(t) for t in tenants],
        total=total,
    )


@router.post("/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    payload: TenantCreate,
    request: Request,
    user: User = Depends(require_role("superadmin")),
    svc: SuperadminService = Depends(_service),
):
    try:
        tenant = await svc.create_tenant(payload)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    await log_action(
        svc.db, tenant.id, "superadmin.tenant.created", "tenant",
        resource_id=tenant.id, user_id=user.id,
        details={"name": tenant.name, "slug": tenant.slug, "plan": tenant.plan},
        ip_address=request.client.host if request.client else None,
    )
    return TenantResponse.model_validate(tenant)


@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: uuid.UUID,
    user: User = Depends(require_role("superadmin")),
    svc: SuperadminService = Depends(_service),
):
    tenant = await svc.get_tenant(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    response = TenantResponse.model_validate(tenant)
    response.stats = await svc.get_tenant_stats(tenant_id)
    return response


@router.patch("/tenants/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: uuid.UUID,
    payload: TenantUpdate,
    request: Request,
    user: User = Depends(require_role("superadmin")),
    svc: SuperadminService = Depends(_service),
):
    try:
        tenant = await svc.update_tenant(tenant_id, payload)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    await log_action(
        svc.db, tenant.id, "superadmin.tenant.updated", "tenant",
        resource_id=tenant.id, user_id=user.id,
        details=payload.model_dump(exclude_none=True),
        ip_address=request.client.host if request.client else None,
    )
    return TenantResponse.model_validate(tenant)


# ── Admins within a tenant ─────────────────────────────────────────────


@router.get(
    "/tenants/{tenant_id}/admins",
    response_model=list[AdminResponse],
)
async def list_admins(
    tenant_id: uuid.UUID,
    user: User = Depends(require_role("superadmin")),
    svc: SuperadminService = Depends(_service),
):
    if await svc.get_tenant(tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    admins = await svc.list_admins(tenant_id)
    return [AdminResponse.model_validate(a) for a in admins]


@router.post(
    "/tenants/{tenant_id}/admins",
    response_model=AdminResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin(
    tenant_id: uuid.UUID,
    payload: AdminCreate,
    request: Request,
    user: User = Depends(require_role("superadmin")),
    svc: SuperadminService = Depends(_service),
):
    if await svc.get_tenant(tenant_id) is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    try:
        new_user, invite = await svc.create_admin(
            tenant_id, payload, superadmin_id=user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await log_action(
        svc.db, tenant_id, "superadmin.admin.created", "user",
        resource_id=new_user.id, user_id=user.id,
        details={
            "email": payload.email, "telegram_id": payload.telegram_id,
            "role": payload.role, "invite_sent": invite is not None,
        },
        ip_address=request.client.host if request.client else None,
    )
    return AdminResponse.model_validate(new_user)


@router.patch(
    "/tenants/{tenant_id}/admins/{user_id}",
    response_model=AdminResponse,
)
async def update_admin(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: AdminUpdate,
    request: Request,
    user: User = Depends(require_role("superadmin")),
    svc: SuperadminService = Depends(_service),
):
    try:
        target = await svc.update_admin(tenant_id, user_id, payload)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await log_action(
        svc.db, tenant_id, "superadmin.admin.updated", "user",
        resource_id=user_id, user_id=user.id,
        details=payload.model_dump(exclude_none=True),
        ip_address=request.client.host if request.client else None,
    )
    return AdminResponse.model_validate(target)


@router.delete(
    "/tenants/{tenant_id}/admins/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def deactivate_admin(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_role("superadmin")),
    svc: SuperadminService = Depends(_service),
):
    try:
        await svc.deactivate_admin(tenant_id, user_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await log_action(
        svc.db, tenant_id, "superadmin.admin.deactivated", "user",
        resource_id=user_id, user_id=user.id,
        ip_address=request.client.host if request.client else None,
    )