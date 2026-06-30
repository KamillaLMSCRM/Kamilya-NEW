from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import hashlib

import argon2
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.core.auth import create_access_token, create_refresh_token, decode_token
from app.models.tenants import Tenant
from app.models.users import User
from app.models.user_roles import UserRole
from app.models.user_sessions import UserSession

ph = argon2.PasswordHasher()


def _hash_token(token: str) -> str:
    """SHA-256 hash for storing refresh tokens."""
    return hashlib.sha256(token.encode()).hexdigest()


async def _get_user_roles(db: AsyncSession, user_id: UUID, tenant_id: UUID) -> list[str]:
    result = await db.execute(
        select(UserRole.role).where(UserRole.user_id == user_id, UserRole.tenant_id == tenant_id)
    )
    return [row[0] for row in result.all()]


async def create_user_and_tokens(
    db: AsyncSession,
    tenant_id: UUID,
    email: str,
    first_name: str,
    last_name: str,
    password: str | None = None,
    role: str = "student",
) -> tuple[User, str, str]:
    password_hash = ph.hash(password) if password else None
    user = User(
        id=uuid4(),
        tenant_id=tenant_id,
        email=email,
        first_name=first_name,
        last_name=last_name,
        password_hash=password_hash,
        role=role,
        is_active=True,
        status="active",
    )
    db.add(user)
    await db.flush()

    # Create role entry
    user_role = UserRole(
        id=uuid4(),
        user_id=user.id,
        tenant_id=tenant_id,
        role=role,
    )
    db.add(user_role)
    await db.flush()

    roles = [role]
    access_token = create_access_token({
        "sub": str(user.id),
        "tenant_id": user.tenant_id,  # UUID or None — never str(None)
        "roles": roles,
    })
    refresh_token = create_refresh_token({
        "sub": str(user.id),
        "tenant_id": user.tenant_id,
    })
    return user, access_token, refresh_token


async def authenticate_user(db: AsyncSession, email: str, password: str) -> tuple[User, str, str]:
    """Authenticate by email + password.

    Tenant scoping (see audit §3.2):
        Email domain is matched against Tenant.slug. If a tenant matches,
        the user is looked up scoped to that tenant. If no tenant matches
        (e.g. someone registered with a non-tenant domain), we fall back
        to a global lookup BUT only for users with tenant_id IS NULL
        (superadmin/legacy). Tenant users can never be looked up without
        their tenant context — this prevents cross-tenant login by
        guessing the email of another tenant's user.
    """
    # Scope to tenant via email domain to prevent cross-tenant login
    email_domain = email.split("@")[-1] if "@" in email else ""
    tenant_result = await db.execute(select(Tenant).where(Tenant.slug == email_domain))
    tenant = tenant_result.scalar_one_or_none()

    if tenant:
        result = await db.execute(
            select(User).where(User.email == email, User.tenant_id == tenant.id)
        )
    else:
        # Restricted fallback: only superadmin-style users (tenant_id IS NULL)
        # can authenticate when their email domain does not match any tenant.
        # Tenant users with a mismatched domain are rejected here — they
        # must use the correct tenant-domain email to log in.
        result = await db.execute(
            select(User).where(User.email == email, User.tenant_id.is_(None))
        )

    user = result.scalar_one_or_none()
    if not user or not user.password_hash:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    try:
        ph.verify(user.password_hash, password)
    except argon2.exceptions.VerifyMismatchError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User inactive")

    # Update last_login
    user.last_login = datetime.now(timezone.utc)
    await db.flush()

    roles = await _get_user_roles(db, user.id, user.tenant_id)
    if not roles:
        roles = [user.role]

    access_token = create_access_token({
        "sub": str(user.id),
        "tenant_id": user.tenant_id,  # UUID or None — never str(None)
        "roles": roles,
    })
    refresh_token = create_refresh_token({
        "sub": str(user.id),
        "tenant_id": user.tenant_id,
    })
    return user, access_token, refresh_token


async def refresh_access_token(db: AsyncSession, refresh_token: str) -> tuple[str, str, User]:
    """Validate a refresh token and mint a fresh (access, refresh) pair.

    Returns (new_access_token, new_refresh_token, user). The new refresh
    token rotates the previous one — callers should treat the old token as
    invalidated (we don't have a blacklist mechanism yet; rotating
    reduces the window if a refresh token leaks). The User object is
    returned so the router can serialise it into TokenResponse.user —
    the frontend's _refresh() in apps/web/src/lib/api.ts requires
    data.user to exist or it never calls setAuth() and the next request
    is sent with a stale/null access token, producing a 401 → redirect
    to /login loop. (Lesson 17, 2026-06-30.)
    """
    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    user_id = UUID(payload["sub"])

    # Stateless refresh: verify JWT is valid and user exists
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    roles = await _get_user_roles(db, user.id, user.tenant_id)
    if not roles:
        roles = [user.role]

    # tenant_id is normalised to str/None by the JWT encoder (see
    # _json_safe_jwt_payload in app/core/auth.py). It accepts UUID
    # | str | None and emits the right shape for jwt.encode's stdlib
    # json.dumps. Direct callers don't need to str() it manually any more.
    new_access = create_access_token({
        "sub": str(user.id),
        "tenant_id": user.tenant_id,
        "roles": roles,
    })
    new_refresh = create_refresh_token({
        "sub": str(user.id),
        "tenant_id": user.tenant_id,
    })
    return new_access, new_refresh, user


async def blacklist_refresh_token(db: AsyncSession, refresh_token: str) -> None:
    """Delete the session by hashed token lookup."""
    token_hash = _hash_token(refresh_token)
    await db.execute(
        delete(UserSession).where(UserSession.refresh_token == token_hash)
    )
