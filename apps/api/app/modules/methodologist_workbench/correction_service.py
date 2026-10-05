"""Owned durable preview admission; no lesson, release or approval writes."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from datetime import datetime as database_timestamp
from typing import cast
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import _set_tenant_security_context, _set_user_security_context
from app.models.tenant_settings import TenantSettings
from app.models.user_roles import UserRole
from app.models.users import User
from app.modules.ai.budget import check_and_charge_llm_budget, refund_llm_budget
from app.modules.ai.llm_client import ResilientLLMClient

from .assignment_service import WorkbenchConflict, WorkbenchNotFound, _assert_actor
from .correction_context import resolve_lesson_correction
from .correction_contract import CorrectionError, LessonCorrectionSnapshot, preview_lesson_correction
from .correction_models import LessonCorrectionPlan
from .correction_proposal import (
    PROPOSAL_TIMEOUT_SECONDS,
    CorrectionPatchAdapter,
    ProposalClient,
    generate_correction_proposal,
)
from .correction_schemas import CorrectionPreviewRequest, CorrectionPreviewResponse, CorrectionProposal
from .plan_contract import ActorContext

OPERATION = "lesson_correction_preview"
ESTIMATED_COST_CENTS = 10
ProviderResolver = Callable[[UUID], Awaitable[ProposalClient]]
SAFE_FAILURES = frozenset(
    {
        "role_denied",
        "stale",
        "expired",
        "new_draft_required",
        "lesson_correction_unsupported",
        "lesson_source_unavailable",
        "lesson_source_provenance_unavailable",
        "correction_context_too_large",
        "proposal_unavailable",
        "invalid_proposal",
        "proposal_quality_blocked",
        "clarification_required",
        "instruction_unclear",
        "outside_lesson_scope",
        "insufficient_evidence",
        "proposal_cancelled",
    }
)


async def resolve_correction_provider(tenant_id: UUID) -> ProposalClient:
    return await ResilientLLMClient.from_settings_async(
        tenant_id=tenant_id,
        temperature=0.2,
        max_tokens=4500,
        max_retries_per_provider=0,
    )


def request_digest(body: CorrectionPreviewRequest) -> str:
    payload = body.model_dump(mode="json", exclude={"request_key"})
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


async def _security_context(db: AsyncSession, actor: ActorContext) -> None:
    await _set_tenant_security_context(db, str(actor.tenant_id))
    await _set_user_security_context(db, actor.actor_id)


async def _database_now(db: AsyncSession) -> datetime:
    try:
        value = await db.scalar(select(func.clock_timestamp()))
    except SQLAlchemyError:
        raise WorkbenchConflict("correction_clock_unavailable") from None
    if not isinstance(value, database_timestamp) or value.tzinfo is None or value.utcoffset() is None:
        raise WorkbenchConflict("correction_clock_unavailable")
    return value.astimezone(UTC)


async def _assert_live_actor(db: AsyncSession, actor: ActorContext) -> None:
    _assert_actor(actor)
    assigned = exists(
        select(UserRole.id).where(
            UserRole.user_id == User.id,
            UserRole.tenant_id == User.tenant_id,
            UserRole.role == "methodologist",
        )
    )
    user_id = await db.scalar(
        select(User.id).where(
            User.id == actor.actor_id,
            User.tenant_id == actor.tenant_id,
            User.is_active.is_(True),
            User.status == "active",
            or_(User.role == "methodologist", assigned),
        )
    )
    if user_id != actor.actor_id:
        raise CorrectionError("role_denied")


async def _by_request(db: AsyncSession, actor: ActorContext, key: UUID) -> LessonCorrectionPlan | None:
    return cast(
        LessonCorrectionPlan | None,
        await db.scalar(
            select(LessonCorrectionPlan)
            .where(
                LessonCorrectionPlan.tenant_id == actor.tenant_id,
                LessonCorrectionPlan.actor_id == actor.actor_id,
                LessonCorrectionPlan.request_key == key,
            )
            .execution_options(populate_existing=True)
        ),
    )


async def _owned(db: AsyncSession, actor: ActorContext, plan_id: UUID, *, lock: bool = False) -> LessonCorrectionPlan:
    query = (
        select(LessonCorrectionPlan)
        .where(
            LessonCorrectionPlan.id == plan_id,
            LessonCorrectionPlan.tenant_id == actor.tenant_id,
            LessonCorrectionPlan.actor_id == actor.actor_id,
        )
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query)
    if row is None or row.tenant_id != actor.tenant_id or row.actor_id != actor.actor_id:
        raise WorkbenchNotFound("plan_not_found")
    return row


def _base_response(row: LessonCorrectionPlan) -> CorrectionPreviewResponse:
    snapshot = LessonCorrectionSnapshot.model_validate(row.snapshot)
    if (
        snapshot.plan_id != row.id
        or snapshot.actor_id != row.actor_id
        or snapshot.context.tenant_id != row.tenant_id
        or snapshot.expires_at != row.expires_at
    ):
        raise WorkbenchConflict("correction_record_invalid")
    if row.status not in {"pending", "ready", "failed"}:
        raise WorkbenchConflict("correction_record_invalid")
    return CorrectionPreviewResponse(
        plan_id=row.id,
        revision=snapshot.revision,
        lesson_id=snapshot.context.lesson_id,
        state=row.status,
        expires_at=row.expires_at,
        error_code=row.error_code if row.status == "failed" else None,
    )


async def _render(db: AsyncSession, actor: ActorContext, row: LessonCorrectionPlan) -> CorrectionPreviewResponse:
    base = _base_response(row)
    if row.status != "ready":
        return base
    snapshot = LessonCorrectionSnapshot.model_validate(row.snapshot)
    if await _database_now(db) >= snapshot.expires_at:
        raise CorrectionError("expired")
    proposal = CorrectionProposal.model_validate(row.proposal)
    resolved = await resolve_lesson_correction(db, actor, snapshot.context.lesson_id)
    preview = preview_lesson_correction(
        snapshot,
        actor=actor,
        current=resolved.context,
        provider=CorrectionPatchAdapter(snapshot.context.content, proposal),
        now=await _database_now(db),
    )
    if preview.fingerprint != row.fingerprint:
        raise WorkbenchConflict("correction_record_invalid")
    return base.model_copy(
        update={"fingerprint": preview.fingerprint, "before_content": snapshot.context.content, "proposal": proposal}
    )


async def get_correction_preview(db: AsyncSession, actor: ActorContext, plan_id: UUID) -> CorrectionPreviewResponse:
    await _assert_live_actor(db, actor)
    return await _render(db, actor, await _owned(db, actor, plan_id))


async def _charge(db: AsyncSession, actor: ActorContext, admission_month: str) -> None:
    # Lock the override through admission commit so zero cannot become the
    # existing shared helper's truthy default. Never change configured budgets.
    budget = await db.scalar(
        select(TenantSettings.monthly_llm_budget_usd_cents)
        .where(
            TenantSettings.tenant_id == actor.tenant_id,
        )
        .with_for_update()
    )
    if budget is not None and budget <= 0:
        raise HTTPException(429, "llm_budget_exceeded")
    if datetime.now(UTC).strftime("%Y-%m") != admission_month:
        raise WorkbenchConflict("correction_accounting_pending")
    await check_and_charge_llm_budget(
        db,
        str(actor.tenant_id),
        operation=OPERATION,
        estimated_cost_cents=ESTIMATED_COST_CENTS,
    )
    if datetime.now(UTC).strftime("%Y-%m") != admission_month:
        raise WorkbenchConflict("correction_accounting_pending")


async def _finish_failure(db: AsyncSession, actor: ActorContext, plan_id: UUID, code: str) -> CorrectionPreviewResponse:
    # Roll back any failed revalidation/ready transition before restoring RLS
    # context. V1.1 permits owned failure closure even after role revocation.
    await db.rollback()
    await _security_context(db, actor)
    row = await _owned(db, actor, plan_id, lock=True)
    if row.status == "pending":
        snapshot = LessonCorrectionSnapshot.model_validate(row.snapshot)
        if datetime.now(UTC).strftime("%Y-%m") != snapshot.created_at.astimezone(UTC).strftime("%Y-%m"):
            raise WorkbenchConflict("correction_accounting_pending")
        await db.execute(
            update(LessonCorrectionPlan)
            .where(
                LessonCorrectionPlan.id == plan_id,
                LessonCorrectionPlan.tenant_id == actor.tenant_id,
                LessonCorrectionPlan.actor_id == actor.actor_id,
                LessonCorrectionPlan.status == "pending",
            )
            .values(status="failed", error_code=code if code in SAFE_FAILURES else "proposal_unavailable")
        )
        await refund_llm_budget(
            db, str(actor.tenant_id), operation=OPERATION, estimated_cost_cents=ESTIMATED_COST_CENTS
        )
        if datetime.now(UTC).strftime("%Y-%m") != snapshot.created_at.astimezone(UTC).strftime("%Y-%m"):
            await db.rollback()
            raise WorkbenchConflict("correction_accounting_pending")
        await db.commit()
        await _security_context(db, actor)
        row = await _owned(db, actor, plan_id)
    return _base_response(row)


async def create_correction_preview(
    db: AsyncSession,
    actor: ActorContext,
    body: CorrectionPreviewRequest,
    *,
    provider_resolver: ProviderResolver = resolve_correction_provider,
) -> CorrectionPreviewResponse:
    """Claim and reserve once, then generate/revalidate without domain writes.

    A process/DB failure may leave pending with its estimate reserved. Replaying
    it never retries or refunds blindly; reconciliation is a separate gate.
    """
    await _assert_live_actor(db, actor)
    digest = request_digest(body)
    existing = await _by_request(db, actor, body.request_key)
    if existing is not None:
        if existing.request_digest != digest:
            raise WorkbenchConflict("request_key_collision")
        return await _render(db, actor, existing)
    resolved = await resolve_lesson_correction(db, actor, body.lesson_id)
    now = await _database_now(db)
    snapshot = LessonCorrectionSnapshot(
        plan_id=uuid4(),
        revision=1,
        actor_id=actor.actor_id,
        created_at=now,
        expires_at=now + timedelta(minutes=15),
        context=resolved.context,
        instruction=body.instruction,
        locale=body.locale,
    )
    claim = await db.execute(
        insert(LessonCorrectionPlan)
        .values(
            id=snapshot.plan_id,
            tenant_id=actor.tenant_id,
            actor_id=actor.actor_id,
            request_key=body.request_key,
            request_digest=digest,
            snapshot=snapshot.model_dump(mode="json"),
            status="pending",
            expires_at=snapshot.expires_at,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "actor_id", "request_key"])
        .returning(LessonCorrectionPlan.id)
    )
    if claim.scalar_one_or_none() is None:
        existing = await _by_request(db, actor, body.request_key)
        if existing is None:
            raise WorkbenchConflict("correction_admission_conflict")
        if existing.request_digest != digest:
            raise WorkbenchConflict("request_key_collision")
        return await _render(db, actor, existing)
    try:
        await _charge(db, actor, snapshot.created_at.astimezone(UTC).strftime("%Y-%m"))
        await db.commit()  # unique claim + charge, before any provider resolution
    except BaseException:
        await db.rollback()
        raise
    try:
        async with asyncio.timeout(PROPOSAL_TIMEOUT_SECONDS):
            provider = await provider_resolver(actor.tenant_id)
            proposal = await generate_correction_proposal(
                snapshot,
                title=resolved.title,
                excerpts=resolved.excerpts,
                llm=provider,
            )
        await _security_context(db, actor)
        await _assert_live_actor(db, actor)
        row = await _owned(db, actor, snapshot.plan_id, lock=True)
        if row.status != "pending":
            raise WorkbenchConflict("correction_admission_conflict")
        current = await resolve_lesson_correction(db, actor, body.lesson_id)
        preview = preview_lesson_correction(
            snapshot,
            actor=actor,
            current=current.context,
            provider=CorrectionPatchAdapter(snapshot.context.content, proposal),
            now=await _database_now(db),
        )
        await db.execute(
            update(LessonCorrectionPlan)
            .where(
                LessonCorrectionPlan.id == snapshot.plan_id,
                LessonCorrectionPlan.tenant_id == actor.tenant_id,
                LessonCorrectionPlan.actor_id == actor.actor_id,
                LessonCorrectionPlan.status == "pending",
            )
            .values(status="ready", proposal=proposal.model_dump(mode="json"), fingerprint=preview.fingerprint)
        )
        await db.commit()
        return CorrectionPreviewResponse(
            plan_id=snapshot.plan_id,
            revision=snapshot.revision,
            lesson_id=body.lesson_id,
            state="ready",
            expires_at=snapshot.expires_at,
            fingerprint=preview.fingerprint,
            before_content=snapshot.context.content,
            proposal=proposal,
        )
    except asyncio.CancelledError as cancelled:
        try:
            await _finish_failure(db, actor, snapshot.plan_id, "proposal_cancelled")
        finally:
            raise cancelled
    except CorrectionError as exc:
        return await _finish_failure(db, actor, snapshot.plan_id, str(exc))
    except Exception:
        # No raw provider, source, ORM or SQL error is persisted/reflected. If DB
        # closure itself fails it propagates to the route's fixed conflict path.
        return await _finish_failure(db, actor, snapshot.plan_id, "proposal_unavailable")
