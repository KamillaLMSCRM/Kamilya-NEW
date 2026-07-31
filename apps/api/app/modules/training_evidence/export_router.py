"""Methodologist-only streaming endpoints for training-evidence packages."""

# FastAPI dependency calls in route defaults follow the project convention.
# ruff: noqa: B008

from __future__ import annotations

import re
import unicodedata
from io import BytesIO
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role, require_tenant_user
from app.core.db import get_db
from app.models.users import User
from app.modules.evidence_export import (
    build_group_evidence_package,
    build_individual_evidence_package,
    render_group_protocol_pdf,
    render_individual_act_pdf,
)
from app.modules.training_evidence.export_schemas import (
    ExportFormat,
    GroupEvidenceExportRequest,
)
from app.modules.training_evidence.export_service import (
    build_group_evidence_input,
    build_individual_evidence_input,
)

router = APIRouter(
    prefix="/training-evidence",
    tags=["training-evidence-export"],
    dependencies=[Depends(require_tenant_user())],
)


def _safe_filename(*parts: object, extension: str) -> str:
    text = "-".join(str(part) for part in parts if part is not None)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-._") or "evidence"
    return f"kamilya-{text[:120]}.{extension}"


def _download(content: bytes, *, media_type: str, filename: str) -> StreamingResponse:
    return StreamingResponse(
        iter((BytesIO(content).getvalue(),)),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/events/{event_id}/export")
async def export_individual_training_evidence(
    event_id: UUID,
    format: ExportFormat = Query(default="zip"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    evidence = await build_individual_evidence_input(db, user.tenant_id, event_id)
    if format == "pdf":
        return _download(
            render_individual_act_pdf(evidence),
            media_type="application/pdf",
            filename=_safe_filename("individual", event_id, extension="pdf"),
        )
    package = build_individual_evidence_package(evidence)
    return _download(
        package.zip_bytes,
        media_type="application/zip",
        filename=_safe_filename("individual", event_id, extension="zip"),
    )


@router.post("/exports/group")
async def export_group_training_evidence(
    payload: GroupEvidenceExportRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    evidence = await build_group_evidence_input(db, user.tenant_id, payload.event_ids)
    if payload.format == "pdf":
        return _download(
            render_group_protocol_pdf(evidence),
            media_type="application/pdf",
            filename=_safe_filename("group", evidence.procedure.type, extension="pdf"),
        )
    package = build_group_evidence_package(evidence)
    return _download(
        package.zip_bytes,
        media_type="application/zip",
        filename=_safe_filename("group", evidence.procedure.type, extension="zip"),
    )


__all__ = ["router"]
