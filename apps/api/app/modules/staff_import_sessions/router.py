from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.core.storage import get_storage
from app.models.staff_import_mapping import StaffImportMapping
from app.models.staff_import_session import StaffImportSession
from app.models.users import User
from app.modules.staff_import_legacy_adapter import adapt_legacy_rows
from app.modules.staff_workbook_analysis import (
    analyze_staff_workbook,
    compute_workbook_signature,
    load_staff_workbook,
)
from app.modules.users.staff_import_service import parse_upload

from .commit_service import (
    commit_approved_import_session,
    mark_rule_recompute_failed,
    run_committed_rule_recompute,
)
from .corrections import apply_proposal_corrections
from .persistence import (
    approve_import_session,
    cleanup_expired_import_sources,
    create_import_session,
    ensure_approved_mapping_profile,
    get_import_session,
    save_proposal,
    save_workbook_analysis,
)
from .repository_matching import reconcile_proposal_with_database
from .schemas import (
    ImportMode,
    ImportSessionConflict,
    ImportSessionProposal,
    ImportSessionState,
    ProposalCorrection,
    SourceCellRef,
)

MAX_IMPORT_BYTES = 20 * 1024 * 1024
PARSER_VERSION = "adaptive-staff-import-v1"
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/staff/import/sessions", tags=["staff-import-sessions"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
Methodologist = Annotated[User, Depends(require_role("methodologist"))]


class ImportSessionResponse(BaseModel):
    id: UUID
    mapping_id: UUID | None
    state: str
    mode: str
    source_file_name: str
    source_file_sha256: str
    source_format: str
    workbook_analysis: dict[str, Any] | None
    mapping_json: dict[str, str] | None
    proposal: ImportSessionProposal | None
    proposal_revision: str | None
    expires_at: Any
    result_summary: dict[str, Any] | None

    model_config = ConfigDict(extra="forbid")


class ApproveImportSessionRequest(BaseModel):
    revision: str = Field(..., min_length=5, max_length=120)
    full_reconciliation_confirmation: bool = False

    model_config = ConfigDict(extra="forbid")


class CommitImportSessionRequest(BaseModel):
    revision: str = Field(..., min_length=5, max_length=120)

    model_config = ConfigDict(extra="forbid")


class ApplyImportMappingRequest(BaseModel):
    mapping_json: dict[str, str]
    sheet_name: str | None = Field(default=None, max_length=120)

    model_config = ConfigDict(extra="forbid")


class CorrectImportProposalRequest(BaseModel):
    revision: str = Field(..., min_length=5, max_length=120)
    corrections: list[ProposalCorrection] = Field(..., min_length=1, max_length=500)

    model_config = ConfigDict(extra="forbid")


def _response(record: StaffImportSession) -> ImportSessionResponse:
    proposal = ImportSessionProposal.model_validate(record.proposal_json) if record.proposal_json is not None else None
    return ImportSessionResponse(
        id=record.id,
        mapping_id=record.mapping_id,
        state=record.state,
        mode=record.mode,
        source_file_name=record.source_file_name,
        source_file_sha256=record.source_file_sha256,
        source_format=record.source_format,
        workbook_analysis=record.workbook_analysis,
        mapping_json=record.mapping_json,
        proposal=proposal,
        proposal_revision=record.proposal_revision,
        expires_at=record.expires_at,
        result_summary=record.result_summary,
    )


def _parse_mapping(value: str | None) -> dict[str, str] | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="mapping_json must be valid JSON") from exc
    if not isinstance(parsed, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in parsed.items()
    ):
        raise HTTPException(status_code=422, detail="mapping_json must be an object of strings")
    return parsed


async def _restore_tenant_context(db: AsyncSession, tenant_id: UUID) -> None:
    """Restore transaction-local RLS context after a commit or rollback."""

    await db.execute(
        text("SELECT set_current_tenant(:tenant_id)"),
        {"tenant_id": str(tenant_id)},
    )


def _source_object_key(tenant_id: UUID, session_id: UUID, suffix: str) -> str:
    return f"staff-import-sessions/{tenant_id}/{session_id}/source.{suffix}"


