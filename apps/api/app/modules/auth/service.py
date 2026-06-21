from datetime import datetime, timedelta, timezone
from uuid import UUID

import argon2
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.core.auth import create_access_token, create_refresh_token
from app.models.users import User
from app.models.user_sessions import UserSession
from app.modules.auth.schemas import TokenResponse

ph = argon2.PasswordHasher()


async def authenticate_user(db: AsyncSession, email: str, password: str) -> tuple[User, str, str]:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user or not user.password_hash:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    try:
        ph.verify(user.password_hash, password)
    except argon2.exceptions.VerifyMismatchError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if user.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User inactive")

    access_token = create_access_token({"sub": str(user.id), "tenant_id": str(user.tenant_id), "roles": []})
    refresh_token = create_refresh_token({"sub": str(user.id), "tenant_id": str(user.tenant_id)})
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
    if not user or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return create_access_token({"sub": str(user.id), "tenant_id": str(user.tenant_id), "roles": []})


async def blacklist_refresh_token(db: AsyncSession, refresh_token: str) -> None:
    await db.execute(update(UserSession).where(UserSession.refresh_token == refresh_token).values(refresh_token=""))
