"""Machine-token authentication for Staff Sync."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db

staff_sync_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class StaffSyncContext:
    credential_id: UUID
    tenant_id: UUID
    name: str
    scopes: tuple[str, ...]


def hash_staff_sync_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def require_staff_sync_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(staff_sync_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StaffSyncContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Staff Sync credential required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials.strip()
    if len(token) < 32:
        raise HTTPException(status_code=401, detail="Invalid Staff Sync credential")

    result = await db.execute(
        text("SELECT * FROM lookup_staff_sync_credential(:token_hash)"),
        {"token_hash": hash_staff_sync_token(token)},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=401, detail="Invalid Staff Sync credential")

    scopes = tuple(str(item) for item in (row["scopes"] or []))
    if "staff:sync" not in scopes:
        raise HTTPException(status_code=403, detail="Staff Sync scope is not allowed")

    tenant_id = UUID(str(row["tenant_id"]))
    await db.execute(text("SELECT set_current_tenant(:tenant_id)"), {"tenant_id": str(tenant_id)})
    return StaffSyncContext(
        credential_id=UUID(str(row["credential_id"])),
        tenant_id=tenant_id,
        name=str(row["credential_name"]),
        scopes=scopes,
    )
