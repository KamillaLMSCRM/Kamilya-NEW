"""Superadmin-only generation-model routing API."""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User
from app.modules.admin.model_routing.schemas import (
    GenerationModelRoutingResponse,
    GenerationModelRoutingUpdate,
)
from app.modules.admin.model_routing.service import (
    GenerationModelRoutingService,
    RoutingConfigurationMissingError,
    RoutingPrimaryNotConfiguredError,
    RoutingRevisionConflictError,
)

router = APIRouter(prefix="/admin/model-routing", tags=["admin", "model-routing"])


DbSession = Annotated[AsyncSession, Depends(get_db)]
SuperadminUser = Annotated[User, Depends(require_role("superadmin"))]


def _service(db: DbSession) -> GenerationModelRoutingService:
    return GenerationModelRoutingService(db)


RoutingService = Annotated[GenerationModelRoutingService, Depends(_service)]


@router.get("", response_model=GenerationModelRoutingResponse)
async def get_generation_model_routing(
    user: SuperadminUser,
    svc: RoutingService,
) -> GenerationModelRoutingResponse:
    try:
        return await svc.get()
    except RoutingConfigurationMissingError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.put("", response_model=GenerationModelRoutingResponse)
async def update_generation_model_routing(
    payload: GenerationModelRoutingUpdate,
    user: SuperadminUser,
    svc: RoutingService,
) -> GenerationModelRoutingResponse:
    try:
        return await svc.update(payload, user_id=cast(uuid.UUID, user.id))
    except RoutingRevisionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RoutingPrimaryNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except RoutingConfigurationMissingError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
