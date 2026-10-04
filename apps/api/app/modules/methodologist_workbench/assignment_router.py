"""Feature-disabled-by-default methodologist preview/confirmation surface."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.config import get_settings
from app.core.db import get_db
from app.models.users import User

from .assignment_schemas import (
    AssignmentInterpretRequest,
    AssignmentPreviewRequest,
    AssignmentReceipt,
    InterpretResponse,
    PlanResponse,
    PreviewResponse,
)
from .assignment_service import (
    WorkbenchConflict,
    WorkbenchNotFound,
    confirm_assignment_plan,
    create_assignment_preview,
    get_assignment_plan,
)
from .document_router import router as document_router
from .intent_application import interpret_assignment
from .plan_contract import ActorContext, ConfirmationRequest

router = APIRouter(prefix="/methodologist-workbench", tags=["methodologist-workbench"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
Methodologist = Annotated[User, Depends(require_role("methodologist"))]


def _context(user: User, response: Response) -> ActorContext:
    response.headers["Cache-Control"] = "no-store"
    if not get_settings().METHODOLOGIST_WORKBENCH_ENABLED:
        raise HTTPException(404, "workbench_disabled")
    if user.tenant_id is None or getattr(user, "is_impersonating", False):
        raise HTTPException(403, "workbench_context_denied")
    return ActorContext(tenant_id=cast(UUID, user.tenant_id), actor_id=cast(UUID, user.id), active_role=user.role)


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, WorkbenchNotFound):
        return HTTPException(404, "resource_not_found")
    if isinstance(exc, IntegrityError | OperationalError):
        return HTTPException(409, "assignment_conflict")
    return HTTPException(409, str(exc))


@router.post("/assignment-preview", response_model=PreviewResponse)
async def preview_assignment(
    body: AssignmentPreviewRequest, response: Response, db: DbSession, user: Methodologist
) -> PreviewResponse:
    actor = _context(user, response)
    try:
        result = await create_assignment_preview(db, actor, body)
        await db.commit()
        return result
    except (WorkbenchConflict, WorkbenchNotFound, IntegrityError, OperationalError) as exc:
        await db.rollback()
        raise _error(exc) from exc


@router.post("/interpret-assignment", response_model=InterpretResponse)
async def interpret_instruction(
    body: AssignmentInterpretRequest, response: Response, db: DbSession, user: Methodologist
) -> InterpretResponse:
    actor = _context(user, response)
    try:
        result = await interpret_assignment(db, actor, body)
        await db.commit()
        return result
    except HTTPException:
        await db.rollback()
        raise
    except (WorkbenchConflict, WorkbenchNotFound, IntegrityError, OperationalError) as exc:
        await db.rollback()
        raise _error(exc) from exc


@router.get("/plans/{plan_id}", response_model=PlanResponse)
async def read_plan(plan_id: UUID, response: Response, db: DbSession, user: Methodologist) -> PlanResponse:
    actor = _context(user, response)
    try:
        return await get_assignment_plan(db, actor, plan_id)
    except (WorkbenchConflict, WorkbenchNotFound) as exc:
        raise _error(exc) from exc


@router.post("/plans/{plan_id}/confirm", response_model=AssignmentReceipt)
async def confirm_plan(
    plan_id: UUID, body: ConfirmationRequest, response: Response, db: DbSession, user: Methodologist
) -> AssignmentReceipt:
    actor = _context(user, response)
    if body.plan_id != plan_id:
        raise HTTPException(422, "plan_id_mismatch")
    try:
        outcome = await confirm_assignment_plan(db, actor, body)
        await db.commit()
    except (WorkbenchConflict, WorkbenchNotFound, IntegrityError, OperationalError) as exc:
        await db.rollback()
        raise _error(exc) from exc
    # Only dispatch after the receipt and domain rows have committed. Outbox
    # timer remains the retry owner; dispatch success is NOT delivery evidence.
    for notification_id in outcome.dispatch_ids:
        try:
            from app.modules.enrollments.notification_tasks import deliver_assignment_notification_task

            deliver_assignment_notification_task.apply_async(args=[str(actor.tenant_id), str(notification_id)])
        except Exception:
            pass
    return outcome.receipt


router.include_router(document_router)