async def _analyze_and_save(
    db: AsyncSession,
    *,
    record: StaffImportSession,
    user: User,
    content: bytes,
    filename: str,
    workbook_analysis: Any,
    workbook_signature: str,
    mapping: dict[str, str] | None,
    sheet_name: str | None,
    matched_profile: StaffImportMapping | None = None,
) -> StaffImportSession:
    parsed = parse_upload(filename, content, mapping=mapping, sheet_name=sheet_name)
    analysis_payload = asdict(workbook_analysis)
    analysis_payload["workbook_signature"] = workbook_signature
    analysis_payload["matched_profile"] = matched_profile.name if matched_profile is not None else None
    analysis_payload["parser"] = {
        "detected_columns": parsed.detected_columns,
        "missing_required_columns": parsed.missing_required_columns,
        "raw_columns": parsed.raw_columns,
        "suggested_mapping": parsed.suggested_mapping,
        "selected_sheet": parsed.sheet_name,
        "header_row": parsed.header_row,
        "invalid_rows": [
            {"row_number": item.get("row_number"), "errors": item.get("errors", [])} for item in parsed.invalid_rows
        ],
    }
    record = await save_workbook_analysis(
        db,
        tenant_id=user.tenant_id,
        session_id=record.id,
        actor_id=user.id,
        analysis=analysis_payload,
        mapping=mapping or parsed.suggested_mapping,
        needs_mapping=bool(parsed.missing_required_columns),
    )
    if parsed.missing_required_columns:
        return record

    proposal = adapt_legacy_rows(
        tenant_id=user.tenant_id,
        source_file_name=filename,
        source_file_sha256=record.source_file_sha256,
        rows=parsed.rows,
        sheet_name=parsed.sheet_name or "Лист1",
        mode=ImportMode(record.mode),
    )
    proposal = await reconcile_proposal_with_database(
        db,
        tenant_id=user.tenant_id,
        proposal=proposal,
    )
    if parsed.invalid_rows:
        proposal = proposal.model_copy(
            update={
                "conflicts": [
                    *proposal.conflicts,
                    *[
                        ImportSessionConflict(
                            conflict_code="invalid_source_row",
                            scope="source_row",
                            message="; ".join(item.get("errors", [])) or "Строка не распознана.",
                            blocking=True,
                            source_refs=[
                                SourceCellRef(
                                    sheet=parsed.sheet_name or "Лист1",
                                    row=int(item.get("row_number") or 1),
                                    column="A",
                                )
                            ],
                        )
                        for item in parsed.invalid_rows
                    ],
                ]
            }
        )
    return await save_proposal(
        db,
        tenant_id=user.tenant_id,
        session_id=record.id,
        actor_id=user.id,
        proposal=proposal,
    )


