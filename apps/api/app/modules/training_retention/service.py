"""Tenant-scoped retention policy and controlled purge services."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.training_retention.models import TrainingRetentionPolicy
from app.modules.training_retention.schemas import (
    PURGE_CONFIRMATION_TOKEN,
    RetentionPurgeRequest,
    RetentionPurgeResponse,
    TrainingRetentionPolicyCreate,
    TrainingRetentionPolicyUpdate,
)


def _reauthenticate_for_execute(*, user, tenant_id: UUID, password: str | None) -> None:
    """Require the current operator to authenticate again before destructive work."""

    if not password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "reauth_required", "message": "Fresh authentication is required"},
        )
    from app.modules.auth.service import verify_current_password

    if user.tenant_id != tenant_id or not verify_current_password(user, password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "reauth_failed", "message": "Fresh authentication failed"},
        )


async def get_policy(db: AsyncSession, tenant_id: UUID, policy_id: UUID) -> TrainingRetentionPolicy:
    policy = await db.scalar(
        select(TrainingRetentionPolicy).where(
            TrainingRetentionPolicy.id == policy_id,
            TrainingRetentionPolicy.tenant_id == tenant_id,
        )
    )
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Retention policy not found")
    return policy


async def list_policies(db: AsyncSession, tenant_id: UUID) -> list[TrainingRetentionPolicy]:
    result = await db.scalars(
        select(TrainingRetentionPolicy)
        .where(TrainingRetentionPolicy.tenant_id == tenant_id)
        .order_by(TrainingRetentionPolicy.procedure_type.asc())
    )
    return list(result.all())


async def create_policy(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    payload: TrainingRetentionPolicyCreate,
) -> TrainingRetentionPolicy:
    existing = await db.scalar(
        select(TrainingRetentionPolicy.id).where(
            TrainingRetentionPolicy.tenant_id == tenant_id,
            TrainingRetentionPolicy.procedure_type == payload.procedure_type,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Policy for this procedure type already exists")
    policy = TrainingRetentionPolicy(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        updated_by_user_id=user_id,
        **payload.model_dump(),
    )
    db.add(policy)
    await db.flush()
    return policy


async def update_policy(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: UUID,
    policy_id: UUID,
    payload: TrainingRetentionPolicyUpdate,
) -> TrainingRetentionPolicy:
    policy = await get_policy(db, tenant_id, policy_id)
    values = payload.model_dump(exclude_unset=True)
    next_active = values.get("active", policy.active)
    next_legal = values.get("legal_basis", policy.legal_basis)
    next_local = values.get("local_basis", policy.local_basis)
    if next_active and not (next_legal and next_legal.strip()) and not (next_local and next_local.strip()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Active retention policy requires legal_basis or local_basis",
        )
    for field, value in values.items():
        setattr(policy, field, value)
    policy.updated_by_user_id = user_id
    await db.flush()
    return policy


async def delete_policy(db: AsyncSession, tenant_id: UUID, policy_id: UUID) -> None:
    policy = await get_policy(db, tenant_id, policy_id)
    if policy.active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Deactivate the policy before deleting it")
    await db.delete(policy)
    await db.flush()


async def purge(
    db: AsyncSession,
    tenant_id: UUID,
    payload: RetentionPurgeRequest,
    *,
    user=None,
) -> RetentionPurgeResponse:
    if not payload.dry_run and payload.confirmation_token != PURGE_CONFIRMATION_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "confirmation_required", "message": "The server confirmation phrase is required"},
        )
    if not payload.dry_run:
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "reauth_required", "message": "Fresh authentication is required"},
            )
        _reauthenticate_for_execute(
            user=user,
            tenant_id=tenant_id,
            password=payload.reauth_password,
        )
    result = await db.scalar(
        text(
            """
            SELECT purge_training_evidence_chains(
                :tenant_id,
                :confirmation_token,
                :dry_run,
                :max_roots
            )
            """
        ),
        {
            "tenant_id": str(tenant_id),
            "confirmation_token": payload.confirmation_token or PURGE_CONFIRMATION_TOKEN,
            "dry_run": payload.dry_run,
            "max_roots": payload.max_roots,
        },
    )
    if not isinstance(result, dict):
        raise RuntimeError("Retention purge returned an invalid aggregate")
    return RetentionPurgeResponse(
        dry_run=bool(result.get("dry_run", payload.dry_run)),
        scan_budget=int(result.get("scan_budget", 0)),
        roots_scanned=int(result.get("roots_scanned", 0)),
        truncated=bool(result.get("truncated", False)),
        eligible_roots=int(result.get("eligible_roots", 0)),
        purged_roots=int(result.get("purged_roots", 0)),
        purged_events=int(result.get("purged_events", 0)),
        purged_confirmations=int(result.get("purged_confirmations", 0)),
        purged_hold_history=int(result.get("purged_hold_history", 0)),
        purged_shares=int(result.get("purged_shares", 0)),
        reason_counts={str(key): int(value) for key, value in (result.get("reason_counts") or {}).items()},
        generated_at=datetime.now(UTC),
    )
