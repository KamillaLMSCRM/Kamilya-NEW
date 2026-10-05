"""Explicit preview/application, behind independent OFF-by-default flag."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.config import get_settings
from app.core.db import get_db
from app.models.users import User

from .assignment_service import WorkbenchConflict, WorkbenchNotFound
from .correction_application import apply_correction_preview, get_correction_application
from .correction_contract import CorrectionError
from .correction_schemas import CorrectionApplicationResponse, CorrectionPreviewRequest, CorrectionPreviewResponse
from .correction_service import SAFE_FAILURES, create_correction_preview, get_correction_preview
from .plan_contract import ActorContext, ConfirmationRequest

router = APIRouter()
DbSession = Annotated[AsyncSession, Depends(get_db)]
Methodologist = Annotated[User, Depends(require_role("methodologist"))]


def _context(user: User, response: Response) -> ActorContext:
    response.headers["Cache-Control"] = "no-store"
    settings = get_settings()
    if not settings.METHODOLOGIST_WORKBENCH_ENABLED or not settings.METHODOLOGIST_LESSON_CORRECTION_ENABLED:
        raise HTTPException(404, "lesson_correction_disabled", headers={"Cache-Control": "no-store"})
    if user.tenant_id is None or getattr(user, "is_impersonating", False):
        raise HTTPException(403, "workbench_context_denied", headers={"Cache-Control": "no-store"})
    return ActorContext(tenant_id=cast(UUID, user.tenant_id), actor_id=cast(UUID, user.id), active_role=user.role)


def _error(exc: Exception) -> HTTPException:
    status = 409
    code = "lesson_correction_conflict"
    if isinstance(exc, WorkbenchNotFound):
        status, code = 404, "resource_not_found"
    elif isinstance(exc, CorrectionError) and str(exc) in SAFE_FAILURES:
        code = str(exc)
    elif isinstance(exc, WorkbenchConflict) and str(exc) in {
        "request_key_collision",
        "correction_confirmation_mismatch",
        "correction_preview_not_ready",
        "correction_clock_unavailable",
        "correction_application_busy",
    }:
        code = str(exc)
    return HTTPException(status, code, headers={"Cache-Control": "no-store"})


@router.post("/lesson-correction-previews", response_model=CorrectionPreviewResponse)
async def create_preview(
    body: CorrectionPreviewRequest, response: Response, db: DbSession, user: Methodologist
) -> CorrectionPreviewResponse:
    actor = _context(user, response)
    try:
        return await create_correction_preview(db, actor, body)
    except HTTPException:
        await db.rollback()
        raise
    except (CorrectionError, WorkbenchConflict, WorkbenchNotFound, SQLAlchemyError, ValidationError) as exc:
        await db.rollback()
        raise _error(exc) from exc


@router.get("/lesson-correction-previews/{plan_id}", response_model=CorrectionPreviewResponse)
async def read_preview(
    plan_id: UUID, response: Response, db: DbSession, user: Methodologist
) -> CorrectionPreviewResponse:
    actor = _context(user, response)
    try:
        return await get_correction_preview(db, actor, plan_id)
    except (CorrectionError, WorkbenchConflict, WorkbenchNotFound, SQLAlchemyError, ValidationError) as exc:
        await db.rollback()
        raise _error(exc) from exc


@router.post("/lesson-correction-previews/{plan_id}/apply", response_model=CorrectionApplicationResponse)
async def apply_preview(
    plan_id: UUID, body: ConfirmationRequest, response: Response, db: DbSession, user: Methodologist
) -> CorrectionApplicationResponse:
    actor = _context(user, response)
    if body.plan_id != plan_id:
        raise HTTPException(409, "correction_confirmation_mismatch", headers={"Cache-Control": "no-store"})
    try:
        return await apply_correction_preview(db, actor, body)
    except HTTPException:
        await db.rollback()
        raise
    except (
        CorrectionError,
        WorkbenchConflict,
        WorkbenchNotFound,
        SQLAlchemyError,
        ValidationError,
        TimeoutError,
    ) as exc:
        await db.rollback()
        raise _error(exc) from None


@router.get("/lesson-correction-previews/{plan_id}/application", response_model=CorrectionApplicationResponse)
async def read_application(
    plan_id: UUID, response: Response, db: DbSession, user: Methodologist
) -> CorrectionApplicationResponse:
    actor = _context(user, response)
    try:
        return await get_correction_application(db, actor, plan_id)
    except (CorrectionError, WorkbenchConflict, WorkbenchNotFound, SQLAlchemyError, ValidationError) as exc:
        await db.rollback()
        raise _error(exc) from None
