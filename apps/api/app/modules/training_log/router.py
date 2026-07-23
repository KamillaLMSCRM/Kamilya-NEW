"""Training log router — GET /api/v1/admin/training-log + CSV export.

P0.3 first-tenant hardening.

Endpoints:
- GET /api/v1/admin/training-log                 list (JSON Page[T])
- GET /api/v1/admin/training-log?format=csv      CSV stream
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_role
from app.core.db import get_db
from app.models.users import User
from app.modules.training_log.schemas import (
    TrainingLogFilter,
    TrainingLogPage,
    TrainingLogSummary,
)
from app.modules.training_log.service import (
    get_training_log_page,
    stream_training_log_as_csv,
    get_training_log_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/training-log",
    tags=["admin"],
)

# Roles allowed to read the training log. Per ADR-0012 the training log is
# an admin/HR concern: admin and org_admin manage the people side, while the
# methodologist owns learning trajectories. Superadmin is accepted but receives
# an empty result without tenant context. Students are excluded.
_TRAINING_LOG_ROLES = ("admin", "org_admin", "methodologist", "superadmin")


@router.get("/summary", response_model=TrainingLogSummary)
async def training_log_summary(
    response: Response,
    course_id: UUID | None = Query(default=None),
    department_id: UUID | None = Query(default=None),
    position_id: UUID | None = Query(default=None),
    status: Literal["assigned", "in_progress", "completed"] | None = Query(default=None),
    delivery_type: Literal["native", "scorm"] | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_TRAINING_LOG_ROLES)),
):
    response.headers["Cache-Control"] = "no-store"
    if user.tenant_id is None:
        return TrainingLogSummary(total=0, assigned=0, in_progress=0, completed=0)
    return await get_training_log_summary(
        db,
        user.tenant_id,
        TrainingLogFilter(
            course_id=course_id,
            department_id=department_id,
            position_id=position_id,
            status=status,
            delivery_type=delivery_type,
            date_from=date_from,
            date_to=date_to,
            search=search,
        ),
    )


@router.get("", response_model=TrainingLogPage)
async def list_training_log(
    request: Request,
    response: Response,
    course_id: UUID | None = Query(default=None),
    department_id: UUID | None = Query(default=None),
    position_id: UUID | None = Query(default=None),
    status: Literal["assigned", "in_progress", "completed"] | None = Query(default=None),
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
        course_id=course_id,
        department_id=department_id,
        position_id=position_id,
        status=status,
        delivery_type=delivery_type,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )

    if format == "csv":
        # Stream CSV with all rows matching the filter (no pagination cap).
        return StreamingResponse(
            stream_training_log_as_csv(db, user.tenant_id, f, lang=lang),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="training-log-'
                    + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                    + '.csv"'
                ),
                # No caching — training log is a live view.
                "Cache-Control": "no-store",
            },
        )

    return await get_training_log_page(
        db,
        user.tenant_id,
        f,
        limit=limit,
        offset=offset,
    )
