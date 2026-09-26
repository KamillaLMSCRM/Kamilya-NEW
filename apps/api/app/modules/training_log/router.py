"""Training log router — GET /api/v1/admin/training-log + CSV export.

P0.3 first-tenant hardening.

Endpoints:
- GET /api/v1/admin/training-log                 list (JSON Page[T])
- GET /api/v1/admin/training-log?format=csv      CSV stream
"""

# FastAPI Query/Depends factories are intentionally declared in signatures.
# ruff: noqa: B008

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.users import User
from app.modules.training_log.schemas import (
    TrainingLogFilter,
    TrainingLogPage,
    TrainingLogSummary,
)
from app.modules.training_log.service import (
    get_training_log_page,
    get_training_log_summary,
    stream_training_log_as_csv,
)
from app.modules.training_responsibility import resolve_reporting_scope
from app.modules.training_responsibility.policy import ReportingScopeMode

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/training-log",
    tags=["admin"],
)

# Tenant admins may read/export reporting, while evidence management remains
# methodologist-only in its separate API and UI flows.
_TRAINING_LOG_ROLES = ("admin", "methodologist", "superadmin")


@router.get("/summary", response_model=TrainingLogSummary)
async def training_log_summary(
    response: Response,
    enrollment_id: Annotated[UUID | None, Query()] = None,
    course_id: UUID | None = Query(default=None),
    department_id: UUID | None = Query(default=None),
    position_id: UUID | None = Query(default=None),
    status: Literal["assigned", "in_progress", "completed", "overdue", "cancelled", "superseded"] | None = Query(
        default=None
    ),
    history: bool = Query(default=False),
    delivery_type: Literal["native", "scorm"] | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_TRAINING_LOG_ROLES)),
):
    response.headers["Cache-Control"] = "no-store"
    if user.tenant_id is None:
        return TrainingLogSummary(total=0, assigned=0, in_progress=0, completed=0, overdue=0)
    reporting_scope = await resolve_reporting_scope(
        db,
        user.tenant_id,
        user_id=user.id,
        role=user.role,
    )
    filters = TrainingLogFilter(
        enrollment_id=enrollment_id,
        course_id=course_id,
        department_id=department_id,
        position_id=position_id,
        status=status,
        history=history,
        delivery_type=delivery_type,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )
    if reporting_scope.mode is ReportingScopeMode.RESTRICTED:
        filters = filters.model_copy(
            update={"responsible_user_ids": reporting_scope.user_ids}
        )
    return await get_training_log_summary(
        db,
        user.tenant_id,
        filters,
    )


@router.get("", response_model=TrainingLogPage)
async def list_training_log(
    request: Request,
    response: Response,
    enrollment_id: Annotated[UUID | None, Query()] = None,
    course_id: UUID | None = Query(default=None),
    department_id: UUID | None = Query(default=None),
    position_id: UUID | None = Query(default=None),
    status: Literal["assigned", "in_progress", "completed", "overdue", "cancelled", "superseded"] | None = Query(
        default=None
    ),
    history: bool = Query(default=False),
    delivery_type: Literal["native", "scorm"] | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    format: Literal["json", "csv"] = Query(default="json"),
    lang: Literal["ru", "kk", "en"] = Query(default="ru"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_TRAINING_LOG_ROLES)),
):
    """List rows of the unified training log (native + SCORM in one view).

    Returns Page[TrainingLogRow]. Pass `format=csv` to get a CSV stream
    with the same filters (no pagination — full export).
    """
    if user.tenant_id is None:
        # superadmin without a tenant — return empty result (not 500)
        # rather than leaking cross-tenant data.
        if format == "csv":
            return StreamingResponse(iter([b"\xef\xbb\xbf"]), media_type="text/csv")
        return TrainingLogPage(items=[], total=0, limit=limit, offset=offset)

    response.headers["Cache-Control"] = "no-store"

    f = TrainingLogFilter(
        enrollment_id=enrollment_id,
        course_id=course_id,
        department_id=department_id,
        position_id=position_id,
        status=status,
        history=history,
        delivery_type=delivery_type,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )
    reporting_scope = await resolve_reporting_scope(
        db,
        user.tenant_id,
        user_id=user.id,
        role=user.role,
    )
    if reporting_scope.mode is ReportingScopeMode.RESTRICTED:
        f = f.model_copy(update={"responsible_user_ids": reporting_scope.user_ids})

    if format == "csv":
        # Stream CSV with all rows matching the filter (no pagination cap).
        return StreamingResponse(
            stream_training_log_as_csv(db, user.tenant_id, f, lang=lang),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="training-log-' + datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + '.csv"'
                ),
                # No caching — training log is a live view.
                "Cache-Control": "no-store",
            },
        )

    page = await get_training_log_page(
        db,
        user.tenant_id,
        f,
        limit=limit,
        offset=offset,
    )
    return page.model_copy(update={"reporting_scope": reporting_scope.mode.value})
