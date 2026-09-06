"""Protected LI-API V1 router; root registers it in the application."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User
from app.modules.learning_insights.schemas import CourseInsights, EnrollmentInsights, Review, ReviewUpdate
from app.modules.learning_insights.service import (
    LearningInsightsNotFoundError,
    LearningInsightsValidationError,
    SnapshotUnavailableError,
    get_course_insights,
    get_enrollment_insights,
    upsert_question_review,
)

router = APIRouter(prefix="/admin/learning-insights", tags=["learning-insights"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
InsightsUser = Annotated[User, Depends(require_role("methodologist"))]


def _tenant_id_or_403(user: User) -> UUID:
    if user.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Learning insights requires a tenant context")
    return UUID(str(user.tenant_id))


def _validate_aware_range(date_from: datetime | None, date_to: datetime | None) -> None:
    if date_from is not None and date_from.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="date_from must include a timezone"
        )
    if date_to is not None and date_to.tzinfo is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="date_to must include a timezone")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="date_from must not be after date_to"
        )


def _service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LearningInsightsNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Learning insights resource not found")
    if isinstance(exc, SnapshotUnavailableError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Immutable attempt evidence is unavailable")
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get("/enrollments/{enrollment_id}", response_model=EnrollmentInsights)
async def enrollment_insights(
    enrollment_id: UUID, response: Response, db: DbSession, user: InsightsUser
) -> EnrollmentInsights:
    response.headers["Cache-Control"] = "no-store"
    try:
        return await get_enrollment_insights(db, tenant_id=_tenant_id_or_403(user), enrollment_id=enrollment_id)
    except (LearningInsightsNotFoundError, LearningInsightsValidationError) as exc:
        raise _service_error(exc) from exc


@router.get("/courses/{course_id}", response_model=CourseInsights)
async def course_insights(
    course_id: UUID,
    response: Response,
    db: DbSession,
    user: InsightsUser,
    department_id: UUID | None = None,
    position_id: UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> CourseInsights:
    response.headers["Cache-Control"] = "no-store"
    _validate_aware_range(date_from, date_to)
    try:
        return await get_course_insights(
            db,
            tenant_id=_tenant_id_or_403(user),
            course_id=course_id,
            department_id=department_id,
            position_id=position_id,
            date_from=date_from,
            date_to=date_to,
        )
    except (LearningInsightsNotFoundError, LearningInsightsValidationError) as exc:
        raise _service_error(exc) from exc


@router.put("/attempts/{attempt_id}/questions/{question_id}/review", response_model=Review)
async def put_question_review(
    attempt_id: UUID,
    question_id: UUID,
    body: ReviewUpdate,
    response: Response,
    db: DbSession,
    user: InsightsUser,
) -> Review:
    response.headers["Cache-Control"] = "no-store"
    try:
        return await upsert_question_review(
            db,
            tenant_id=_tenant_id_or_403(user),
            # Platform impersonation is authenticated by core.auth; its real
            # actor is not a local tenant user and cannot satisfy the tenant FK.
            actor_id=None if getattr(user, "is_impersonating", False) else UUID(str(user.id)),
            attempt_id=attempt_id,
            question_id=question_id,
            status=body.status,
        )
    except (LearningInsightsNotFoundError, SnapshotUnavailableError) as exc:
        raise _service_error(exc) from exc
