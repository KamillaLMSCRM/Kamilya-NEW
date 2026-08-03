"""Methodologist-only CRUD for tenant-configurable procedure definitions."""

# FastAPI dependency calls in defaults are the established project pattern.
# Ruff's B008 rule is not actionable for these route declarations.
# ruff: noqa: B008

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User
from app.modules.training_procedures.schemas import (
    ProcedureStatus,
    TrainingProcedureCreate,
    TrainingProcedureListResponse,
    TrainingProcedureResponse,
    TrainingProcedureUpdate,
)
from app.modules.training_procedures.service import (
    activate_procedure,
    create_procedure,
    delete_procedure,
    get_procedure,
    list_procedures,
    retire_procedure,
    update_procedure,
)

router = APIRouter(prefix="/training-procedures", tags=["training-procedures"])


@router.get("", response_model=TrainingProcedureListResponse)
async def list_training_procedures(
    procedure_status: ProcedureStatus | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    items = await list_procedures(db, user.tenant_id, procedure_status)
    return TrainingProcedureListResponse(items=items, total=len(items))


@router.post("", response_model=TrainingProcedureResponse, status_code=status.HTTP_201_CREATED)
async def create_training_procedure(
    payload: TrainingProcedureCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    return await create_procedure(db, user.tenant_id, user.id, payload)


@router.get("/{procedure_id}", response_model=TrainingProcedureResponse)
async def get_training_procedure(
    procedure_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    return await get_procedure(db, user.tenant_id, procedure_id)


@router.patch("/{procedure_id}", response_model=TrainingProcedureResponse)
async def update_training_procedure(
    procedure_id: UUID,
    payload: TrainingProcedureUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    return await update_procedure(db, user.tenant_id, user.id, procedure_id, payload)


@router.delete("/{procedure_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_training_procedure(
    procedure_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    await delete_procedure(db, user.tenant_id, procedure_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{procedure_id}/activate", response_model=TrainingProcedureResponse)
async def activate_training_procedure(
    procedure_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    return await activate_procedure(db, user.tenant_id, user.id, procedure_id)


@router.post("/{procedure_id}/retire", response_model=TrainingProcedureResponse)
async def retire_training_procedure(
    procedure_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    return await retire_procedure(db, user.tenant_id, user.id, procedure_id)
