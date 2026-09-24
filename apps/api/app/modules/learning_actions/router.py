from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User
from app.modules.learning_actions.schemas import (
    LearningActionClose,
    LearningActionCreate,
    LearningActionList,
    LearningActionRecord,
)
from app.modules.learning_actions.service import (
    LearningActionConflictError,
    LearningActionNotFoundError,
    close_learning_action,
    create_learning_action,
    list_learning_actions,
)

router = APIRouter(prefix="/admin/learning-actions", tags=["learning-actions"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
Methodologist = Annotated[User, Depends(require_role("methodologist"))]


def _tenant_id_or_403(user: User) -> UUID:
    if user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Learning actions requires a tenant context")
    return UUID(str(user.tenant_id))


def _service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LearningActionNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Learning action resource not found")
    if isinstance(exc, LearningActionConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("", response_model=LearningActionList)
async def get_learning_actions(
    response: Response,
    db: DbSession,
    user: Methodologist,
    course_id: UUID | None = None,
    status_filter: Annotated[Literal["open", "completed", "cancelled"], Query(alias="status")] = "open",
) -> LearningActionList:
    response.headers["Cache-Control"] = "no-store"
    try:
        return await list_learning_actions(
            db, tenant_id=_tenant_id_or_403(user), course_id=course_id, status=status_filter
        )
    except (LearningActionNotFoundError, LearningActionConflictError) as exc:
        raise _service_error(exc) from exc


@router.post("", response_model=LearningActionRecord, status_code=status.HTTP_201_CREATED)
async def post_learning_action(
    body: LearningActionCreate,
    response: Response,
    db: DbSession,
    user: Methodologist,
) -> LearningActionRecord:
    response.headers["Cache-Control"] = "no-store"
    try:
        return await create_learning_action(
            db,
            tenant_id=_tenant_id_or_403(user),
            actor_id=None if getattr(user, "is_impersonating", False) else UUID(str(user.id)),
            body=body,
        )
    except (LearningActionNotFoundError, LearningActionConflictError) as exc:
        raise _service_error(exc) from exc


@router.post("/{action_id}/close", response_model=LearningActionRecord)
async def post_close_learning_action(
    action_id: UUID,
    body: LearningActionClose,
    response: Response,
    db: DbSession,
    user: Methodologist,
) -> LearningActionRecord:
    response.headers["Cache-Control"] = "no-store"
    try:
        return await close_learning_action(
            db,
            tenant_id=_tenant_id_or_403(user),
            actor_id=None if getattr(user, "is_impersonating", False) else UUID(str(user.id)),
            action_id=action_id,
            resolution=body.resolution,
            note=body.note,
        )
    except (LearningActionNotFoundError, LearningActionConflictError) as exc:
        raise _service_error(exc) from exc
