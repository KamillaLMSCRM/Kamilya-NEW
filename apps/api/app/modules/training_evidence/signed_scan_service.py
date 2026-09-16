"""Append-only returned hand-signed scans for tenant training evidence."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from pathlib import PurePath
from typing import cast
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import get_storage
from app.models.enrollment import Enrollment
from app.modules.training_evidence.models import (
    TrainingEvidenceEvent,
    TrainingEvidenceSignedScan,
    TrainingEvidenceSignedScanReview,
)

logger = logging.getLogger(__name__)

MAX_SIGNED_SCAN_BYTES = 10 * 1024 * 1024
_ALLOWED_CONTENT_TYPES = {"application/pdf", "image/jpeg", "image/png"}
_UNSAFE_FILENAME_CHARS = re.compile(r'[\x00-\x1f\x7f"\\]')


def _safe_filename(value: str | None) -> str:
    name = PurePath(value or "signed-copy").name
    # The filename is metadata only (the object key is UUID-based), but keep it
    # safe for Content-Disposition and audit exports as well.
    name = _UNSAFE_FILENAME_CHARS.sub("", name).strip()
    return (name or "signed-copy")[:255]


def _valid_magic_bytes(content: bytes, content_type: str) -> bool:
    if content_type == "application/pdf":
        return content.startswith(b"%PDF-")
    if content_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    return False


async def _eligible_event(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    event_id: UUID,
) -> TrainingEvidenceEvent:
    event = await db.scalar(
        select(TrainingEvidenceEvent).where(
            TrainingEvidenceEvent.id == event_id,
            TrainingEvidenceEvent.tenant_id == tenant_id,
        )
    )
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence event not found")
    if (
        event.record_type != "original"
        or event.procedure_type != "training"
        or event.enrollment_id is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A signed copy can be attached only to an original enrolled training event",
        )
    enrollment = await db.scalar(
        select(Enrollment).where(
            Enrollment.id == event.enrollment_id,
            Enrollment.tenant_id == tenant_id,
            Enrollment.user_id == event.user_id,
        )
    )
    if enrollment is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Evidence enrollment is unavailable")
    return event


def _storage_key(tenant_id: UUID, event_id: UUID, scan_id: UUID, content_type: str) -> str:
    extension = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}[content_type]
    return f"training-evidence/{tenant_id}/{event_id}/signed-scans/{scan_id}.{extension}"


async def append_signed_scan(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    uploader_user_id: UUID,
    event_id: UUID,
    file: UploadFile,
) -> TrainingEvidenceSignedScan:
    content_type = (file.content_type or "").lower().strip()
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Signed copy must be a PDF, JPEG or PNG"
        )
    content = await file.read(MAX_SIGNED_SCAN_BYTES + 1)
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Signed copy is empty")
    if len(content) > MAX_SIGNED_SCAN_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Signed copy exceeds 10 MB")
    if not _valid_magic_bytes(content, content_type):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Signed copy content does not match its declared type",
        )

    event = await _eligible_event(db, tenant_id=tenant_id, event_id=event_id)
    scan_id = uuid4()
    stored_key = _storage_key(tenant_id, cast(UUID, event.id), scan_id, content_type)
    scan = TrainingEvidenceSignedScan(
        id=scan_id,
        tenant_id=tenant_id,
        event_id=event.id,
        enrollment_id=event.enrollment_id,
        user_id=event.user_id,
        status="uploaded_pending_review",
        original_filename=_safe_filename(file.filename),
        content_type=content_type,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        storage_key=stored_key,
        uploaded_by_user_id=uploader_user_id,
        uploaded_at=datetime.now(UTC),
    )
    db.add(scan)
    blob_persisted = False
    try:
        # Reserve the immutable ledger row before persisting object storage so
        # a database constraint failure cannot leave a blob behind.
        await db.flush()
        get_storage().put_bytes(stored_key, content, content_type=content_type)
        blob_persisted = True
        await db.commit()
        return scan
    except Exception:
        await db.rollback()
        if blob_persisted:
            try:
                get_storage().delete_bytes(stored_key)
            except Exception:
                logger.exception("Could not remove orphaned signed scan %s", scan_id)
        raise


async def list_signed_scans(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    event_id: UUID,
) -> tuple[TrainingEvidenceEvent, list[TrainingEvidenceSignedScan]]:
    event = await _eligible_event(db, tenant_id=tenant_id, event_id=event_id)
    scans = list(
        (
            await db.scalars(
                select(TrainingEvidenceSignedScan)
                .where(
                    TrainingEvidenceSignedScan.tenant_id == tenant_id,
                    TrainingEvidenceSignedScan.event_id == event.id,
                )
                .order_by(TrainingEvidenceSignedScan.uploaded_at, TrainingEvidenceSignedScan.id)
            )
        ).all()
    )
    return event, scans


def derive_signed_copy_status(
    scans: list[TrainingEvidenceSignedScan], reviews: list[TrainingEvidenceSignedScanReview]
) -> str:
    """Derive lifecycle state without updating an immutable scan row."""
    if not scans:
        return "awaiting_return"
    latest_by_scan: dict[UUID, TrainingEvidenceSignedScanReview] = {}
    for review in reviews:
        latest_by_scan[cast(UUID, review.signed_scan_id)] = review
    latest = max(
        scans,
        key=lambda scan: (
            getattr(scan, "uploaded_at", None) or datetime.min.replace(tzinfo=UTC),
            scan.id,
        ),
    )
    decision = latest_by_scan.get(cast(UUID, latest.id))
    if decision is None:
        return "uploaded_pending_review"
    return "accepted" if decision.action == "accept" else "replacement_requested"


async def list_signed_scan_reviews(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    event_id: UUID,
) -> list[TrainingEvidenceSignedScanReview]:
    rows = await db.scalars(
        select(TrainingEvidenceSignedScanReview)
        .where(
            TrainingEvidenceSignedScanReview.tenant_id == tenant_id,
            TrainingEvidenceSignedScanReview.event_id == event_id,
        )
        .order_by(TrainingEvidenceSignedScanReview.reviewed_at, TrainingEvidenceSignedScanReview.id)
    )
    return list(rows.all())


async def review_signed_scan(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    reviewer_user_id: UUID,
    event_id: UUID,
    scan_id: UUID,
    action: str,
    reason: str | None,
) -> TrainingEvidenceSignedScanReview:
    event = await _eligible_event(db, tenant_id=tenant_id, event_id=event_id)
    scan = await db.scalar(
        select(TrainingEvidenceSignedScan).where(
            TrainingEvidenceSignedScan.id == scan_id,
            TrainingEvidenceSignedScan.tenant_id == tenant_id,
            TrainingEvidenceSignedScan.event_id == event.id,
        )
    )
    if scan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signed copy not found")
    if action not in {"accept", "request_replacement"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported review action")
    if action == "request_replacement" and not reason:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Replacement reason is required")
    if action == "accept" and reason is not None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Acceptance cannot include a reason")
    review = TrainingEvidenceSignedScanReview(
        id=uuid4(),
        tenant_id=tenant_id,
        event_id=event.id,
        signed_scan_id=scan.id,
        action=action,
        reason=reason,
        reviewed_by_user_id=reviewer_user_id,
        reviewed_at=datetime.now(UTC),
    )
    db.add(review)
    await db.commit()
    return review
