"""Admin credential management and machine Staff Sync endpoint."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User

from .auth import StaffSyncContext, require_staff_sync_context
from .models import StaffSyncCredential
from .schemas import (
    StaffSyncCredentialCreate,
    StaffSyncCredentialCreated,
    StaffSyncCredentialStatus,
    StaffSyncEventRequest,
    StaffSyncEventResponse,
)
from .service import process_event, rotate_credential

router = APIRouter(prefix="/integrations/staff-sync", tags=["staff-sync"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
TenantAdmin = Annotated[User, Depends(require_role("admin", "superadmin"))]
MachineContext = Annotated[StaffSyncContext, Depends(require_staff_sync_context)]


@router.get("/credential", response_model=StaffSyncCredentialStatus | None)
async def credential_status(
    db: DbSession,
    user: TenantAdmin,
):
    if user.tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant is required")
    return await db.scalar(
        select(StaffSyncCredential)
        .where(
            StaffSyncCredential.tenant_id == user.tenant_id,
            StaffSyncCredential.revoked_at.is_(None),
        )
        .order_by(StaffSyncCredential.created_at.desc())
    )


@router.post("/credential", response_model=StaffSyncCredentialCreated, status_code=status.HTTP_201_CREATED)
async def create_or_rotate_credential(
    payload: StaffSyncCredentialCreate,
    db: DbSession,
    user: TenantAdmin,
):
    if user.tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant is required")
    return await rotate_credential(
        db,
        tenant_id=user.tenant_id,
        created_by=user.id,
        payload=payload,
    )


@router.delete("/credential/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_credential(
    credential_id: UUID,
    db: DbSession,
    user: TenantAdmin,
):
    if user.tenant_id is None:
        raise HTTPException(status_code=400, detail="Tenant is required")
    credential = await db.scalar(
        select(StaffSyncCredential).where(
            StaffSyncCredential.id == credential_id,
            StaffSyncCredential.tenant_id == user.tenant_id,
        )
    )
    if credential is None:
        raise HTTPException(status_code=404, detail="Staff Sync credential not found")
    credential.is_active = False
    credential.revoked_at = datetime.now(UTC)


@router.post("/events", response_model=StaffSyncEventResponse)
async def receive_staff_event(
    payload: StaffSyncEventRequest,
    db: DbSession,
    context: MachineContext,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
):
    if idempotency_key != payload.event_id:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "idempotency_key_mismatch",
                "message": "Idempotency-Key must match event_id",
            },
        )
    return await process_event(db, context, payload)
