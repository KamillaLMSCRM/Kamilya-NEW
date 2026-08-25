"""Read-only tenant view of centrally governed retention policies.

Policy mutation and evidence purge deliberately have no tenant HTTP route.
The bounded service and database implementation remain available for a future
separately authorized compliance workflow.
"""

# FastAPI dependency calls in defaults are the established project pattern.
# Ruff's B008 rule is not actionable for these route declarations.
# ruff: noqa: B008

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User
from app.modules.training_retention.schemas import TrainingRetentionPolicyListResponse
from app.modules.training_retention.service import list_policies

router = APIRouter(prefix="/training-retention", tags=["training-retention"])


@router.get("/policies", response_model=TrainingRetentionPolicyListResponse)
async def list_training_retention_policies(
    db: AsyncSession = Depends(get_db), user: User = Depends(require_role("methodologist"))
):
    items = await list_policies(db, user.tenant_id)
    return TrainingRetentionPolicyListResponse(items=items, total=len(items))
