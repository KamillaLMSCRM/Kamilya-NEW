"""Canonical position qualification-card API."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_role, require_tenant_user
from app.core.db import get_db
from app.models.users import User
from app.modules.positions import qualification_service as service
from app.modules.positions.qualification_schemas import (
    PositionQualificationCard,
    QualificationCompetenciesPut,
    QualificationHistoryResponse,
    QualificationProfilePatch,
    QualificationRestoreRequest,
    QualificationTrainingPut,
)

router = APIRouter(
    prefix="/positions",
    tags=["positions-qualification"],
    dependencies=[
        Depends(require_tenant_user()),
        Depends(require_role("methodologist")),
    ],
)
_DB = Depends(get_db)
_USER = Depends(get_current_user)


@router.get("/{position_id}/qualification-card", response_model=PositionQualificationCard)
async def get_qualification_card(
    position_id: UUID,
    db: AsyncSession = _DB,
    user: User = _USER,
) -> PositionQualificationCard:
    return await service.get_card(db, position_id, user.tenant_id)


@router.patch("/{position_id}/qualification-profile", response_model=PositionQualificationCard)
async def patch_qualification_profile(
    position_id: UUID,
    payload: QualificationProfilePatch,
    db: AsyncSession = _DB,
    user: User = _USER,
) -> PositionQualificationCard:
    return await service.update_profile(db, position_id, user.tenant_id, user.id, payload)


@router.put("/{position_id}/qualification-competencies", response_model=PositionQualificationCard)
async def put_qualification_competencies(
    position_id: UUID,
    payload: QualificationCompetenciesPut,
    db: AsyncSession = _DB,
    user: User = _USER,
) -> PositionQualificationCard:
    return await service.update_competencies(db, position_id, user.tenant_id, user.id, payload)


@router.put("/{position_id}/mandatory-training", response_model=PositionQualificationCard)
async def put_mandatory_training(
    position_id: UUID,
    payload: QualificationTrainingPut,
    db: AsyncSession = _DB,
    user: User = _USER,
) -> PositionQualificationCard:
    return await service.update_training(db, position_id, user.tenant_id, user.id, payload)


@router.get("/{position_id}/qualification-history", response_model=QualificationHistoryResponse)
async def get_qualification_history(
    position_id: UUID,
    db: AsyncSession = _DB,
    user: User = _USER,
) -> QualificationHistoryResponse:
    return QualificationHistoryResponse(items=await service.history(db, position_id, user.tenant_id))


@router.post(
    "/{position_id}/qualification-history/{version_id}/restore",
    response_model=PositionQualificationCard,
)
async def restore_qualification_history(
    position_id: UUID,
    version_id: UUID,
    payload: QualificationRestoreRequest | None = None,
    db: AsyncSession = _DB,
    user: User = _USER,
) -> PositionQualificationCard:
    return await service.restore(
        db,
        position_id,
        version_id,
        user.tenant_id,
        user.id,
        payload.change_reason if payload else None,
    )
