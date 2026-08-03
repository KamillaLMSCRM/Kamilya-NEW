"""Methodologist-only retention policy and purge endpoints."""

# FastAPI dependency calls in defaults are the established project pattern.
# Ruff's B008 rule is not actionable for these route declarations.
# ruff: noqa: B008

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User
from app.modules.training_retention.schemas import (
    RetentionPurgeRequest,
    RetentionPurgeResponse,
    TrainingRetentionPolicyCreate,
    TrainingRetentionPolicyListResponse,
    TrainingRetentionPolicyResponse,
    TrainingRetentionPolicyUpdate,
)
from app.modules.training_retention.service import (
    create_policy,
    delete_policy,
    get_policy,
    list_policies,
    purge,
    update_policy,
)

router = APIRouter(prefix="/training-retention", tags=["training-retention"])


@router.get("/policies", response_model=TrainingRetentionPolicyListResponse)
async def list_training_retention_policies(
    db: AsyncSession = Depends(get_db), user: User = Depends(require_role("methodologist"))
):
    items = await list_policies(db, user.tenant_id)
    return TrainingRetentionPolicyListResponse(items=items, total=len(items))


@router.post("/policies", response_model=TrainingRetentionPolicyResponse, status_code=status.HTTP_201_CREATED)
async def create_training_retention_policy(
    payload: TrainingRetentionPolicyCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    return await create_policy(db, user.tenant_id, user.id, payload)


@router.get("/policies/{policy_id}", response_model=TrainingRetentionPolicyResponse)
async def get_training_retention_policy(
    policy_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_role("methodologist"))
):
    return await get_policy(db, user.tenant_id, policy_id)


@router.patch("/policies/{policy_id}", response_model=TrainingRetentionPolicyResponse)
async def update_training_retention_policy(
    policy_id: UUID,
    payload: TrainingRetentionPolicyUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    return await update_policy(db, user.tenant_id, user.id, policy_id, payload)


@router.delete("/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_training_retention_policy(
    policy_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_role("methodologist"))
):
    await delete_policy(db, user.tenant_id, policy_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/purge", response_model=RetentionPurgeResponse)
async def purge_training_evidence(
    payload: RetentionPurgeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    return await purge(db, user.tenant_id, payload, user=user)
