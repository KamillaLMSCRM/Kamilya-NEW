"""Admin dashboard API router"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import io

from app.core.auth import require_role
from app.core.db import get_db
from app.modules.admin.schemas import AdminDashboard, TenantStats, TrialUsage
from app.modules.admin.service import get_admin_dashboard, get_tenant_stats, get_trial_usage
from app.modules.admin.export import (
    export_users_csv,
    export_courses_csv,
    export_enrollments_csv,
    export_quiz_results_csv,
)
from app.models.users import User

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/dashboard", response_model=AdminDashboard)
async def dashboard(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin")),
):
    """Get admin dashboard (admin only)."""
    return await get_admin_dashboard(db, user.tenant_id)


@router.get("/stats", response_model=TenantStats)
async def stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin")),
):
    """Get tenant statistics (admin only)."""
    return await get_tenant_stats(db, user.tenant_id)


@router.get("/trial-usage", response_model=TrialUsage)
async def trial_usage(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "methodologist", "teacher")),
):
    """Get tenant-facing trial limits and current usage."""
    try:
        return await get_trial_usage(db, user.tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/export/users")
async def export_users(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin")),
):
    """Export users to CSV (admin only)."""
    csv_data = await export_users_csv(db, user.tenant_id)
    return _csv_response(csv_data, "users.csv")


@router.get("/export/courses")
async def export_courses(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin")),
):
    """Export courses to CSV (admin only)."""
    csv_data = await export_courses_csv(db, user.tenant_id)
    return _csv_response(csv_data, "courses.csv")


# ADR-0012: enrollment CSV export is part of the methodologist's content
# domain (manual assignment workflow), not pure tenant infrastructure.
# Methodologist/teacher needs the export for compliance/handoff to HR.
_ENROLLMENT_REPORT_ROLES = ("methodologist", "teacher")


@router.get("/export/enrollments")
async def export_enrollments(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_ENROLLMENT_REPORT_ROLES)),
):
    """Export enrollments to CSV (methodologist/teacher only)."""
    csv_data = await export_enrollments_csv(db, user.tenant_id)
    return _csv_response(csv_data, "enrollments.csv")


@router.get("/export/quiz-results")
async def export_quiz_results(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin")),
):
    """Export quiz results to CSV (admin only)."""
    csv_data = await export_quiz_results_csv(db, user.tenant_id)
    return _csv_response(csv_data, "quiz-results.csv")


def _csv_response(csv_data: str, filename: str) -> StreamingResponse:
    """Wrap a CSV string in a UTF-8-BOM StreamingResponse.

    Without the BOM (\ufeff), Excel/Notepad interpret the bytes as cp1251
    and any Cyrillic in user/course/enrollment names renders as
    mojibake (e.g. "ID,Email,���,�������"). The `charset=utf-8` in
    media_type is what PowerShell `Invoke-WebRequest` and most browsers
    key off of when deciding how to decode the body.

    See P1 QA report 2026-07-10 bug #6.
    """
    return StreamingResponse(
        io.StringIO("\ufeff" + csv_data),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── Debug / observability ──────────────────────────────────────────────
# Endpoints here exist so an AI agent (or on-call engineer) can read
# runtime logs without opening the Render Dashboard. Capture happens in
# app.core.debug_log_buffer: every print() and logger.info() line is
# tee'd into a thread-safe ring buffer that survives until the
# container restarts.


@router.get("/debug/logs")
async def debug_logs(
    limit: int = 100,
    level: str | None = None,
    since_ts: float | None = None,
    user: User = Depends(require_role("superadmin")),
):
    """Return the last N log lines from the in-memory ring buffer.

    Query params:
      limit:  1..1000 (default 100)
      level:  minimum severity to return (DEBUG/INFO/WARNING/ERROR)
      since_ts: unix timestamp; return only records strictly after it

    Auth: superadmin only. Tenants have no business reading platform
    operator diagnostics.
    """
    from app.core import debug_log_buffer
    records = debug_log_buffer.get_recent(
        limit=min(max(limit, 1), 1000),
        level=level,
        since_ts=since_ts,
    )
    return {
        "count": len(records),
        "buffer_total": debug_log_buffer.get_recent(limit=1000).__len__(),
        "records": records,
    }


@router.delete("/debug/logs")
async def debug_logs_clear(
    user: User = Depends(require_role("superadmin")),
):
    """Wipe the in-memory log buffer. Useful when isolating a repro."""
    from app.core import debug_log_buffer
    debug_log_buffer.clear()
    return {"status": "cleared"}
