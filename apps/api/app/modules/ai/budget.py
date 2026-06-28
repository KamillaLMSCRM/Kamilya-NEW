"""Per-tenant LLM cost tracking.

Audit §6.3 — track token usage and reject requests that exceed the
tenant's monthly budget. Prevents one tenant from exhausting the
shared DeepSeek fallback budget.

Design notes:
  - Usage is incremented BEFORE the LLM call (optimistic). If the
    call fails, we decrement in the except block. This means a
    flood of failed calls could over-count, but the counter is
    best-effort — exact accounting would require idempotent
    receipts from the provider, which neither Qwen nor DeepSeek
    expose.
  - Budget is checked on each /ai/generate-course call. Smaller
    endpoints (chat, rephrase) don't go through this gate because
    their per-call cost is negligible.
  - 'month' is UTC calendar month (not 30-day rolling). Resets on
    the 1st of each month at 00:00 UTC.
  - We track cost in USD cents to avoid floating-point arithmetic
    in the database. Conversion to USD happens once when the rate
    is updated.
"""

from __future__ import annotations

import calendar
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.tenant_settings import TenantSettings
from app.models.tenant_llm_usage import TenantLLMUsage
from app.core.config import get_settings

logger = logging.getLogger(__name__)


# USD per 1M tokens. Updated manually when rates change.
# These are conservative defaults; DeepSeek v4-flash is the cheapest
# in our chain and used as the upper bound. Qwen is free.
DEFAULT_BUDGET_USD_CENTS = 5000  # $50/month per tenant default

# Average cost per /ai/generate-course call (estimated from typical
# 8K input tokens + 4K output tokens). Used to estimate whether
# the next call would exceed budget before committing to it.
ESTIMATED_COST_PER_GENERATION_USD_CENTS = 10  # $0.10 (matches TZ.md target)


async def check_and_charge_llm_budget(
    db: AsyncSession,
    tenant_id: str,
    operation: str = "generate_course",
    estimated_cost_cents: int = ESTIMATED_COST_PER_GENERATION_USD_CENTS,
) -> None:
    """Check the tenant's LLM budget and increment usage atomically.

    Raises HTTPException(429) if the tenant has exceeded its monthly
    budget. The budget is configured in tenant_settings.monthly_llm_budget_usd_cents
    (default: $50).

    The check + increment is wrapped in a single SQL UPDATE to avoid
    race conditions where two concurrent requests both see "under budget"
    and both proceed.
    """
    # Lazy import to avoid circular import.
    from app.models.tenants import Tenant

    # Get budget (per-tenant override or default).
    settings_result = await db.execute(
        select(TenantSettings.monthly_llm_budget_usd_cents).where(
            TenantSettings.tenant_id == tenant_id
        )
    )
    budget_cents = settings_result.scalar_one_or_none() or DEFAULT_BUDGET_USD_CENTS

    # Get current month key (YYYY-MM).
    now = datetime.now(timezone.utc)
    month_key = now.strftime("%Y-%m")

    # Atomic check-and-increment: only update if (current + estimated) <= budget.
    # RETURNING tells us whether the row was actually updated.
    from sqlalchemy import text

    result = await db.execute(
        text("""
            INSERT INTO tenant_llm_usage (tenant_id, month_key, cost_cents, request_count)
            VALUES (:tenant_id, :month_key, :cost, 1)
            ON CONFLICT (tenant_id, month_key)
            DO UPDATE SET
                cost_cents = tenant_llm_usage.cost_cents + :cost,
                request_count = tenant_llm_usage.request_count + 1,
                updated_at = NOW()
            WHERE tenant_llm_usage.cost_cents + :cost <= :budget
            RETURNING cost_cents, request_count
        """),
        {
            "tenant_id": tenant_id,
            "month_key": month_key,
            "cost": estimated_cost_cents,
            "budget": budget_cents,
        },
    )
    row = result.fetchone()
    if row is None:
        # Either tenant_id/month_key doesn't exist (insert failed because
        # the WHERE clause blocked the update) OR the budget was exceeded.
        # Check current usage to disambiguate.
        current = await db.execute(
            text("SELECT cost_cents FROM tenant_llm_usage WHERE tenant_id = :t AND month_key = :m"),
            {"t": tenant_id, "m": month_key},
        )
        used = current.scalar() or 0
        logger.warning(
            "tenant=%s exceeded LLM budget (%d/%d cents) for %s; rejecting %s",
            tenant_id, used, budget_cents, month_key, operation,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "llm_budget_exceeded",
                "message": "Tenant LLM budget exceeded for this month.",
                "used_cents": used,
                "budget_cents": budget_cents,
                "month": month_key,
            },
        )

    # Verify tenant exists (defense — the FK should catch this but
    # explicit check surfaces a clearer error).
    exists = await db.execute(
        select(Tenant.id).where(Tenant.id == tenant_id)
    )
    if exists.scalar_one_or_none() is None:
        # Roll back the increment — the tenant doesn't actually exist.
        await db.execute(
            text("""
                UPDATE tenant_llm_usage
                SET cost_cents = cost_cents - :cost,
                    request_count = request_count - 1
                WHERE tenant_id = :t AND month_key = :m
            """),
            {"cost": estimated_cost_cents, "t": tenant_id, "m": month_key},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )

    logger.debug(
        "tenant=%s charged %d cents for %s (now %d/%d)",
        tenant_id, estimated_cost_cents, operation, row[0], budget_cents,
    )


async def refund_llm_budget(
    db: AsyncSession,
    tenant_id: str,
    operation: str,
    estimated_cost_cents: int = ESTIMATED_COST_PER_GENERATION_USD_CENTS,
) -> None:
    """Refund an optimistic LLM charge when the call failed.

    Call sites should pair this with check_and_charge_llm_budget in
    an except block:

        try:
            await check_and_charge_llm_budget(db, tenant_id)
        except HTTPException:
            raise
        try:
            result = await call_llm(...)
        except Exception:
            await refund_llm_budget(db, tenant_id, "generate_course")
            raise
    """
    from sqlalchemy import text

    month_key = datetime.now(timezone.utc).strftime("%Y-%m")
    await db.execute(
        text("""
            UPDATE tenant_llm_usage
            SET cost_cents = GREATEST(0, cost_cents - :cost),
                request_count = GREATEST(0, request_count - 1),
                updated_at = NOW()
            WHERE tenant_id = :t AND month_key = :m
        """),
        {"cost": estimated_cost_cents, "t": tenant_id, "m": month_key},
    )