"""Separate router for learner step-up confirmation.

The application registers this router explicitly beside the core evidence
router in ``app/main.py``.
"""

# FastAPI dependency calls in defaults are the established project pattern.
# ruff's B008 rule is not actionable for these route declarations.
# ruff: noqa: B008

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User
from app.modules.training_evidence.step_up_schemas import (
    StepUpChallengeRequest,
    StepUpChallengeResponse,
    StepUpVerifyRequest,
    StepUpVerifyResponse,
)
from app.modules.training_evidence.step_up_service import request_step_up, verify_step_up

router = APIRouter(prefix="/training-evidence/step-up", tags=["training-evidence-step-up"])


@router.post("/events/{event_id}/request", response_model=StepUpChallengeResponse)
async def request_step_up_code(
    event_id: UUID,
    payload: StepUpChallengeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("student")),
):
    return await request_step_up(
        db=db,
        tenant_id=user.tenant_id,
        event_id=event_id,
        user=user,
        ip_address=request.client.host if request.client else None,
    )


@router.post(
    "/events/{event_id}/verify",
    response_model=StepUpVerifyResponse,
    status_code=status.HTTP_200_OK,
)
async def verify_step_up_code(
    event_id: UUID,
    payload: StepUpVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("student")),
):
    confirmation = await verify_step_up(
        db=db,
        tenant_id=user.tenant_id,
        event_id=event_id,
        user=user,
        challenge_id=payload.challenge_id,
        code=payload.code,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()
    return {"confirmed": True, "confirmation_id": confirmation.id}
