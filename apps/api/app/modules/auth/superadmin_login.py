"""Superadmin (platform operator) authentication endpoint.

Distinct from /login because:

  * Superadmin rows have ``tenant_id IS NULL`` — they don't belong to any
    single tenant. /login would still find them via email fallback, but
    the resulting JWT would carry ``tenant_id='None'`` which trips up
    RLS context-setting in ``get_current_user``.
  * We want a separate login URL (``/superadmin/login`` in the frontend)
    so the superadmin flow is visually and semantically distinct from
    tenant-user login.
  * We deliberately do NOT support Telegram auth for superadmin in v1.
    The platform operator should use a strong password (Argon2) and
    ideally a hardware token via WebAuthn — that's a v1.1 follow-up.
"""
from datetime import datetime, timezone

import argon2
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_access_token, create_refresh_token
from app.core.db import get_db
from app.models.users import User
from app.modules.audit.service import log_action


router = APIRouter(prefix="/auth", tags=["auth"])

_ph = argon2.PasswordHasher()


class SuperadminLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=256)


class SuperadminLoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int = 900
    user: dict


@router.post("/superadmin-login", response_model=SuperadminLoginResponse)
async def superadmin_login(
    req: SuperadminLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Log in as platform superadmin.

    Rejects:
      * Unknown email
      * Wrong password
      * Non-superadmin role (defence-in-depth — never expose a tenant
        user's token via this endpoint)
      * Inactive users
    """
    import logging
    logger = logging.getLogger(__name__)

    result = await db.execute(
        select(User).where(User.email == req.email, User.tenant_id.is_(None))
    )
    user = result.scalar_one_or_none()
    if not user or not user.password_hash:
        # Same error for unknown email and missing hash — don't leak
        # which addresses exist.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    try:
        _ph.verify(user.password_hash, req.password)
    except (argon2.exceptions.VerifyMismatchError, argon2.exceptions.InvalidHashError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if user.role != "superadmin":
        # Defence in depth — only superadmin rows can use this endpoint.
        logger.warning(
            "superadmin-login attempted with non-superadmin row: %s (role=%s)",
            req.email, user.role,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a superadmin account",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive",
        )

    user.last_login = datetime.now(timezone.utc)
    await db.flush()

    # Build JWT — tenant_id=None is meaningful here (no RLS context set).
    access_token = create_access_token({
        "sub": str(user.id),
        "tenant_id": None,  # explicit — distinguishes from missing key
        "roles": ["superadmin"],
    })
    refresh_token = create_refresh_token({
        "sub": str(user.id),
        "tenant_id": None,
    })

    # AuditLog.tenant_id is NOT NULL — use a sentinel UUID for
    # platform-level (no-tenant) events so the existing schema keeps
    # working. Log filtering by tenant still excludes these rows.
    PLATFORM_SENTINEL = "00000000-0000-0000-0000-000000000000"
    await log_action(
        db, PLATFORM_SENTINEL, "superadmin.login", "user",
        resource_id=str(user.id), user_id=user.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()

    return SuperadminLoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user={
            "user_id": str(user.id),
            "tenant_id": None,
            "email": user.email,
            "telegram_id": user.telegram_id,
            "role": "superadmin",
            "full_name": f"{user.first_name} {user.last_name}",
            "tenant": None,  # superadmin has no tenant
        },
    )