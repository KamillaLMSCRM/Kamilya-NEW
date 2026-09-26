"""Tenant-scoped mandatory-training matrix and summary routes."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User
from app.modules.mandatory_training.requirements import (
    RequirementAction,
    RequirementState,
)
from app.modules.mandatory_training.schemas import (
    MandatoryTrainingFilter,
    MandatoryTrainingPage,
    MandatoryTrainingSummary,
)
from app.modules.mandatory_training.service import (
    get_mandatory_training_page,
    get_mandatory_training_summary,
)
from app.modules.training_responsibility import resolve_reporting_scope
from app.modules.training_responsibility.policy import ReportingScopeMode

router = APIRouter(prefix="/admin/mandatory-training", tags=["admin"])

_REPORTING_ROLES = ("admin", "methodologist", "superadmin")
_reporting_role = require_role(*_REPORTING_ROLES)


def _filters(
    *,
    course_id: UUID | None,
    organization_unit_id: UUID | None,
    position_id: UUID | None,
    requirement_state: RequirementState | None,
    action_required: RequirementAction | None,
    search: str | None,
    include_inactive: bool,
) -> MandatoryTrainingFilter:
    return MandatoryTrainingFilter(
        course_id=course_id,
        organization_unit_id=organization_unit_id,
        position_id=position_id,
        requirement_state=requirement_state,
        action_required=action_required,
        search=search,
        include_inactive=include_inactive,
    )


@router.get("/summary", response_model=MandatoryTrainingSummary)
async def mandatory_training_summary(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_reporting_role)],
    course_id: Annotated[UUID | None, Query()] = None,
    organization_unit_id: Annotated[UUID | None, Query()] = None,
    position_id: Annotated[UUID | None, Query()] = None,
    requirement_state: Annotated[RequirementState | None, Query()] = None,
    action_required: Annotated[RequirementAction | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    include_inactive: Annotated[bool, Query()] = False,
) -> MandatoryTrainingSummary:
    response.headers["Cache-Control"] = "no-store"
    if user.tenant_id is None:
        return MandatoryTrainingSummary(
            total=0,
            materialized=0,
            missing_enrollment=0,
            protected_assignment=0,
            stale_managed_enrollment=0,
            action_materialize=0,
            action_review_stale=0,
        )
    tenant_id = cast(UUID, user.tenant_id)
    user_id = cast(UUID, user.id)
    role = cast(str, user.role)
    try:
        reporting_scope = await resolve_reporting_scope(
            db,
            tenant_id,
            user_id=user_id,
            role=role,
        )
        filters = _filters(
            course_id=course_id,
            organization_unit_id=organization_unit_id,
            position_id=position_id,
            requirement_state=requirement_state,
            action_required=action_required,
            search=search,
            include_inactive=include_inactive,
        )
        if reporting_scope.mode is ReportingScopeMode.RESTRICTED:
            filters = filters.model_copy(
                update={"responsible_user_ids": reporting_scope.user_ids}
            )
        return await get_mandatory_training_summary(
            db,
            tenant_id,
            filters,
        )
    except ValueError as exc:
        if str(exc) != "mandatory_training_scope_too_large":
            raise
        raise HTTPException(
            status_code=422,
            detail={"code": "mandatory_training_scope_too_large"},
        ) from exc


@router.get("", response_model=MandatoryTrainingPage)
async def list_mandatory_training(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(_reporting_role)],
    course_id: Annotated[UUID | None, Query()] = None,
    organization_unit_id: Annotated[UUID | None, Query()] = None,
    position_id: Annotated[UUID | None, Query()] = None,
    requirement_state: Annotated[RequirementState | None, Query()] = None,
    action_required: Annotated[RequirementAction | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    include_inactive: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MandatoryTrainingPage:
    response.headers["Cache-Control"] = "no-store"
    if user.tenant_id is None:
        return MandatoryTrainingPage(items=[], total=0, limit=limit, offset=offset)
    tenant_id = cast(UUID, user.tenant_id)
    user_id = cast(UUID, user.id)
    role = cast(str, user.role)
    try:
        reporting_scope = await resolve_reporting_scope(
            db,
            tenant_id,
            user_id=user_id,
            role=role,
        )
        filters = _filters(
            course_id=course_id,
            organization_unit_id=organization_unit_id,
            position_id=position_id,
            requirement_state=requirement_state,
            action_required=action_required,
            search=search,
            include_inactive=include_inactive,
        )
        if reporting_scope.mode is ReportingScopeMode.RESTRICTED:
            filters = filters.model_copy(
                update={"responsible_user_ids": reporting_scope.user_ids}
            )
        page = await get_mandatory_training_page(
            db,
            tenant_id,
            filters,
            limit=limit,
            offset=offset,
        )
        return page.model_copy(update={"reporting_scope": reporting_scope.mode.value})
    except ValueError as exc:
        if str(exc) != "mandatory_training_scope_too_large":
            raise
        raise HTTPException(
            status_code=422,
            detail={"code": "mandatory_training_scope_too_large"},
        ) from exc
