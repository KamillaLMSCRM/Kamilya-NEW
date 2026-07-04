"""Staff import endpoints — admin uploads Excel/CSV штатное расписание.

Stage 1d of employee onboarding epic.

Endpoints:
- POST /admin/staff/import/preview           multipart file → returns ParsedFile + PreviewResult
- POST /admin/staff/import/commit            same payload structure → applies changes, returns counts
- GET  /admin/staff/apply-rules/status/{tid} poll Celery task state (B1c)
"""
import logging
import json

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
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
    create_manual_staff_member,
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
    items: list[PreviewItemResponse] = Field(default_factory=list)
    new_positions: list[str] = Field(default_factory=list)
    new_departments: list[str] = Field(default_factory=list)
    summary: dict = Field(default_factory=lambda: {
        "create": 0,
        "update": 0,
        "skip": 0,
        "new_positions": 0,
        "new_departments": 0,
        "invalid_rows": 0,
    })
    invalid_rows: list[dict] = Field(default_factory=list)  # rows that failed to parse (with errors)
    missing_required_columns: list[str] = Field(default_factory=list)
    total_rows_in_file: int = 0
    detected_columns: dict[str, str] = Field(default_factory=dict)
    raw_columns: list[str] = Field(default_factory=list)
    sample_rows: list[dict[str, str]] = Field(default_factory=list)
    suggested_mapping: dict[str, str] = Field(default_factory=dict)
    sheet_name: str | None = None
    header_row: int = 1
    sheets: list[dict] = Field(default_factory=list)
    limit_warning: dict | None = None


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


class ManualStaffCreateRequest(BaseModel):
    personnel_number: str = Field(..., min_length=1, max_length=64)
    first_name: str = Field(..., min_length=1, max_length=120)
    last_name: str = Field(..., min_length=1, max_length=120)
    department: str = Field(..., min_length=1, max_length=160)
    position: str = Field(..., min_length=1, max_length=160)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=64)


class ManualStaffCreateResponse(BaseModel):
    created: int
    updated: int
    skipped: int
    positions_created: int
    apply_rules_task_id: str | None = None
    affected_user_count: int = 0


def _parsed_file_to_response(parsed: ParsedFile, preview: PreviewResult | None = None) -> dict:
    """Convert internal dataclasses to JSON-friendly dict."""
    out = {
        "missing_required_columns": parsed.missing_required_columns,
        "total_rows_in_file": parsed.total_rows_in_file,
        "invalid_rows": parsed.invalid_rows,
        "detected_columns": parsed.detected_columns,
        "raw_columns": parsed.raw_columns,
        "sample_rows": parsed.sample_rows,
        "suggested_mapping": parsed.suggested_mapping,
        "sheet_name": parsed.sheet_name,
        "header_row": parsed.header_row,
        "sheets": parsed.sheets,
        "limit_warning": None,
        "items": [],
        "new_positions": [],
        "new_departments": [],
        "summary": {
            "create": 0,
            "update": 0,
            "skip": 0,
            "new_positions": 0,
            "new_departments": 0,
            "invalid_rows": len(parsed.invalid_rows),
        },
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


def _parse_mapping(mapping: str | None) -> dict[str, str] | None:
    if not mapping:
        return None
    try:
        value = json.loads(mapping)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Некорректное сопоставление колонок")
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="Некорректное сопоставление колонок")
    return {str(k): str(v) for k, v in value.items() if v}


@router.post("/manual", response_model=ManualStaffCreateResponse, status_code=201)
async def create_manual_staff(
    payload: ManualStaffCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin", "methodologist", "teacher")),
):
    """Create one learner manually without uploading a staff file."""
    if not user.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant is required")

    existing_result = await db.execute(
        select(User).where(
            User.tenant_id == user.tenant_id,
            func.lower(User.personnel_number) == payload.personnel_number.strip().lower(),
        )
    )
    existing_user = existing_result.scalar_one_or_none()
    if existing_user is None:
        from app.core.trial_limits import assert_can_create_learners

        await assert_can_create_learners(db, user.tenant_id, requested=1)

    try:
        result = await create_manual_staff_member(
            db,
            user.tenant_id,
            personnel_number=payload.personnel_number,
            first_name=payload.first_name,
            last_name=payload.last_name,
            department=payload.department,
            position=payload.position,
            email=payload.email,
            phone=payload.phone,
        )
    except Exception as e:
        msg = str(e)
        if "uq_users_tenant_personnel" in msg or "duplicate key" in msg.lower():
            raise HTTPException(
                status_code=409,
                detail="Сотрудник с таким табельным номером уже существует",
            )
        raise

    return {
        "created": result["created"],
        "updated": result["updated"],
        "skipped": result["skipped"],
        "positions_created": result["positions_created"],
        "apply_rules_task_id": result.get("apply_rules_task_id"),
        "affected_user_count": len(result.get("affected_user_ids") or []),
    }


