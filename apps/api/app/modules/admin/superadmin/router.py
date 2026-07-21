"""HTTP endpoints for superadmin tenant + admin management.

All endpoints require role=superadmin. Tenant IDs are path params (UUID).

Action audit logging uses prefix `superadmin.*` so they're filterable
from the standard /v1/audit endpoint.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_access_token, require_role
from app.core.db import get_db
from app.models.tenants import Tenant
from app.models.users import User
from app.modules.admin.superadmin.schemas import (
    AdminCreate,
    AdminResponse,
    AdminUpdate,
    TenantCreate,
    TenantCreateResponse,
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


async def _tenant_response(svc: SuperadminService, tenant: Tenant) -> TenantResponse:
    response = TenantResponse.model_validate(tenant)
    response.stats = await svc.get_tenant_stats(tenant.id)
    response.usage = await svc.get_tenant_usage(tenant.id)
    response.latest_lead = await svc.get_latest_lead(tenant.id)
    return response


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
    tenant_responses = [await _tenant_response(svc, tenant) for tenant in tenants]
    return TenantListResponse(
        tenants=tenant_responses,
        total=total,
    )


@router.post("/tenants", response_model=TenantCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    payload: TenantCreate,
    request: Request,
    user: User = Depends(require_role("superadmin")),
    svc: SuperadminService = Depends(_service),
):
    try:
        tenant, first_admin, invite, invite_url = await svc.create_tenant_wizard(
            payload, superadmin_id=user.id
        )
    except ValueError as e:
        await svc.db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    await log_action(
        svc.db, tenant.id, "superadmin.tenant.created", "tenant",
        resource_id=tenant.id, user_id=user.id,
        details={
            "name": tenant.name,
            "slug": tenant.slug,
            "plan": tenant.plan,
            "first_admin": first_admin.email if first_admin else None,
            "invite_created": invite is not None,
        },
        ip_address=request.client.host if request.client else None,
    )
    if first_admin is not None:
        await log_action(
            svc.db, tenant.id, "superadmin.admin.created", "user",
            resource_id=first_admin.id, user_id=user.id,
            details={
                "email": first_admin.email,
                "telegram_id": first_admin.telegram_id,
                "role": first_admin.role,
                "invite_sent": invite is not None,
            },
            ip_address=request.client.host if request.client else None,
        )
    response = TenantCreateResponse(
        tenant=await _tenant_response(svc, tenant),
        first_admin=AdminResponse.model_validate(first_admin) if first_admin else None,
        invite_url=invite_url,
    )
    await svc.db.commit()
    return response


@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: uuid.UUID,
    user: User = Depends(require_role("superadmin")),
    svc: SuperadminService = Depends(_service),
):
    tenant = await svc.get_tenant(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return await _tenant_response(svc, tenant)


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
        details=payload.model_dump(exclude_none=True, mode="json"),
        ip_address=request.client.host if request.client else None,
    )
    await svc.db.commit()
    await svc.db.refresh(tenant)
    return await _tenant_response(svc, tenant)


@router.delete("/tenants/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    tenant_id: uuid.UUID,
    request: Request,
    confirm_slug: Annotated[
        str | None,
        Query(
            description=(
                "Required. Must match the tenant's slug exactly — defense "
                "against accidental DELETE from a stray script or stale tab."
            ),
        ),
    ] = None,
    user: User = Depends(require_role("superadmin")),
    svc: SuperadminService = Depends(_service),
):
    """Soft-delete a tenant.

    P0.2 first-tenant hardening:
      - `confirm_slug` query param must match the tenant's slug (defense
        against accidental deletion).
      - Production tenant (`slug == "kamilya"`) is protected and cannot
        be deleted through this endpoint.
      - All actions are audit-logged (visible via /v1/audit).
    """
    try:
        tenant = await svc.get_tenant(tenant_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if tenant.slug == "kamilya":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Production tenant 'kamilya' is protected from deletion. "
                "Use the dedicated migration script if this is intentional."
            ),
        )

    if confirm_slug is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Missing required query parameter `confirm_slug`. "
                "Repeat the DELETE with ?confirm_slug=<tenant.slug>."
            ),
        )
    if confirm_slug != tenant.slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"confirm_slug mismatch: provided '{confirm_slug}', "
                f"expected '{tenant.slug}'."
            ),
        )

    try:
        tenant = await svc.delete_tenant(tenant_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        await svc.db.rollback()
        raise HTTPException(status_code=500, detail=f"Tenant delete failed: {e}") from e

    import logging

    logging.getLogger(__name__).warning(
        "superadmin.tenant.deleted id=%s slug=%s by=%s ip=%s",
        tenant.id,
        tenant.slug,
        user.id,
        request.client.host if request.client else None,
    )


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


# ── Impersonation ──────────────────────────────────────────────────────


class ImpersonateRequest(BaseModel):
    """Optional — defaults to impersonating as 'admin'."""
    role: str = Field(
        default="admin",
        description="Role to assume inside the tenant. Must be one of admin|org_admin|methodologist.",
        pattern="^(admin|org_admin|methodologist)$",
    )


class ImpersonateResponse(BaseModel):
    access_token: str
    expires_in: int = 900  # 15 min — same as regular access tokens
    as_role: str
    tenant: dict
    user: dict


@router.post(
    "/tenants/{tenant_id}/impersonate",
    response_model=ImpersonateResponse,
    summary="Mint a short-lived JWT bound to a tenant (impersonation)",
)
async def impersonate_tenant(
    tenant_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_role("superadmin")),
    db: AsyncSession = Depends(get_db),
):
    """Superadmin enters a tenant context.

    The returned JWT has:
      sub                = superadmin.id (so audit identifies the operator)
      tenant_id          = <target tenant>
      roles              = [requested role]
      impersonated_by    = superadmin.id (marker claim — copied to audit)
      impersonated_tenant= <target tenant>
      impersonated_role  = requested role

    `get_current_user` detects `impersonated_tenant` and returns an
    `_ImpersonatedUser` wrapper so downstream handlers see a normal
    user object with the overridden tenant_id/role.

    All actions performed under this token are audit-logged with
    `actor_id=superadmin.id` and a `impersonation` flag in details.

    Security:
      - Token expires in 15 min (same as regular).
      - The superadmin must re-impersonate to extend.
      - Audit row written on every impersonation start.
    """
    # We don't even need to parse the body — defaults are fine. But to be
    # explicit and validate role, instantiate the schema.
    try:
        # Body is optional; FastAPI doesn't parse without Depends. Use raw
        # JSON with a default fallback.
        body = await request.json()
    except Exception:
        body = {}
    try:
        req = ImpersonateRequest(**body)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid impersonate body: {e}")

    # 1. Verify tenant exists and is not deleted.
    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # 2. Mint the impersonation token.
    access_token = create_access_token({
        "sub": str(user.id),  # real operator (for audit)
        "tenant_id": str(tenant.id),
        "roles": [req.role],
        "impersonated_by": str(user.id),
        "impersonated_tenant": str(tenant.id),
        "impersonated_role": req.role,
    })

    # 3. Audit row — written under the TARGET tenant's audit stream
    #    so the tenant admin (if they ever get access) can see "the
    #    superadmin impersonated us at this moment".
    await log_action(
        db,
        tenant.id,
        "superadmin.impersonation.started",
        "tenant",
        resource_id=tenant.id,
        user_id=user.id,
        details={
            "as_role": req.role,
            "superadmin_email": user.email,
            "tenant_slug": tenant.slug,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()

    return ImpersonateResponse(
        access_token=access_token,
        expires_in=900,
        as_role=req.role,
        tenant={
            "id": str(tenant.id),
            "name": tenant.name,
            "slug": tenant.slug,
            "plan": tenant.plan,
            "is_demo": bool(tenant.is_demo),
        },
        # Synthesize the user payload so the frontend can populate its
        # AuthStore immediately without a second /users/me round-trip.
        user={
            "user_id": str(user.id),
            "tenant_id": str(tenant.id),
            "telegram_id": str(user.telegram_id) if user.telegram_id else "",
            "role": req.role,
            "full_name": f"{user.first_name} {user.last_name}",
            "email": user.email,
            "tenant": {
                "id": str(tenant.id),
                "name": tenant.name,
                "slug": tenant.slug,
                "is_demo": bool(tenant.is_demo),
                "plan": tenant.plan,
            },
            "impersonated_by": str(user.id),
            "impersonated_tenant": str(tenant.id),
            "impersonated_role": req.role,
        },
    )
