"""HTTP endpoints for provider_keys — superadmin only."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User
from app.modules.admin.provider_keys.schemas import (
    ProviderKeyCreate,
    ProviderKeyListResponse,
    ProviderKeyResponse,
    ProviderKeyTestResult,
    ProviderKeyUpdate,
)
from app.modules.admin.provider_keys.service import ProviderKeyService

router = APIRouter(prefix="/admin/provider-keys", tags=["admin", "provider-keys"])


def _service(db: AsyncSession = Depends(get_db)) -> ProviderKeyService:
    return ProviderKeyService(db)


@router.get("", response_model=ProviderKeyListResponse)
async def list_provider_keys(
    user: User = Depends(require_role("superadmin")),
    svc: ProviderKeyService = Depends(_service),
):
    """List all global provider keys (superadmin only).

    Returns the masked preview only — never the plaintext API key.
    """
    return await svc.list_providers()


@router.post("", response_model=ProviderKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_provider_key(
    payload: ProviderKeyCreate,
    user: User = Depends(require_role("superadmin")),
    svc: ProviderKeyService = Depends(_service),
):
    """Create a new provider key.

    If `is_active=true` (default), any existing active key for the same
    provider is deactivated. Plaintext `api_key` is encrypted with Fernet
    before being persisted and is never returned.
    """
    try:
        return await svc.create_key(payload, user_id=user.id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create provider key: {type(e).__name__}",
        ) from e


@router.patch("/{key_id}", response_model=ProviderKeyResponse)
async def update_provider_key(
    key_id: uuid.UUID,
    payload: ProviderKeyUpdate,
    user: User = Depends(require_role("superadmin")),
    svc: ProviderKeyService = Depends(_service),
):
    try:
        return await svc.update_key(key_id, payload)
    except LookupError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_key(
    key_id: uuid.UUID,
    user: User = Depends(require_role("superadmin")),
    svc: ProviderKeyService = Depends(_service),
):
    try:
        await svc.delete_key(key_id)
    except LookupError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e


@router.post("/{key_id}/test", response_model=ProviderKeyTestResult)
async def test_provider_key(
    key_id: uuid.UUID,
    user: User = Depends(require_role("superadmin")),
    svc: ProviderKeyService = Depends(_service),
):
    """Probe the provider API to confirm the stored key works.

    Updates last_used_at and last_error on the row regardless of outcome.
    """
    try:
        return await svc.test_key(key_id)
    except LookupError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e