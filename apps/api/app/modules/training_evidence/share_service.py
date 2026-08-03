"""Restricted, immutable external links for generated training-evidence packages."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rate_limit import RateLimiter
from app.modules.evidence_export import (
    build_group_evidence_package,
    build_individual_evidence_package,
    render_group_protocol_pdf,
    render_individual_act_pdf,
)
from app.modules.training_evidence.export_service import (
    build_group_evidence_input,
    build_individual_evidence_input,
)
from app.modules.training_evidence.models import TrainingEvidenceShare, TrainingEvidenceShareAccessLog

ShareFormat = Literal["zip", "pdf"]
PUBLIC_SHARE_RATE_LIMIT = 20
PUBLIC_SHARE_RATE_WINDOW_SECONDS = 60
MAX_SHARE_LIFETIME = timedelta(days=31)
MAX_SHARE_PACKAGE_BYTES = 25 * 1024 * 1024
_public_share_rate_limiter: RateLimiter | None = None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _ip_hash(request: Request) -> str:
    ip = request.client.host if request.client else "unknown"
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:32]


async def enforce_public_share_rate_limit(request: Request) -> None:
    """Apply the project's Redis/Valkey limiter to unauthenticated share reads."""

    global _public_share_rate_limiter
    if _public_share_rate_limiter is None:
        _public_share_rate_limiter = RateLimiter(get_settings().REDIS_URL)

    allowed, info = await _public_share_rate_limiter.check_rate_limit(
        f"public_training_evidence_share:ip:{_ip_hash(request)}",
        PUBLIC_SHARE_RATE_LIMIT,
        PUBLIC_SHARE_RATE_WINDOW_SECONDS,
    )
    if info.get("unavailable"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Evidence share service temporarily unavailable",
            headers={"Retry-After": "5"},
        )
    if not allowed:
        retry_after = max(1, int(info.get("reset", 0)) - int(datetime.now(UTC).timestamp()))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Share rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )


def _package_metadata(package_format: ShareFormat) -> tuple[str, str]:
    if package_format == "pdf":
        return "application/pdf", "kamilya-training-evidence-package.pdf"
    return "application/zip", "kamilya-training-evidence-package.zip"


def _ensure_unique_event_ids(event_ids: list[UUID]) -> None:
    if len(set(event_ids)) != len(event_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="event_ids must not contain duplicates",
        )


def _normalize_expiry(expires_at: datetime) -> datetime:
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="expires_at must include a timezone",
        )
    normalized = expires_at.astimezone(UTC)
    now = datetime.now(UTC)
    if normalized <= now:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="expires_at must be in the future",
        )
    if normalized > now + MAX_SHARE_LIFETIME:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="expires_at must be within 31 days",
        )
    return normalized


async def create_share(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    event_ids: list[UUID],
    package_format: ShareFormat,
    expires_at: datetime,
    max_downloads: int,
) -> tuple[TrainingEvidenceShare, str]:
    """Build once, then persist the exact bytes served by the public endpoint."""

    _ensure_unique_event_ids(event_ids)
    expires_at = _normalize_expiry(expires_at)
    if not 1 <= max_downloads <= 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="max_downloads must be between 1 and 100",
        )

    if len(event_ids) == 1:
        evidence = await build_individual_evidence_input(db, tenant_id, event_ids[0])
        if package_format == "pdf":
            package_bytes = render_individual_act_pdf(evidence)
        else:
            package_bytes = build_individual_evidence_package(evidence).zip_bytes
    else:
        evidence = await build_group_evidence_input(db, tenant_id, event_ids)
        if package_format == "pdf":
            package_bytes = render_group_protocol_pdf(evidence)
        else:
            package_bytes = build_group_evidence_package(evidence).zip_bytes

    if len(package_bytes) > MAX_SHARE_PACKAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Evidence package is too large for an external share",
        )

    token = secrets.token_urlsafe(32)
    content_type, filename = _package_metadata(package_format)
    share = TrainingEvidenceShare(
        tenant_id=tenant_id,
        token_sha256=_token_hash(token),
        package_format=package_format,
        content_type=content_type,
        public_filename=filename,
        package_bytes=package_bytes,
        package_sha256=hashlib.sha256(package_bytes).hexdigest(),
        source_event_ids=[str(event_id) for event_id in event_ids],
        expires_at=expires_at,
        max_downloads=max_downloads,
        created_by_user_id=user_id,
    )
    db.add(share)
    await db.flush()
    return share, token


async def set_public_tenant_context(db: AsyncSession, tenant_id: UUID) -> bool:
    """Set transaction-local RLS context before any tenant-scoped lookup."""

    await db.execute(text("SELECT set_current_tenant(:tenant_id)"), {"tenant_id": str(tenant_id)})
    return True


def package_integrity_valid(share: TrainingEvidenceShare) -> bool:
    actual_sha256 = hashlib.sha256(bytes(share.package_bytes)).hexdigest()
    return hmac.compare_digest(actual_sha256, share.package_sha256)


async def record_share_access(
    db: AsyncSession,
    share: TrainingEvidenceShare,
    *,
    outcome: str,
    download_count_after: int | None,
) -> None:
    db.add(
        TrainingEvidenceShareAccessLog(
            tenant_id=share.tenant_id,
            share_id=share.id,
            outcome=outcome,
            download_count_after=download_count_after,
        )
    )
    await db.flush()


async def reject_known_share(
    db: AsyncSession,
    share: TrainingEvidenceShare,
    *,
    outcome: str,
) -> None:
    """Persist a non-PII rejection event before returning the same generic 404."""

    await record_share_access(db, share, outcome=outcome, download_count_after=share.download_count)
    await db.commit()
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share unavailable")


__all__ = [
    "PUBLIC_SHARE_RATE_LIMIT",
    "PUBLIC_SHARE_RATE_WINDOW_SECONDS",
    "MAX_SHARE_LIFETIME",
    "MAX_SHARE_PACKAGE_BYTES",
    "_public_share_rate_limiter",
    "create_share",
    "enforce_public_share_rate_limit",
    "package_integrity_valid",
    "record_share_access",
    "reject_known_share",
    "set_public_tenant_context",
]