@router.post("/import/preview", response_model=PreviewResponse)
async def import_staff_preview(
    file: UploadFile = File(...),
    mapping: str = Form(""),
    sheet_name: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin", "methodologist")),
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
        parsed = parse_upload(
            file.filename or "upload",
            content,
            mapping=_parse_mapping(mapping),
            sheet_name=sheet_name or None,
        )
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
    response = _parsed_file_to_response(parsed, preview)
    try:
        from app.core.trial_limits import assert_can_create_learners
        await assert_can_create_learners(db, user.tenant_id, requested=int(preview.summary.get("create") or 0))
    except HTTPException as exc:
        response["limit_warning"] = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
    return response


@router.post("/import/commit", response_model=CommitResponse)
async def import_staff_commit(
    file: UploadFile = File(...),
    mapping: str = Form(""),
    sheet_name: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "org_admin", "superadmin", "methodologist")),
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
        parsed = parse_upload(
            file.filename or "upload",
            content,
            mapping=_parse_mapping(mapping),
            sheet_name=sheet_name or None,
        )
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
        preview = await build_preview(db, user.tenant_id, parsed)
        from app.core.trial_limits import assert_can_create_learners
        await assert_can_create_learners(
            db,
            user.tenant_id,
            requested=int(preview.summary.get("create") or 0),
        )
        result = await commit_import(db, user.tenant_id, parsed)
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка применения: {type(e).__name__}: {e}",
        )

    # P0-1 fix (TZ §2.6): commit_import now triggers apply-rules
    # INLINE (no Celery) and returns the Redis task_id directly.
    # The HTTP request blocks for the duration of apply-rules
    # (typically <10s for hundreds of users) and the response
    # includes the task_id for the UI to poll via
    # GET /admin/staff/apply-rules/status/{task_id}.
    affected_user_ids: list[str] = result.pop("affected_user_ids", [])
    task_id: str | None = result.pop("apply_rules_task_id", None)

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
async def get_apply_rules_status(
    task_id: str,
    user: User = Depends(require_role("admin", "org_admin", "superadmin", "methodologist")),
):
    """Return the current state of an apply-rules task.

    Two backends, tried in order:

    1. **Redis (inline path, P0-1 fix).** Since TZ §2.6 the import
       runs `apply_rules_for_users` inline, not in Celery. The
       task state is published to Redis at key
       `apply_rules:task:{task_id}` by `core/redis_progress.py`.
       This is the hot path.
    2. **Celery (retroactive / retry path).** The standalone
       `POST /admin/staff/apply-rules` endpoint still dispatches
       a Celery task for back-fills. We fall back to that result
       backend so the same status URL works for both flows.

    Polling pattern (recommended for UI):
      - poll every 1s while state ∈ {PENDING, STARTED}
      - stop on SUCCESS / FAILURE
      - if FAILED, surface `error` to user, log it for support

    `require_role` ensures only admin / methodologist / superadmin
    can introspect task state — students must not see these
    results because they reveal other users' enrollment counts.
    """
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id is required")

    # 1) Try Redis first.
    try:
        from app.core import redis_progress
        rd = await redis_progress.get_task(task_id)
    except Exception as exc:  # noqa: BLE001 — Redis hiccup must not 500
        logger.warning("redis get_task failed for %s: %s", task_id, exc)
        rd = None

    if rd:
        state = rd.get("state", "PENDING")
        done = rd.get("done", 0)
        total = rd.get("total", 0)
        ready = state in ("SUCCESS", "FAILURE")
        successful = state == "SUCCESS"
        failed = state == "FAILURE"
        body = {
            "users_processed": done,
            "total": total,
            "added": rd.get("added", 0),
            "removed": rd.get("removed", 0),
            "failed": rd.get("failed", 0),
        } if state == "SUCCESS" else None
        return ApplyRulesStatusResponse(
            task_id=task_id,
            state=state,
            ready=ready,
            successful=successful,
            failed=failed,
            result=body,
            error=rd.get("error") or None,
        )

    # 2) Fall back to Celery (for retroactive apply-rules tasks
    #    dispatched by the standalone endpoint).
    res = AsyncResult(task_id, app=celery_app)
    state = res.state
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
