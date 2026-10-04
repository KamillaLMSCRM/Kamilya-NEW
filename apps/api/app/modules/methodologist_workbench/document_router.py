"""Human-confirmed document draft commands; independently disabled by default."""

from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.config import get_settings
from app.core.db import get_db
from app.models.users import User

from .assignment_service import WorkbenchConflict, WorkbenchNotFound
from .document_intent import DocumentCandidate, DocumentClarification, DocumentInterpretRequest, interpret_document
from .document_schemas import DocumentExecution, DocumentPlanResponse, DocumentPreview, DocumentPreviewRequest
from .document_service import confirm_document_plan, create_document_preview, get_document_plan
from .plan_contract import ActorContext, ConfirmationRequest

router = APIRouter()
DbSession = Annotated[AsyncSession, Depends(get_db)]
Methodologist = Annotated[User, Depends(require_role("methodologist"))]


class InterpretedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["interpreted"] = "interpreted"
    candidate: DocumentCandidate


def _context(user: User, response: Response) -> ActorContext:
    response.headers["Cache-Control"] = "no-store"
    settings = get_settings()
    if not settings.METHODOLOGIST_WORKBENCH_ENABLED or not settings.METHODOLOGIST_DOCUMENT_DRAFT_ENABLED:
        raise HTTPException(404, "document_workbench_disabled")
    if user.tenant_id is None or getattr(user, "is_impersonating", False):
        raise HTTPException(403, "workbench_context_denied")
    return ActorContext(tenant_id=cast(UUID, user.tenant_id), actor_id=cast(UUID, user.id), active_role=user.role)


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, WorkbenchNotFound):
        return HTTPException(404, "resource_not_found")
    if isinstance(exc, IntegrityError | OperationalError):
        return HTTPException(409, "document_conflict")
    return HTTPException(409, str(exc))


@router.post("/document-preview", response_model=DocumentPreview)
async def preview_document(body: DocumentPreviewRequest, response: Response, db: DbSession,
                           user: Methodologist) -> DocumentPreview:
    actor = _context(user, response)
    try:
        result = await create_document_preview(db, actor, body)
        await db.commit()
        return result
    except (WorkbenchConflict, WorkbenchNotFound, IntegrityError, OperationalError) as exc:
        await db.rollback()
        raise _error(exc) from exc


@router.post("/interpret-document", response_model=InterpretedDocument | DocumentClarification)
async def interpret_instruction(body: DocumentInterpretRequest, response: Response, db: DbSession,
                                user: Methodologist) -> InterpretedDocument | DocumentClarification:
    actor = _context(user, response)
    try:
        result = await interpret_document(db, actor, body)
        await db.commit()
        return InterpretedDocument(candidate=result) if isinstance(result, DocumentCandidate) else result
    except HTTPException:
        await db.rollback()
        raise
    except (WorkbenchConflict, WorkbenchNotFound, IntegrityError, OperationalError) as exc:
        await db.rollback()
        raise _error(exc) from exc


@router.get("/document-plans/{plan_id}", response_model=DocumentPlanResponse)
async def read_document(plan_id: UUID, response: Response, db: DbSession,
                        user: Methodologist) -> DocumentPlanResponse:
    actor = _context(user, response)
    try:
        return await get_document_plan(db, actor, plan_id)
    except (WorkbenchConflict, WorkbenchNotFound) as exc:
        raise _error(exc) from exc


@router.post("/document-plans/{plan_id}/confirm", response_model=DocumentExecution)
async def confirm_document(plan_id: UUID, body: ConfirmationRequest, response: Response,
                           db: DbSession, user: Methodologist) -> DocumentExecution:
    actor = _context(user, response)
    if body.plan_id != plan_id:
        raise HTTPException(422, "plan_id_mismatch")
    try:
        # The existing generation command owns admission commit and dispatch.
        return await confirm_document_plan(db, actor, body, user)
    except HTTPException:
        await db.rollback()
        raise
    except (WorkbenchConflict, WorkbenchNotFound, IntegrityError, OperationalError) as exc:
        await db.rollback()
        raise _error(exc) from exc
