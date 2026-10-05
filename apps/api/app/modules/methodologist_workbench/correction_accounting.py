"""Correction-owned estimate lifecycle; settlement refunds are DB-trigger owned."""

from __future__ import annotations

from datetime import UTC
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant_settings import TenantSettings
from app.modules.ai.budget import DEFAULT_BUDGET_USD_CENTS

from .assignment_service import WorkbenchConflict
from .correction_contract import LessonCorrectionSnapshot
from .correction_models import LessonCorrectionAccounting
from .plan_contract import ActorContext

ESTIMATED_COST_CENTS = 10


async def reserve_correction_estimate(db: AsyncSession, actor: ActorContext, snapshot: LessonCorrectionSnapshot) -> None:
    """Caller commits this with its unique parent claim, or rolls all three back."""
    override = await db.scalar(
        select(TenantSettings.monthly_llm_budget_usd_cents)
        .where(TenantSettings.tenant_id == actor.tenant_id)
        .with_for_update()
    )
    budget = DEFAULT_BUDGET_USD_CENTS if override is None else override
    if budget <= 0:
        raise HTTPException(429, "llm_budget_exceeded")
    month = snapshot.created_at.astimezone(UTC).strftime("%Y-%m")
    charge = await db.execute(
        text("""INSERT INTO tenant_llm_usage(id,tenant_id,month_key,cost_cents,request_count)
            SELECT :usage_id,:tenant_id,:month_key,CAST(:cost AS INTEGER),1
            WHERE CAST(:cost AS INTEGER)<=CAST(:budget AS INTEGER)
            ON CONFLICT(tenant_id,month_key) DO UPDATE SET
                cost_cents=tenant_llm_usage.cost_cents+:cost,
                request_count=tenant_llm_usage.request_count+1,updated_at=clock_timestamp()
            WHERE tenant_llm_usage.cost_cents+:cost<=:budget RETURNING cost_cents"""),
        {"usage_id": uuid4(), "tenant_id": actor.tenant_id, "month_key": month, "cost": ESTIMATED_COST_CENTS, "budget": budget},
    )
    if charge.scalar_one_or_none() is None:
        raise HTTPException(429, "llm_budget_exceeded")
    await db.execute(
        insert(LessonCorrectionAccounting).values(
            plan_id=snapshot.plan_id, tenant_id=actor.tenant_id, actor_id=actor.actor_id,
            month_key=month, estimated_cost_cents=ESTIMATED_COST_CENTS, state="reserved",
        )
    )


async def transition_correction_estimate(
    db: AsyncSession, actor: ActorContext, plan_id: UUID, state: str,
) -> None:
    """Parent must be locked first. Trigger owns time and original-month refunds."""
    if state not in {"started", "charged", "refunded"}:
        raise WorkbenchConflict("correction_accounting_pending")
    row = await db.scalar(
        select(LessonCorrectionAccounting).where(
            LessonCorrectionAccounting.plan_id == plan_id,
            LessonCorrectionAccounting.tenant_id == actor.tenant_id,
            LessonCorrectionAccounting.actor_id == actor.actor_id,
        ).with_for_update().execution_options(populate_existing=True)
    )
    if row is None:
        # Legacy admission has no reliable per-plan reservation. Never fabricate
        # one or decrement a shared aggregate for it.
        if state == "refunded":
            return
        raise WorkbenchConflict("correction_accounting_pending")
    if row.state == state:
        return
    expected = {"reserved"} if state == "started" else {"started"} if state == "charged" else {"reserved", "started"}
    if row.state not in expected or row.tenant_id != actor.tenant_id or row.actor_id != actor.actor_id:
        raise WorkbenchConflict("correction_accounting_pending")
    result = await db.execute(
        update(LessonCorrectionAccounting).where(
            LessonCorrectionAccounting.plan_id == plan_id,
            LessonCorrectionAccounting.tenant_id == actor.tenant_id,
            LessonCorrectionAccounting.actor_id == actor.actor_id,
            LessonCorrectionAccounting.state == row.state,
        ).values(state=state).returning(LessonCorrectionAccounting.state)
    )
    if result.scalar_one_or_none() != state:
        raise WorkbenchConflict("correction_accounting_pending")
