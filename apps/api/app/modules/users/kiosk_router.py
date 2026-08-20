"""Kiosk link endpoints — admin CRUD + public identify flow.

Stage 1b of employee onboarding epic.

Endpoints:
- Admin (auth required):
    GET    /admin/kiosks                    list tenant kiosk links
    POST   /admin/kiosks                    create
    PATCH  /admin/kiosks/{id}               toggle active, edit name/location
    DELETE /admin/kiosks/{id}               delete

- Public (no auth):
    GET   /kiosks/{token}                    view kiosk (name, scope, etc.)
    POST  /kiosks/{token}/identify           body: {personnel_number} → returns
                                              user identity + assigned courses
"""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User
from app.modules.users.kiosk_service import (
    create_kiosk_link,
    delete_kiosk_link,
    establish_public_kiosk_tenant_context,
    get_public_kiosk,
    identify_at_kiosk,
    issue_kiosk_user_pin,
    list_kiosk_access_logs,
    list_kiosk_links,
    list_kiosk_pin_users,
    update_kiosk_link,
)

admin_router = APIRouter(prefix="/admin/kiosks", tags=["kiosks-admin"])


# ── Admin CRUD ────────────────────────────────────────────────────


class KioskLinkCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    scope_position_id: UUID | None = None
    expires_at: datetime | None = None


class KioskLinkUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    expires_at: datetime | None = None


class KioskLinkResponse(BaseModel):
    id: UUID
    name: str
    token: str
    kiosk_url: str
    location: str | None = None
    scope_position_id: UUID | None = None
    scope_position_name: str | None = None
    is_active: bool
    expires_at: datetime | None = None
    created_at: datetime


class KioskAccessLogResponse(BaseModel):
    id: UUID
    kiosk_id: UUID
    kiosk_name: str
    user_id: UUID | None = None
    personnel_number_masked: str | None = None
    success: bool
    reason: str | None = None
    ip_address: str | None = None
    created_at: datetime


class KioskScopePositionResponse(BaseModel):
    id: UUID
    name: str
    department: str | None = None


class KioskPinUserResponse(BaseModel):
    user_id: UUID
    full_name: str
    personnel_number_masked: str | None = None
    has_kiosk_pin: bool


class KioskPinIssueResponse(BaseModel):
    user_id: UUID
    personnel_number_masked: str | None = None
    temporary_pin: str
    issued_at: datetime


def _to_response(link, base_url: str, scope_position_name: str | None = None) -> dict:
    base = (base_url or "https://app.kml.kz").rstrip("/")
    return {
        "id": link.id,
        "name": link.name,
        "token": link.token,
        "kiosk_url": f"{base}/kiosk/{link.token}",
        "location": link.location,
        "scope_position_id": link.scope_position_id,
        "scope_position_name": scope_position_name,
        "is_active": link.is_active,
        "expires_at": link.expires_at,
        "created_at": link.created_at,
    }


@admin_router.post("", response_model=KioskLinkResponse, status_code=201)
async def create_kiosk(
    payload: KioskLinkCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "superadmin")),
):
    """Create a new kiosk link."""
    from app.core.config import get_settings
    settings = get_settings()
    base_url = getattr(settings, "PUBLIC_URL", None)

    pos_name = None
    if payload.scope_position_id:
        from app.modules.positions.models import Position

        result = await db.execute(
            Position.__table__.select().where(
                Position.id == payload.scope_position_id,
                Position.tenant_id == user.tenant_id,
            )
        )
        position = result.first()
        if position is None:
            raise HTTPException(status_code=404, detail="Position not found")
        pos_name = position.name

    link_data = await create_kiosk_link(
        db,
        tenant_id=user.tenant_id,
        created_by=user.id,
        name=payload.name,
        location=payload.location,
        scope_position_id=payload.scope_position_id,
        expires_at=payload.expires_at,
        base_url=base_url,
    )

    return {
        **link_data,
        "scope_position_name": pos_name,
    }


@admin_router.get("/scope-positions", response_model=list[KioskScopePositionResponse])
async def list_kiosk_scope_positions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "superadmin")),
):
    """List the tenant positions an administrator may use to scope a kiosk."""
    from app.modules.positions.models import Position

    result = await db.execute(
        Position.__table__.select()
        .where(Position.tenant_id == user.tenant_id)
        .order_by(Position.name.asc())
    )
    return [
        {
            "id": row.id,
            "name": row.name,
            "department": row.department,
        }
        for row in result
    ]


