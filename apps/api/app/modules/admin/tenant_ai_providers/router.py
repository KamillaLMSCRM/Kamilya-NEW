"""Tenant-admin HTTP adapter for BYOK configuration; registered by root."""
from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User
from app.modules.admin.tenant_ai_providers.schemas import (
    TenantAIProviderListResponse,
    TenantAIProviderResponse,
    TenantAIProviderUpdate,
)
from app.modules.admin.tenant_ai_providers.service import TenantAIProviderService


class TenantAIProviderRoute(APIRoute):
    """Keep BYOK request-validation details, including write-only keys, private."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original_handler = super().get_route_handler()

        async def safe_validation_handler(request: Request) -> Response:
            try:
                return await original_handler(request)
            except RequestValidationError:
                return JSONResponse(
                    status_code=422,
                    content={
                        "error": "validation_error",
                        "message": "Invalid AI provider configuration",
                    },
                )

        return safe_validation_handler


router = APIRouter(
    prefix="/admin/ai-providers",
    tags=["admin", "ai-providers"],
    route_class=TenantAIProviderRoute,
)
TenantAdmin = Depends(require_role("admin", "superadmin"))


def _service(db: AsyncSession = Depends(get_db)) -> TenantAIProviderService:  # noqa: B008
    return TenantAIProviderService(db)


@router.get("", response_model=TenantAIProviderListResponse)
async def list_ai_providers(
    user: User = TenantAdmin,
    service: TenantAIProviderService = Depends(_service),  # noqa: B008
) -> TenantAIProviderListResponse:
    if user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant_context_required")
    return await service.list(cast(UUID, user.tenant_id))


@router.put("/{purpose}", response_model=TenantAIProviderResponse)
async def put_ai_provider(
    purpose: str,
    payload: TenantAIProviderUpdate,
    user: User = TenantAdmin,
    service: TenantAIProviderService = Depends(_service),  # noqa: B008
) -> TenantAIProviderResponse:
    if user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant_context_required")
    try:
        return await service.put(cast(UUID, user.tenant_id), purpose, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None


@router.delete("/{purpose}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ai_provider(
    purpose: str,
    user: User = TenantAdmin,
    service: TenantAIProviderService = Depends(_service),  # noqa: B008
) -> Response:
    if user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant_context_required")
    try:
        await service.delete(cast(UUID, user.tenant_id), purpose)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant_ai_provider_not_found") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