@router.post("/analyze", response_model=ImportSessionResponse, status_code=status.HTTP_201_CREATED)
async def analyze_import_session(
    db: DbSession,
    user: Methodologist,
    file: Annotated[UploadFile, File(...)],
    idempotency_key: Annotated[str, Form(min_length=8, max_length=200)],
    mapping_json: Annotated[str | None, Form()] = None,
    mapping_id: Annotated[UUID | None, Form()] = None,
    sheet_name: Annotated[str | None, Form(max_length=120)] = None,
    mode: Annotated[ImportMode, Form()] = ImportMode.ADD_OR_UPDATE,
):
    if mode is ImportMode.FULL_RECONCILIATION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Режим полной сверки пока недоступен. Используйте добавление и обновление.",
        )
    content = await file.read(MAX_IMPORT_BYTES + 1)
    if not content:
        raise HTTPException(status_code=422, detail="Файл пуст.")
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="Файл превышает лимит 20 МБ.")
    filename = (file.filename or "staff.xlsx").strip()
    suffix = filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""
    if suffix not in {"xls", "xlsx", "csv"}:
        raise HTTPException(status_code=422, detail="Поддерживаются только .xls, .xlsx и .csv.")
    digest = sha256(content).hexdigest()
    mapping = _parse_mapping(mapping_json)
    profile: StaffImportMapping | None = None
    persisted_key: str | None = None
    try:
        await cleanup_expired_import_sources(
            db,
            tenant_id=user.tenant_id,
            storage=get_storage(),
        )
        await db.commit()
        # PostgreSQL's tenant context is transaction-local.  The cleanup
        # commit above deliberately closes its transaction, so restore the
        # context before inserting a session guarded by FORCE RLS and the
        # actor/tenant ownership trigger.
        await _restore_tenant_context(db, user.tenant_id)
        workbook_analysis = analyze_staff_workbook(load_staff_workbook(content, filename))
        initial_parse = parse_upload(filename, content, mapping=None, sheet_name=sheet_name)
        workbook_signature = compute_workbook_signature(
            workbook_analysis,
            selected_sheet=initial_parse.sheet_name,
            raw_columns=initial_parse.raw_columns,
        )
        if mapping is None and mapping_id is not None:
            selected_profile_result = await db.execute(
                select(StaffImportMapping).where(
                    StaffImportMapping.id == mapping_id,
                    StaffImportMapping.tenant_id == user.tenant_id,
                )
            )
            profile = selected_profile_result.scalar_one_or_none()
            if profile is None:
                raise HTTPException(status_code=404, detail="Column mapping not found")
            mapping = dict(profile.mapping_json or {})
        if mapping is None:
            profile_result = await db.execute(
                select(StaffImportMapping).where(
                    StaffImportMapping.tenant_id == user.tenant_id,
                    StaffImportMapping.workbook_signature == workbook_signature,
                )
            )
            profile = profile_result.scalar_one_or_none()
            if profile is not None:
                mapping = dict(profile.mapping_json or {})
        record = await create_import_session(
            db,
            tenant_id=user.tenant_id,
            actor_id=user.id,
            actor_role=user.role,
            idempotency_key=idempotency_key,
            source_file_name=filename,
            source_file_sha256=digest,
            source_format=suffix,
            source_size_bytes=len(content),
            parser_version=PARSER_VERSION,
            mode=mode,
            mapping_id=profile.id if profile is not None else None,
        )
        if record.workbook_analysis is not None:
            return _response(record)
        if record.source_object_key is None:
            persisted_key = _source_object_key(user.tenant_id, record.id, suffix)
            get_storage().put_bytes(
                persisted_key,
                content,
                content_type=file.content_type or "application/octet-stream",
            )
            record.source_object_key = persisted_key
            await db.flush()
        record = await _analyze_and_save(
            db,
            record=record,
            user=user,
            content=content,
            filename=filename,
            workbook_analysis=workbook_analysis,
            workbook_signature=workbook_signature,
            mapping=mapping,
            sheet_name=sheet_name,
            matched_profile=profile,
        )
        await db.commit()
        try:
            from .retention_tasks import cleanup_expired_import_sources_task

            cleanup_expired_import_sources_task.apply_async(
                args=[str(user.tenant_id), str(record.id)],
                eta=record.expires_at,
            )
        except Exception:  # noqa: BLE001 - opportunistic API cleanup remains available
            logger.warning("staff import source cleanup task could not be scheduled", exc_info=True)
        return _response(record)
    except HTTPException:
        await db.rollback()
        raise
    except ValueError as exc:
        await db.rollback()
        if persisted_key is not None:
            get_storage().delete_bytes(persisted_key)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        await db.rollback()
        if persisted_key is not None:
            try:
                get_storage().delete_bytes(persisted_key)
            except Exception:  # noqa: BLE001 - preserve the original failure
                pass
        raise


