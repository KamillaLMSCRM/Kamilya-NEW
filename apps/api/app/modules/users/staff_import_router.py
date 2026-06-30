"""Staff import endpoints — admin uploads Excel/CSV штатное расписание.

Stage 1d of employee onboarding epic.

Endpoints:
- POST /admin/staff/import/preview           multipart file → returns ParsedFile + PreviewResult
- POST /admin/staff/import/commit            same payload structure → applies changes, returns counts
- GET  /admin/staff/apply-rules/status/{tid} poll Celery task state (B1c)
"""
import logging

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.celery_app import celery_app
from app.core.db import get_db
from app.models.users import User
from app.modules.users.staff_import_service import (
    ParsedFile,
    PreviewResult,
    build_preview,
    commit_import,
    parse_upload,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/staff", tags=["staff-import"])


class PreviewItemResponse(BaseModel):
    row_number: int
    personnel_number: str
    first_name: str
    last_name: str
    department: str
    position: str
    email: str | None
    phone: str | None
    action: str  # 'create' | 'update' | 'skip'
    existing_user_id: str | None
    notes: list[str]


class PreviewResponse(BaseModel):
    items: list[PreviewItemResponse]
    new_positions: list[str]
    new_departments: list[str]
    summary: dict
    invalid_rows: list[dict] = []  # rows that failed to parse (with errors)
    missing_required_columns: list[str] = []
    total_rows_in_file: int = 0


class CommitResponse(BaseModel):
    created: int
    updated: int
    skipped: int
    positions_created: int
    # B1b: when present, a Celery task has been dispatched to apply
    # course-assignment rules for these users. The frontend can poll
    # for the task result or simply refresh the staff structure page
    # once the rule processing settles.
    apply_rules_task_id: str | None = None
    affected_user_count: int = 0


def _parsed_file_to_response(parsed: ParsedFile, preview: PreviewResult | None = None) -> dict:
    """Convert internal dataclasses to JSON-friendly dict."""
    out = {
        "missing_required_columns": parsed.missing_required_columns,
        "total_rows_in_file": parsed.total_rows_in_file,
        "invalid_rows": parsed.invalid_rows,
        "detected_columns": parsed.detected_columns,
    }
    if preview is not None:
        out["items"] = [
            {
                "row_number": it.row_number,
                "personnel_number": it.personnel_number,
                "first_name": it.first_name,
                "last_name": it.last_name,
                "department": it.department,
                "position": it.position,
                "email": it.email,
                "phone": it.phone,
                "action": it.action,
                "existing_user_id": it.existing_user_id,
                "notes": it.notes,
            }
            for it in preview.items
        ]
        out["new_positions"] = preview.new_positions
        out["new_departments"] = preview.new_departments
        out["summary"] = preview.summary
    return out


@router.post("/import/preview", response_model=PreviewResponse)
async def import_staff_preview(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin")),
):
    """Parse uploaded file (xlsx/csv) and return a preview of what would change.

    No DB writes. HR reviews, then POSTs to /import/commit to apply.
    """
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Файл пустой")
    if len(content) > 10 * 1024 * 1024:  # 10MB cap
        raise HTTPException(status_code=413, detail="Файл слишком большой (макс. 10 МБ)")

    try:
        parsed = parse_upload(file.filename or "upload", content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Не удалось прочитать файл: {type(e).__name__}: {e}",
        )

    if parsed.missing_required_columns:
        return _parsed_file_to_response(parsed, None)

    # Build preview (matches against DB)
    preview = await build_preview(db, user.tenant_id, parsed)

    # Inject invalid_rows count into summary so HR sees parse errors too
    preview.summary["invalid_rows"] = len(parsed.invalid_rows)
    return _parsed_file_to_response(parsed, preview)


@router.post("/import/commit", response_model=CommitResponse)
async def import_staff_commit(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin")),
):
    """Parse uploaded file and apply changes (create new users, update existing, auto-create positions).

    All-or-nothing: if any row fails to apply, the entire transaction is rolled back.
    """
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Файл пустой")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Файл слишком большой (макс. 10 МБ)")

    try:
        parsed = parse_upload(file.filename or "upload", content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Не удалось прочитать файл: {type(e).__name__}: {e}",
        )

    if parsed.missing_required_columns:
        raise HTTPException(
            status_code=400,
            detail=f"В файле отсутствуют обязательные колонки: {', '.join(parsed.missing_required_columns)}",
        )

    if parsed.invalid_rows:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "В файле есть строки с ошибками. Исправьте и попробуйте снова.",
                "invalid_rows": parsed.invalid_rows[:20],  # cap to first 20
                "total_invalid": len(parsed.invalid_rows),
            },
        )

    if not parsed.rows:
        raise HTTPException(status_code=400, detail="Файл не содержит данных")

    try:
        result = await commit_import(db, user.tenant_id, parsed)
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка применения: {type(e).__name__}: {e}",
        )

    # B1b: dispatch apply-rules to Celery for every affected user.
    # This materializes PositionCourse/DepartmentCourse into
    # Enrollment rows. Run in a worker process so the HTTP request
    # returns immediately. If the task fails, the staff data is
    # still consistent — apply-rules can be re-run via the
    # /admin/staff/apply-rules endpoint (B1c) without re-importing.
    affected_user_ids: list[str] = result.pop("affected_user_ids", [])
    task_id: str | None = None
    if affected_user_ids:
        try:
            from app.modules.positions.tasks import apply_rules_for_users_task
            async_result = apply_rules_for_users_task.delay(affected_user_ids)
            task_id = async_result.id
        except Exception as e:
            # Don't fail the import — log and continue. The user can
            # retry apply-rules manually. The import is the source
            # of truth for staff data; apply-rules is downstream.
            import logging
            logging.getLogger(__name__).exception(
                "apply-rules dispatch failed for %d users: %s",
                len(affected_user_ids), e,
            )

    return {
        "created": result["created"],
        "updated": result["updated"],
        "skipped": result["skipped"],
        "positions_created": result["positions_created"],
        "apply_rules_task_id": task_id,
        "affected_user_count": len(affected_user_ids),
    }


