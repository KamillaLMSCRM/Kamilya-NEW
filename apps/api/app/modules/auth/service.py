from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import argon2
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.core.auth import create_access_token, create_refresh_token
from app.models.users import User
from app.models.user_roles import UserRole
from app.models.user_sessions import UserSession

ph = argon2.PasswordHasher()


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
        "tenant_id": str(user.tenant_id),
        "roles": roles,
    })
    refresh_token = create_refresh_token({
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
    })
    return user, access_token, refresh_token


async def authenticate_user(db: AsyncSession, email: str, password: str) -> tuple[User, str, str]:
    result = await db.execute(select(User).where(User.email == email))
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
        "tenant_id": str(user.tenant_id),
        "roles": roles,
    })
    refresh_token = create_refresh_token({
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
    })
    return user, access_token, refresh_token


async def refresh_access_token(db: AsyncSession, refresh_token: str) -> str:
    from app.core.auth import decode_token

    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    user_id = UUID(payload["sub"])
    session = (await db.execute(select(UserSession).where(UserSession.refresh_token == refresh_token))).scalar_one_or_none()
    if not session or session.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    roles = await _get_user_roles(db, user.id, user.tenant_id)
    if not roles:
        roles = [user.role]

    return create_access_token({
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "roles": roles,
    })


async def blacklist_refresh_token(db: AsyncSession, refresh_token: str) -> None:
    await db.execute(
        update(UserSession)
        .where(UserSession.refresh_token == refresh_token)
        .values(refresh_token="")
    )
