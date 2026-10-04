"""Authorized, bounded interpretation; no assignment or approval side effects."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import _set_tenant_security_context, _set_user_security_context
from app.modules.ai.budget import check_and_charge_llm_budget, refund_llm_budget
from app.modules.ai.llm_client import ResilientLLMClient

from .assignment_schemas import (
    AssignmentInterpretRequest,
    AssignmentPreview,
    Clarification,
    InterpretedAssignment,
    InterpretResponse,
)
from .assignment_service import _assert_actor, get_assignment_plan
from .natural_assignment_intent import (
    AssignmentCandidate,
    build_intent_messages,
    candidate_to_parsed,
    parse_model_candidate,
    requires_absolute_deadline,
)
from .plan_contract import ActorContext

ProviderResolver = Callable[[UUID], Awaitable[ResilientLLMClient]]
INTENT_TIMEOUT_SECONDS = 30
INTENT_ESTIMATED_COST_CENTS = 1
INTENT_OPERATION = "assignment_intent_parse"


async def resolve_intent_provider(tenant_id: UUID) -> ResilientLLMClient:
    return await ResilientLLMClient.from_settings_async(
        tenant_id=tenant_id, temperature=0, max_tokens=1200, max_retries_per_provider=0
    )


async def _refund_admission(db: AsyncSession, actor: ActorContext) -> None:
    # Admission commit ended the transaction-local RLS context. Re-establish
    # the same server-owned identity before any new ledger transaction.
    await _set_tenant_security_context(db, str(actor.tenant_id))
    await _set_user_security_context(db, actor.actor_id)
    await refund_llm_budget(
        db, str(actor.tenant_id), operation=INTENT_OPERATION, estimated_cost_cents=INTENT_ESTIMATED_COST_CENTS
    )


async def interpret_assignment(
    db: AsyncSession,
    actor: ActorContext,
    body: AssignmentInterpretRequest,
    *,
    provider_resolver: ProviderResolver = resolve_intent_provider,
    now: datetime | None = None,
) -> InterpretResponse:
    """Reserve existing usage before a bounded provider call; return untrusted fields.

    A previous plan is read only through the existing owned-plan interface.
    The prompt contains no plan identity, actor, tenant or recipient information.
    Successful interpretation still needs editable review, server preview and
    human confirmation. Estimated usage is not a provider billing receipt.
    """
    _assert_actor(actor)
    now = now or datetime.now(UTC)
    try:
        zone = ZoneInfo(body.timezone_name)
    except (ValueError, ZoneInfoNotFoundError):
        return Clarification(code="timezone_invalid")
    if requires_absolute_deadline(body.instruction):
        return Clarification(code="intent_relative_deadline")
    previous = None
    if body.previous_plan_id is not None:
        plan = await get_assignment_plan(db, actor, body.previous_plan_id)
        if not isinstance(plan, AssignmentPreview):
            return Clarification(code="previous_plan_not_ready")
        deadline = plan.due_at.astimezone(zone)
        previous = AssignmentCandidate(
            course_query=plan.course_title,
            department_query=plan.department_name,
            due_date=deadline.strftime("%Y-%m-%d"),
            due_time=deadline.strftime("%H:%M:%S"),
            notify=plan.notify,
            include_descendants=plan.include_descendants,
        )
    messages = build_intent_messages(body.instruction, body.timezone_name, previous)
    await check_and_charge_llm_budget(
        db, str(actor.tenant_id), operation=INTENT_OPERATION, estimated_cost_cents=INTENT_ESTIMATED_COST_CENTS
    )
    # A durable admission prevents concurrent requests bypassing the budget while
    # the provider is running. No workbench/domain rows are written in this route.
    await db.commit()
    try:
        async with asyncio.timeout(INTENT_TIMEOUT_SECONDS):
            provider = await provider_resolver(actor.tenant_id)
            response = await provider.ainvoke(messages)
        # Parse AFTER transport failover. Invalid semantic/JSON output does not
        # spend more calls on repair or another model.
        candidate = parse_model_candidate(
            response.content,
            notify=body.notify,
            include_descendants=body.include_descendants,
            default_due_time=previous.due_time if previous is not None else "23:59:59",
        )
        candidate_to_parsed(candidate, body.timezone_name, now)
        return InterpretedAssignment(candidate=candidate)
    except asyncio.CancelledError:
        # A cancelled request must not return a late interpretation. Settle the
        # same estimate while the dependency's session is still owned, then
        # propagate cancellation. No detached task using a soon-closed session.
        try:
            await _refund_admission(db, actor)
            await db.commit()
        finally:
            raise
    except ValueError as exc:
        code = str(exc)
        allowed = {"intent_clarification", "intent_invalid_response", "deadline_invalid", "deadline_passed", "timezone_invalid"}
        result = Clarification(code=code if code in allowed else "intent_invalid_response")
    except Exception:
        # Do not expose/log provider exception text, which may include endpoints
        # or untrusted content. No silent guessed fallback or retry.
        result = Clarification(code="intent_provider_unavailable")
    await _refund_admission(db, actor)
    return result