class ApplyRulesStatusResponse(BaseModel):
    """Polling response for /admin/staff/apply-rules/status/{task_id}.

    Maps Celery task states onto a UI-friendly surface. Frontend
    refreshes every 1–2s while `state in ("PENDING", "STARTED",
    "RECEIVED", "RETRY")` and stops on SUCCESS / FAILURE.

    `result` carries the per-task body — for `positions.apply_course_rules`
    that's the standard RecomputeRollup dict (users_processed, added,
    removed, skipped_manual, protected_completed, failed_user_ids, errors).
    """

    task_id: str
    state: str
    ready: bool
    successful: bool | None = None
    failed: bool | None = None
    result: dict | str | None = None
    error: str | None = None


@router.get("/apply-rules/status/{task_id}", response_model=ApplyRulesStatusResponse)
def get_apply_rules_status(
    task_id: str,
    user: User = Depends(require_role("admin", "org_admin", "superadmin", "methodologist")),
):
    """Return the current state of a Celery apply-rules task.

    Polling pattern (recommended for UI):
      - poll every 1s while state ∈ {PENDING, RECEIVED, STARTED, RETRY}
      - stop on SUCCESS/FAILURE
      - if FAILED, surface `error` to user, log it for support

    `require_role` ensures only admin / methodologist / superadmin
    can introspect task state — students must not see these
    results because they reveal other users' enrollment counts.
    """
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id is required")
    res = AsyncResult(task_id, app=celery_app)

    state = res.state          # PENDING | RECEIVED | STARTED | SUCCESS | FAILURE | RETRY | REVOKED
    ready = res.ready()
    successful = res.successful() if ready else None
    failed = res.failed() if ready else None

    body: dict | str | None = None
    err: str | None = None
    if state == "SUCCESS":
        try:
            body = res.result if isinstance(res.result, (dict, list, str, int, float, bool)) else str(res.result)
        except Exception as e:  # noqa: BLE001
            logger.warning("could not read SUCCESS result for %s: %s", task_id, e)
            body = None
    elif state == "FAILURE":
        try:
            err = str(res.result)
        except Exception as e:  # noqa: BLE001
            err = f"<error reading exception: {e!r}>"

    return ApplyRulesStatusResponse(
        task_id=task_id,
        state=state,
        ready=ready,
        successful=successful,
        failed=failed,
        result=body,
        error=err,
    )