@admin_router.get("", response_model=list[KioskLinkResponse])
async def list_kiosks(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "superadmin")),
):
    """List all kiosk links for current tenant, newest first."""
    from app.core.config import get_settings
    settings = get_settings()
    base_url = getattr(settings, "PUBLIC_URL", None)

    links = await list_kiosk_links(db, user.tenant_id)

    # Pre-fetch position names (1 query for all)
    pos_ids = {l.scope_position_id for l in links if l.scope_position_id}
    pos_names = {}
    if pos_ids:
        from app.modules.positions.models import Position
        result = await db.execute(
            Position.__table__.select().where(Position.id.in_(pos_ids))
        )
        for row in result.fetchall():
            pos_names[row[0]] = row[1]  # id -> name (positional)

    return [
        _to_response(l, base_url, pos_names.get(l.scope_position_id))
        for l in links
    ]


@admin_router.get("/access-logs", response_model=list[KioskAccessLogResponse])
async def kiosk_access_logs(
    kiosk_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "superadmin")),
):
    """Latest kiosk identify attempts for current tenant."""
    return await list_kiosk_access_logs(db, user.tenant_id, kiosk_id=kiosk_id, limit=limit)


@admin_router.get("/pin-users", response_model=list[KioskPinUserResponse])
async def kiosk_pin_users(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "superadmin")),
):
    """List active tenant learners that can receive a kiosk-only PIN."""
    return await list_kiosk_pin_users(db, user.tenant_id)


@admin_router.post("/pin-users/{user_id}/issue", response_model=KioskPinIssueResponse, status_code=201)
async def issue_kiosk_pin(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "superadmin")),
):
    """Issue or rotate a learner's kiosk PIN; clear PIN is returned once."""
    result = await issue_kiosk_user_pin(
        db,
        tenant_id=user.tenant_id,
        user_id=user_id,
        issued_by=user.id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Eligible learner not found")
    return result


@admin_router.patch("/{kiosk_id}", response_model=KioskLinkResponse)
async def update_kiosk(
    kiosk_id: UUID,
    payload: KioskLinkUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "superadmin")),
):
    """Toggle active, edit name/location/position scope."""
    from app.core.config import get_settings
    settings = get_settings()
    base_url = getattr(settings, "PUBLIC_URL", None)

    patch = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    link = await update_kiosk_link(db, user.tenant_id, kiosk_id, patch)
    if not link:
        raise HTTPException(status_code=404, detail="Kiosk not found")

    pos_name = None
    if link.scope_position_id:
        from app.modules.positions.models import Position
        pos = await db.get(Position, link.scope_position_id)
        pos_name = pos.name if pos else None

    return _to_response(link, base_url, pos_name)


@admin_router.delete("/{kiosk_id}", status_code=204)
async def delete_kiosk(
    kiosk_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "superadmin")),
):
    """Delete a kiosk link."""
    ok = await delete_kiosk_link(db, user.tenant_id, kiosk_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    return None


# ── Public endpoints ─────────────────────────────────────────────

public_router = APIRouter(prefix="/kiosks", tags=["kiosks-public"])


class KioskPublicView(BaseModel):
    name: str
    tenant_name: str
    scope_position_name: str | None = None
    location: str | None = None
    valid: bool
    reason_if_invalid: str | None = None


class KioskIdentifyRequest(BaseModel):
    personnel_number: str = Field(..., min_length=1, max_length=64)
    pin: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class KioskIdentifyResponse(BaseModel):
    user: dict
    kiosk_name: str
    kiosk_location: str | None = None
    courses: list[dict]
    # Per TZ §3.5: kiosk identify must return a JWT so the
    # worker can actually open courses. Pre-fix the response
    # was missing both fields and the course player (which
    # requires auth) bounced the worker back to login.
    access_token: str
    token_type: str = "bearer"


@public_router.get("/{token}", response_model=KioskPublicView)
async def view_kiosk(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public view of a kiosk (no auth). Worker sees the welcome screen."""
    tenant_id = await establish_public_kiosk_tenant_context(db, token)
    if tenant_id is None:
        return {
            "name": "",
            "tenant_name": "",
            "valid": False,
            "reason_if_invalid": "kiosk_not_found",
        }
    result = await get_public_kiosk(db, token)
    return result


@public_router.post("/{token}/identify", response_model=KioskIdentifyResponse)
async def identify_kiosk(
    token: str,
    request: Request,
    payload: KioskIdentifyRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Exchange a tab number plus separately issued PIN for kiosk course access.

    The kiosk URL is public and the personnel number is only an identifier.
    The PIN is a separate per-user credential with server-side lockout.
    """
    tenant_id = await establish_public_kiosk_tenant_context(db, token)
    if tenant_id is None:
        raise HTTPException(status_code=404, detail="Kiosk not found")
    result = await identify_at_kiosk(
        db,
        token,
        payload.personnel_number,
        payload.pin,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return result
