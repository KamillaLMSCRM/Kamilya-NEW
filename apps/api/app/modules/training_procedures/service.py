"""Application rules for configuring, activating, and retiring procedures."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.training_procedures.models import TrainingProcedure
from app.modules.training_procedures.schemas import TrainingProcedureCreate, TrainingProcedureUpdate

REQUIRED_COMMISSION_RULES = ("members", "quorum", "decision_record")
REQUIRED_AUTHORIZED_DECISION_RULES = ("authority", "decision_record", "effective_date")


class ActivationIncompleteError(ValueError):
    def __init__(self, fields: list[str]):
        self.fields = fields
        super().__init__(", ".join(fields))


def _present(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


def validate_activation_ready(procedure: TrainingProcedure) -> None:
    """Return no result only when the definition is complete enough to activate."""

    missing: list[str] = []
    for field in ("approval_reference", "approval_date", "approved_by_name", "retention_class", "retention_days"):
        if not _present(getattr(procedure, field)):
            missing.append(field)
    if not (_present(procedure.legal_basis) or _present(procedure.local_basis)):
        missing.append("legal_basis_or_local_basis")

    if procedure.procedure_type == "internal_attestation":
        rules = procedure.commission_snapshot_rules
        if not isinstance(rules, Mapping) or any(not _present(rules.get(key)) for key in REQUIRED_COMMISSION_RULES):
            missing.append("commission_snapshot_rules")
    if procedure.procedure_type == "admission_decision":
        rules = procedure.authorized_decision_rules
        if not isinstance(rules, Mapping) or any(not _present(rules.get(key)) for key in REQUIRED_AUTHORIZED_DECISION_RULES):
            missing.append("authorized_decision_rules")
    if missing:
        raise ActivationIncompleteError(missing)


async def get_procedure(db: AsyncSession, tenant_id: UUID, procedure_id: UUID) -> TrainingProcedure:
    procedure = await db.scalar(
        select(TrainingProcedure).where(
            TrainingProcedure.id == procedure_id,
            TrainingProcedure.tenant_id == tenant_id,
        )
    )
    if procedure is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training procedure not found")
    return procedure


async def list_procedures(db: AsyncSession, tenant_id: UUID, procedure_status: str | None = None) -> list[TrainingProcedure]:
    statement = select(TrainingProcedure).where(TrainingProcedure.tenant_id == tenant_id)
    if procedure_status:
        statement = statement.where(TrainingProcedure.status == procedure_status)
    result = await db.execute(statement.order_by(TrainingProcedure.code.asc(), TrainingProcedure.version.desc()))
    return list(result.scalars().all())


async def create_procedure(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID | None,
    payload: TrainingProcedureCreate,
) -> TrainingProcedure:
    existing = await db.scalar(
        select(TrainingProcedure.id).where(
            TrainingProcedure.tenant_id == tenant_id,
            TrainingProcedure.code == payload.code,
            TrainingProcedure.version == payload.version,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Procedure code and version already exist")
    procedure = TrainingProcedure(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        updated_by_user_id=user_id,
        **payload.model_dump(),
    )
    db.add(procedure)
    await db.flush()
    return procedure


async def update_procedure(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID | None,
    procedure_id: UUID,
    payload: TrainingProcedureUpdate,
) -> TrainingProcedure:
    procedure = await get_procedure(db, tenant_id, procedure_id)
    if procedure.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft procedures can be edited")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(procedure, field, value)
    procedure.updated_by_user_id = user_id
    await db.flush()
    return procedure


async def delete_procedure(db: AsyncSession, tenant_id: UUID, procedure_id: UUID) -> None:
    procedure = await get_procedure(db, tenant_id, procedure_id)
    if procedure.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft procedures can be deleted")
    await db.delete(procedure)
    await db.flush()


async def activate_procedure(db: AsyncSession, tenant_id: UUID, user_id: UUID | None, procedure_id: UUID) -> TrainingProcedure:
    procedure = await db.scalar(
        select(TrainingProcedure)
        .where(TrainingProcedure.id == procedure_id, TrainingProcedure.tenant_id == tenant_id)
        .with_for_update()
    )
    if procedure is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training procedure not found")
    if procedure.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft procedures can be activated")
    try:
        validate_activation_ready(procedure)
    except ActivationIncompleteError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "activation_incomplete", "missing_fields": exc.fields},
        ) from exc
    active_version = await db.scalar(
        select(TrainingProcedure)
        .where(
            TrainingProcedure.tenant_id == tenant_id,
            TrainingProcedure.code == procedure.code,
            TrainingProcedure.status == "active",
            TrainingProcedure.id != procedure.id,
        )
        .with_for_update()
    )
    if active_version is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "active_procedure_version_exists",
                "message": (
                    f"An active version already exists for procedure code '{procedure.code}'. "
                    "Retire the active version first before activating another version."
                ),
            },
        )
    procedure.status = "active"
    procedure.updated_by_user_id = user_id
    procedure.activated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(procedure)
    return procedure


async def retire_procedure(db: AsyncSession, tenant_id: UUID, user_id: UUID | None, procedure_id: UUID) -> TrainingProcedure:
    procedure = await get_procedure(db, tenant_id, procedure_id)
    if procedure.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only active procedures can be retired")
    procedure.status = "retired"
    procedure.updated_by_user_id = user_id
    procedure.retired_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(procedure)
    return procedure
