"""Methodologist-only streaming endpoints for training-evidence packages."""

# FastAPI dependency calls in route defaults follow the project convention.
# ruff: noqa: B008

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
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
    build_learner_individual_evidence_input,
)
from app.modules.training_evidence.models import TrainingEvidenceShare
from app.modules.training_evidence.share_schemas import (
    EvidenceShareCreateRequest,
    EvidenceShareResponse,
    EvidenceShareRevokeResponse,
)
from app.modules.training_evidence.share_service import (
    _token_hash,
    create_share,
    enforce_public_share_rate_limit,
    package_integrity_valid,
    record_share_access,
    reject_known_share,
    set_public_tenant_context,
)

router = APIRouter(
    prefix="/training-evidence",
    tags=["training-evidence-export"],
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


def _share_url(request: Request, tenant_id: UUID, token: str) -> str:
    return str(
        request.url_for(
            "download_public_training_evidence_share",
            tenant_id=str(tenant_id),
            token=token,
        )
    )


@router.get("/events/mine/{event_id}/export")
async def export_my_training_evidence(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_user: User = Depends(require_tenant_user()),
    user: User = Depends(require_role("student")),
):
    """Download only the authenticated learner's own individual result PDF."""

    evidence = await build_learner_individual_evidence_input(
        db,
        tenant_user.tenant_id,
        user.id,
        event_id,
    )
    return _download(
        render_individual_act_pdf(evidence),
        media_type="application/pdf",
        filename=_safe_filename("my-training-result", event_id, extension="pdf"),
    )


@router.get("/events/{event_id}/export")
async def export_individual_training_evidence(
    event_id: UUID,
    format: ExportFormat = Query(default="zip"),
    db: AsyncSession = Depends(get_db),
    tenant_user: User = Depends(require_tenant_user()),
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
    tenant_user: User = Depends(require_tenant_user()),
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


def _share_response(share: TrainingEvidenceShare, *, url: str | None = None) -> EvidenceShareResponse:
    return EvidenceShareResponse(
        id=share.id,
        format=share.package_format,
        package_sha256=share.package_sha256,
        package_size_bytes=len(share.package_bytes),
        source_event_count=len(share.source_event_ids or []),
        expires_at=share.expires_at,
        max_downloads=share.max_downloads,
        download_count=share.download_count,
        revoked_at=share.revoked_at,
        created_at=share.created_at,
        url=url,
    )


@router.post("/shares", response_model=EvidenceShareResponse, status_code=status.HTTP_201_CREATED)
async def create_training_evidence_share(
    payload: EvidenceShareCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    tenant_user: User = Depends(require_tenant_user()),
    user: User = Depends(require_role("methodologist")),
):
    share, token = await create_share(
        db,
        tenant_id=tenant_user.tenant_id,
        user_id=user.id,
        event_ids=payload.event_ids,
        package_format=payload.format,
        expires_at=payload.expires_at,
        max_downloads=payload.max_downloads,
    )
    url = _share_url(request, tenant_user.tenant_id, token)
    return _share_response(share, url=url)


@router.get("/shares", response_model=list[EvidenceShareResponse])
async def list_training_evidence_shares(
    db: AsyncSession = Depends(get_db),
    tenant_user: User = Depends(require_tenant_user()),
    user: User = Depends(require_role("methodologist")),
):
    shares = list(
        (
            await db.scalars(
                select(TrainingEvidenceShare)
                .where(TrainingEvidenceShare.tenant_id == tenant_user.tenant_id)
                .order_by(TrainingEvidenceShare.created_at.desc())
                .limit(100)
            )
        ).all()
    )
    return [_share_response(share) for share in shares]


@router.post("/shares/{share_id}/revoke", response_model=EvidenceShareRevokeResponse)
async def revoke_training_evidence_share(
    share_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant_user: User = Depends(require_tenant_user()),
    user: User = Depends(require_role("methodologist")),
):
    share = await db.scalar(
        select(TrainingEvidenceShare)
        .where(
            TrainingEvidenceShare.id == share_id,
            TrainingEvidenceShare.tenant_id == tenant_user.tenant_id,
        )
        .with_for_update()
    )
    if share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")
    if share.revoked_at is None:
        share.revoked_at = datetime.now(UTC)
        await db.flush()
    return EvidenceShareRevokeResponse(id=share.id, revoked_at=share.revoked_at)


@router.get(
    "/shares/{tenant_id}/{token}",
    response_class=StreamingResponse,
    dependencies=[Depends(enforce_public_share_rate_limit)],
)
async def download_public_training_evidence_share(
    tenant_id: UUID,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Serve one stored package without exposing share metadata or neighboring rows."""

    if not await set_public_tenant_context(db, tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share unavailable")

    share = await db.scalar(
        select(TrainingEvidenceShare)
        .where(
            TrainingEvidenceShare.tenant_id == tenant_id,
            TrainingEvidenceShare.token_sha256 == _token_hash(token),
        )
        .with_for_update()
    )
    if share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share unavailable")

    now = datetime.now(UTC)
    if share.revoked_at is not None:
        await reject_known_share(db, share, outcome="rejected_revoked")
    if now >= share.expires_at:
        await reject_known_share(db, share, outcome="rejected_expired")
    if share.download_count >= share.max_downloads:
        await reject_known_share(db, share, outcome="rejected_exhausted")
    if not package_integrity_valid(share):
        await reject_known_share(db, share, outcome="rejected_integrity")

    share.download_count += 1
    await record_share_access(
        db,
        share,
        outcome="downloaded",
        download_count_after=share.download_count,
    )
    return _download(
        share.package_bytes,
        media_type=share.content_type,
        filename=share.public_filename,
    )


__all__ = ["router"]
