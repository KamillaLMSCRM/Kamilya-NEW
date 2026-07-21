from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import hashlib

import argon2
from sqlalchemy import select, delete, text
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


async def get_user_roles(db: AsyncSession, user: User) -> list[str]:
    """Return assigned roles with the user's primary role first."""
    if user.tenant_id is None:
        return [user.role]

    result = await db.execute(
        select(UserRole.role).where(
            UserRole.user_id == user.id,
            UserRole.tenant_id == user.tenant_id,
        )
    )
    assigned = {row[0] for row in result.all()}
    assigned.add(user.role)
    return [user.role, *sorted(assigned - {user.role})]


async def build_user_payload(
    db: AsyncSession,
    user: User,
    telegram_id: str | int | None = None,
    active_role: str | None = None,
) -> dict:
    """Build the user_data dict that the frontend AuthUser shape expects.

    Single source of truth for serialising a User ORM row into the
    shape consumed by apps/web/src/lib/auth.ts::AuthUser. Used by:

      - telegram.py webhook (after /check-code verification)
      - service.py::refresh_access_token (so /refresh returns the
        same shape and the frontend can update its in-memory user
        without losing role/tenant/full_name)

    The shape is:
        {
            user_id: str,           # UUID
            tenant_id: str | None,  # UUID or None (superadmin-style)
            tenant: dict | None,    # {id, name, slug, is_demo, plan} or None
            telegram_id: str | int,
            role: str,
            full_name: str,
            email: str | None,
            first_name: str,
            last_name: str,
        }

    Assigned roles are returned as an array. ``role`` is the active role for
    the current session and defaults to the user's primary role.
    """
    roles = await get_user_roles(db, user)
    role = active_role if active_role in roles else user.role

    # Tenant: load via Tenant table if user has tenant_id, else None.
    tenant_payload: dict | None = None
    if user.tenant_id is not None:
        tenant_row = (
            await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
        ).scalar_one_or_none()
        if tenant_row is not None:
            tenant_payload = {
                "id": str(tenant_row.id),
                "name": tenant_row.name,
                "slug": tenant_row.slug,
                "is_demo": bool(tenant_row.is_demo),
                "plan": tenant_row.plan,
            }

    return {
        "user_id": str(user.id),
        # tenant_id stays a str() for the frontend. Note this differs
        # from auth_sessions.py which keeps it as a UUID inside Redis
        # (UUID-aware encoder) and only stringifies at the JSON boundary.
        "tenant_id": str(user.tenant_id) if user.tenant_id is not None else None,
        "telegram_id": str(telegram_id) if telegram_id is not None else None,
        "role": role,
        "roles": roles,
        "full_name": f"{user.first_name or ''} {user.last_name or ''}".strip() or (user.email or ""),
        "tenant": tenant_payload,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
    }


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
    # RLS bypass: the `tenant_isolation` policy on `users` checks
    # `current_setting('app.tenant_id', true)`. Before INSERT this session
    # variable is NULL (the caller hasn't set tenant context yet because we
    # just created the tenant row), so the policy evaluates
    # `tenant_id = NULL` = UNKNOWN and denies the INSERT.
    # Setting it as a *local* (true) config here keeps the value scoped to
    # the current transaction — safe for PgBouncer transaction-mode pool.
    # Same pattern as auth/telegram_register.py:136.
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )
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
        "active_role": role,
    })
    refresh_token = create_refresh_token({
        "sub": str(user.id),
        "tenant_id": user.tenant_id,
        "active_role": role,
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
        await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant.id)})
        result = await db.execute(
            select(User).where(User.email == email, User.tenant_id == tenant.id)
        )
        user = result.scalar_one_or_none()
    else:
        # Legacy tenants may have a slug that is not the email domain (for
        # example slug=demo and admin@demo.kml). Resolve such an address only
        # when it is globally unambiguous; duplicate addresses across tenants
        # remain rejected instead of guessing a tenant context.
        await db.execute(text("SELECT set_config('app.auth_lookup', 'true', true)"))
        result = await db.execute(
            select(User).where(User.email == email)
        )
        matches = result.scalars().all()
        user = matches[0] if len(matches) == 1 else None
        await db.execute(text("SELECT set_config('app.auth_lookup', 'false', true)"))
        if user and user.tenant_id is not None:
            await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(user.tenant_id)})
    if not user or not user.password_hash:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    try:
        ph.verify(user.password_hash, password)
    except argon2.exceptions.VerifyMismatchError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User inactive")

    # Tenant users can update their own row under tenant RLS. A superadmin
    # has tenant_id=NULL and must be handled through the explicit
    # superadmin-session RLS context; a plain password login must not issue a
    # zero-row UPDATE and turn a valid login into StaleDataError.
    if user.tenant_id is not None:
        user.last_login = datetime.now(timezone.utc)
        await db.flush()

    roles = await get_user_roles(db, user)
    active_role = user.role

    access_token = create_access_token({
        "sub": str(user.id),
        "tenant_id": user.tenant_id,  # UUID or None — never str(None)
        "roles": roles,
        "active_role": active_role,
    })
    refresh_token = create_refresh_token({
        "sub": str(user.id),
        "tenant_id": user.tenant_id,
        "active_role": active_role,
    })
    return user, access_token, refresh_token


async def refresh_access_token(db: AsyncSession, refresh_token: str) -> tuple[str, str, dict]:
    """Validate a refresh token and mint a fresh (access, refresh) pair.

    Returns (new_access_token, new_refresh_token, user_payload). The
    user_payload is a dict in the AuthUser shape (see
    build_user_payload) so the frontend's setAuth() can persist it.
    """
    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    user_id = UUID(payload["sub"])
    tenant_id = payload.get("tenant_id")

    if tenant_id:
        await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": tenant_id})

    # Stateless refresh: verify JWT is valid and user exists
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    roles = await get_user_roles(db, user)
    requested_role = payload.get("active_role")
    active_role = requested_role if requested_role in roles else user.role

    new_access = create_access_token({
        "sub": str(user.id),
        "tenant_id": user.tenant_id,
        "roles": roles,
        "active_role": active_role,
    })
    new_refresh = create_refresh_token({
        "sub": str(user.id),
        "tenant_id": user.tenant_id,
        "active_role": active_role,
    })
    user_payload = await build_user_payload(db, user, telegram_id=None, active_role=active_role)
    return new_access, new_refresh, user_payload


async def blacklist_refresh_token(db: AsyncSession, refresh_token: str) -> None:
    """Delete the session by hashed token lookup."""
    token_hash = _hash_token(refresh_token)
    await db.execute(
        delete(UserSession).where(UserSession.refresh_token == token_hash)
    )