@router.post("/{session_id}/mapping", response_model=ImportSessionResponse)
async def apply_session_mapping(
    session_id: UUID,
    body: ApplyImportMappingRequest,
    db: DbSession,
    user: Methodologist,
):
    try:
        record = await get_import_session(
            db,
            tenant_id=user.tenant_id,
            session_id=session_id,
            for_update=True,
        )
        if record.state != "needs_mapping":
            raise ValueError("session is not waiting for column mapping")
        if record.expires_at is not None and record.expires_at <= datetime.now(UTC):
            raise ValueError("import session expired; upload the workbook again")
        if not record.source_object_key:
            raise ValueError("source workbook is unavailable; upload it again")
        content = get_storage().get_bytes(record.source_object_key)
        if content is None:
            raise ValueError("source workbook is unavailable; upload it again")
        if sha256(content).hexdigest() != record.source_file_sha256:
            raise ValueError("stored source workbook failed integrity verification")

        workbook_analysis = analyze_staff_workbook(load_staff_workbook(content, record.source_file_name))
        initial_parse = parse_upload(
            record.source_file_name,
            content,
            mapping=None,
            sheet_name=body.sheet_name,
        )
        signature = compute_workbook_signature(
            workbook_analysis,
            selected_sheet=initial_parse.sheet_name,
            raw_columns=initial_parse.raw_columns,
        )
        record = await _analyze_and_save(
            db,
            record=record,
            user=user,
            content=content,
            filename=record.source_file_name,
            workbook_analysis=workbook_analysis,
            workbook_signature=signature,
            mapping=body.mapping_json,
            sheet_name=body.sheet_name,
        )
        await db.commit()
        return _response(record)
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail="Import session not found") from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{session_id}", response_model=ImportSessionResponse)
async def read_import_session(session_id: UUID, db: DbSession, user: Methodologist):
    try:
        record = await get_import_session(db, tenant_id=user.tenant_id, session_id=session_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Import session not found") from exc
    return _response(record)


@router.post("/{session_id}/corrections", response_model=ImportSessionResponse)
async def correct_session_proposal(
    session_id: UUID,
    body: CorrectImportProposalRequest,
    db: DbSession,
    user: Methodologist,
):
    try:
        record = await get_import_session(
            db,
            tenant_id=user.tenant_id,
            session_id=session_id,
            for_update=True,
        )
        if record.state not in {
            ImportSessionState.NEEDS_REVIEW.value,
            ImportSessionState.NEEDS_CORRECTION.value,
            ImportSessionState.READY_FOR_APPROVAL.value,
        }:
            raise ValueError("session proposal is not editable")
        if record.proposal_json is None or record.proposal_revision != body.revision:
            raise ValueError("proposal revision is stale")
        current = ImportSessionProposal.model_validate(record.proposal_json)
        corrected = apply_proposal_corrections(current, body.corrections)
        if corrected.source_file_sha256 != record.source_file_sha256 or corrected.mode.value != record.mode:
            raise ValueError("corrected proposal source contract mismatch")
        record = await save_proposal(
            db,
            tenant_id=user.tenant_id,
            session_id=session_id,
            actor_id=user.id,
            proposal=corrected,
        )
        await db.commit()
        return _response(record)
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail="Import session not found") from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{session_id}/approve", response_model=ImportSessionResponse)
async def approve_session(
    session_id: UUID,
    body: ApproveImportSessionRequest,
    db: DbSession,
    user: Methodologist,
):
    try:
        record = await approve_import_session(
            db,
            tenant_id=user.tenant_id,
            session_id=session_id,
            actor_id=user.id,
            revision=body.revision,
            full_reconciliation_confirmation=body.full_reconciliation_confirmation,
        )
        await ensure_approved_mapping_profile(db, record=record, actor_id=user.id)
        await db.commit()
        return _response(record)
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail="Import session not found") from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{session_id}/commit", response_model=ImportSessionResponse)
async def commit_session(
    session_id: UUID,
    body: CommitImportSessionRequest,
    db: DbSession,
    user: Methodologist,
):
    # Keep immutable primitives across commits. SQLAlchemy expires ORM objects
    # after commit, and reading ``user.tenant_id`` or ``record.*`` then would
    # trigger forbidden implicit async IO (MissingGreenlet).
    tenant_id = UUID(str(user.tenant_id))
    actor_id = UUID(str(user.id))
    try:
        record = await commit_approved_import_session(
            db,
            tenant_id=tenant_id,
            session_id=session_id,
            actor_id=actor_id,
            revision=body.revision,
        )
        await db.commit()
        await _restore_tenant_context(db, tenant_id)
        try:
            record = await run_committed_rule_recompute(
                db,
                tenant_id=tenant_id,
                session_id=session_id,
                actor_id=actor_id,
            )
        except Exception as exc:  # noqa: BLE001 - import is already committed
            await db.rollback()
            await _restore_tenant_context(db, tenant_id)
            record = await mark_rule_recompute_failed(
                db,
                tenant_id=tenant_id,
                session_id=session_id,
                actor_id=actor_id,
                error_code=type(exc).__name__,
            )
        source_key = record.source_object_key
        await db.commit()
        if source_key:
            try:
                get_storage().delete_bytes(source_key)
                await _restore_tenant_context(db, tenant_id)
                record = await get_import_session(
                    db,
                    tenant_id=tenant_id,
                    session_id=session_id,
                    for_update=True,
                )
                record.source_object_key = None
                await db.commit()
            except Exception:  # noqa: BLE001 - committed import remains successful
                await db.rollback()
        await _restore_tenant_context(db, tenant_id)
        record = await get_import_session(
            db,
            tenant_id=tenant_id,
            session_id=session_id,
        )
        return _response(record)
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail="Import session not found") from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
