"""Methodologist-only CRUD for tenant-configurable procedure definitions."""

# FastAPI dependency calls in defaults are the established project pattern.
# Ruff's B008 rule is not actionable for these route declarations.
# ruff: noqa: B008

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User
from app.modules.audit.service import log_action
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


def _procedure_actor_id(user: User) -> UUID | None:
    """Return a tenant-valid author without fabricating an impersonated user."""

    if getattr(user, "is_impersonating", False):
        return None
    return cast(UUID, user.id)


def _procedure_tenant_id(user: User) -> UUID:
    """Narrow the tenant guaranteed by the methodologist role dependency."""

    return cast(UUID, user.tenant_id)


def _audit_details(user: User) -> dict[str, bool]:
    return {"impersonation": bool(getattr(user, "is_impersonating", False))}


@router.get("", response_model=TrainingProcedureListResponse)
async def list_training_procedures(
    procedure_status: ProcedureStatus | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    items = await list_procedures(db, _procedure_tenant_id(user), procedure_status)
    return TrainingProcedureListResponse(items=items, total=len(items))


@router.post("", response_model=TrainingProcedureResponse, status_code=status.HTTP_201_CREATED)
async def create_training_procedure(
    payload: TrainingProcedureCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    tenant_id = _procedure_tenant_id(user)
    procedure = await create_procedure(db, tenant_id, _procedure_actor_id(user), payload)
    await log_action(
        db,
        tenant_id,
        "training_procedure.created",
        "training_procedure",
        resource_id=procedure.id,
        user_id=user.id,
        details=_audit_details(user),
    )
    return procedure


@router.get("/{procedure_id}", response_model=TrainingProcedureResponse)
async def get_training_procedure(
    procedure_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    return await get_procedure(db, _procedure_tenant_id(user), procedure_id)


@router.patch("/{procedure_id}", response_model=TrainingProcedureResponse)
async def update_training_procedure(
    procedure_id: UUID,
    payload: TrainingProcedureUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    tenant_id = _procedure_tenant_id(user)
    procedure = await update_procedure(
        db, tenant_id, _procedure_actor_id(user), procedure_id, payload
    )
    await log_action(
        db,
        tenant_id,
        "training_procedure.updated",
        "training_procedure",
        resource_id=procedure.id,
        user_id=user.id,
        details=_audit_details(user),
    )
    return procedure


@router.delete("/{procedure_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_training_procedure(
    procedure_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    tenant_id = _procedure_tenant_id(user)
    procedure = await get_procedure(db, tenant_id, procedure_id)
    await delete_procedure(db, tenant_id, procedure_id)
    await log_action(
        db,
        tenant_id,
        "training_procedure.deleted",
        "training_procedure",
        resource_id=procedure.id,
        user_id=user.id,
        details=_audit_details(user),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{procedure_id}/activate", response_model=TrainingProcedureResponse)
async def activate_training_procedure(
    procedure_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    tenant_id = _procedure_tenant_id(user)
    procedure = await activate_procedure(
        db, tenant_id, _procedure_actor_id(user), procedure_id
    )
    await log_action(
        db,
        tenant_id,
        "training_procedure.activated",
        "training_procedure",
        resource_id=procedure.id,
        user_id=user.id,
        details=_audit_details(user),
    )
    return procedure


@router.post("/{procedure_id}/retire", response_model=TrainingProcedureResponse)
async def retire_training_procedure(
    procedure_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    tenant_id = _procedure_tenant_id(user)
    procedure = await retire_procedure(
        db, tenant_id, _procedure_actor_id(user), procedure_id
    )
    await log_action(
        db,
        tenant_id,
        "training_procedure.retired",
        "training_procedure",
        resource_id=procedure.id,
        user_id=user.id,
        details=_audit_details(user),
    )
    return procedure
