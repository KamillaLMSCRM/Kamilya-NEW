"""Superadmin-only operational observability and synthetic cleanup.

The endpoint in this module intentionally returns aggregate operational data.
It never returns tenant names, emails, document names, job messages, or other
tenant-owned payloads. Cleanup is deliberately narrower than the existing
tenant deletion service: a tenant must be explicitly marked as a demo tenant,
match one of the fixed synthetic prefixes, and be older than the safety floor.
"""
from __future__ import annotations

import logging
import os
import platform
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.config import get_settings
from app.core.db import engine, get_db
from app.models.ai_job import AIJob
from app.models.document import Document
from app.models.tenants import Tenant
from app.models.users import User
from app.modules.admin.superadmin.service import SuperadminService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/operations", tags=["superadmin-operations"])

PROCESS_STARTED_AT = datetime.now(UTC).replace(microsecond=0)
PROCESS_STARTED_MONOTONIC = time.monotonic()

# This is intentionally code-owned, not caller-controlled. A caller cannot
# expand the deletion scope by supplying a broader prefix in the request.
ALLOWED_SYNTHETIC_SLUG_PREFIXES = (
    "synthetic-",
    "test-",
    "qa-",
    "smoke-",
    "e2e-",
    "loadtest-",
)
MIN_CLEANUP_AGE_HOURS = 24
MAX_CLEANUP_AGE_HOURS = 24 * 365 * 5
CLEANUP_CONFIRM_TOKEN = "CLEANUP_SYNTHETIC_TENANTS"
MAX_CLEANUP_CANDIDATES = 100


class AIJobOperationsSummary(BaseModel):
    queued_count: int
    running_count: int
    failed_count: int
    oldest_queued_age_seconds: int | None = None
    oldest_running_age_seconds: int | None = None


class DocumentOperationsSummary(BaseModel):
    indexing_count: int
    failed_index_count: int
    failed_embedding_count: int
    cleanup_pending_count: int
    cleanup_failed_count: int
    oldest_indexing_age_seconds: int | None = None
    oldest_cleanup_pending_age_seconds: int | None = None


class DatabasePoolSummary(BaseModel):
    pool_class: str
    configured_pool_size: int | None = None
    configured_max_overflow: int | None = None
    configured_pool_timeout_seconds: int | None = None
    configured_pool_recycle_seconds: int | None = None
    checked_in: int | None = None
    checked_out: int | None = None
    overflow: int | None = None
    capacity: int | None = None


class ProcessRuntimeSummary(BaseModel):
    process_id: int
    started_at: datetime
    uptime_seconds: int
    python_version: str


class OperationsSummary(BaseModel):
    generated_at: datetime
    ai_jobs: AIJobOperationsSummary
    documents: DocumentOperationsSummary
    database: DatabasePoolSummary
    process: ProcessRuntimeSummary


class SyntheticCleanupRequest(BaseModel):
    """Safe cleanup controls.

    Dry-run is the default. A destructive request must set ``confirm`` and
    provide the exact fixed token. The age floor cannot be lowered by a
    caller.
    """

    dry_run: bool = True
    min_age_hours: int = Field(
        default=MIN_CLEANUP_AGE_HOURS,
        ge=MIN_CLEANUP_AGE_HOURS,
        le=MAX_CLEANUP_AGE_HOURS,
    )
    confirm: bool = False
    confirm_token: str | None = Field(default=None, max_length=64)


CleanupAction = Literal["would_delete", "deleted", "skipped", "failed"]


class SyntheticCleanupResult(BaseModel):
    tenant_id: uuid.UUID
    slug: str
    created_at: datetime
    age_hours: float
    action: CleanupAction
    reason: str | None = None


class SyntheticCleanupResponse(BaseModel):
    dry_run: bool
    min_age_hours: int
    allowed_slug_prefixes: list[str]
    matched_count: int
    deleted_count: int
    skipped_count: int
    failed_count: int
    truncated: bool
    results: list[SyntheticCleanupResult]


def _age_seconds(when: datetime | None, now: datetime) -> int | None:
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0, int((now - when).total_seconds()))


def _is_allowed_synthetic_tenant(tenant: Tenant) -> bool:
    """Return true only for explicitly demo-marked, fixed-prefix tenants."""

    return bool(tenant.is_demo) and any(
        tenant.slug.startswith(prefix) for prefix in ALLOWED_SYNTHETIC_SLUG_PREFIXES
    )


def _pool_summary() -> DatabasePoolSummary:
    settings = get_settings()
    pool = engine.sync_engine.pool
    pool_class = type(pool).__name__

    # NullPool, used by pytest and some one-shot jobs, has no pool counters.
    def counter(name: str) -> int | None:
        getter = getattr(pool, name, None)
        if not callable(getter):
            return None
        try:
            return int(getter())
        except Exception:
            return None
    configured_size = getattr(settings, "DB_POOL_SIZE", None)
    configured_overflow = getattr(settings, "DB_MAX_OVERFLOW", None)
    capacity = (
        int(configured_size) + int(configured_overflow)
        if configured_size is not None and configured_overflow is not None
        else None
    )
    return DatabasePoolSummary(
        pool_class=pool_class,
        configured_pool_size=configured_size,
        configured_max_overflow=configured_overflow,
        configured_pool_timeout_seconds=getattr(settings, "DB_POOL_TIMEOUT", None),
        configured_pool_recycle_seconds=getattr(settings, "DB_POOL_RECYCLE_SECONDS", None),
        checked_in=counter("checkedin"),
        checked_out=counter("checkedout"),
        overflow=counter("overflow"),
        capacity=capacity,
    )


class SuperadminOperationsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def summary(self) -> OperationsSummary:
        now = datetime.now(UTC)

        queued_count, oldest_queued = (
            await self.db.execute(
                select(func.count(AIJob.id), func.min(AIJob.created_at)).where(
                    AIJob.status == "pending"
                )
            )
        ).one()
        running_count, oldest_running = (
            await self.db.execute(
                select(func.count(AIJob.id), func.min(AIJob.created_at)).where(
                    AIJob.status == "running"
                )
            )
        ).one()
        failed_count = (
            await self.db.execute(
                select(func.count(AIJob.id)).where(
                    AIJob.status.in_(("failed", "error"))
                )
            )
        ).scalar_one()

        indexing_count, oldest_indexing = (
            await self.db.execute(
                select(func.count(Document.id), func.min(Document.created_at)).where(
                    Document.index_status == "processing"
                )
            )
        ).one()
        failed_index_count = (
            await self.db.execute(
                select(func.count(Document.id)).where(Document.index_status == "failed")
            )
        ).scalar_one()
        failed_embedding_count = (
            await self.db.execute(
                select(func.count(Document.id)).where(
                    Document.embedding_status == "failed"
                )
            )
        ).scalar_one()
        cleanup_pending_count, oldest_cleanup_pending = (
            await self.db.execute(
                select(func.count(Document.id), func.min(Document.created_at)).where(
                    Document.lifecycle_status == "deletion_pending"
                )
            )
        ).one()
        cleanup_failed_count = (
            await self.db.execute(
                select(func.count(Document.id)).where(
                    Document.lifecycle_status == "delete_failed"
                )
            )
        ).scalar_one()

        return OperationsSummary(
            generated_at=now,
            ai_jobs=AIJobOperationsSummary(
                queued_count=int(queued_count or 0),
                running_count=int(running_count or 0),
                failed_count=int(failed_count or 0),
                oldest_queued_age_seconds=_age_seconds(oldest_queued, now),
                oldest_running_age_seconds=_age_seconds(oldest_running, now),
            ),
            documents=DocumentOperationsSummary(
                indexing_count=int(indexing_count or 0),
                failed_index_count=int(failed_index_count or 0),
                failed_embedding_count=int(failed_embedding_count or 0),
                cleanup_pending_count=int(cleanup_pending_count or 0),
                cleanup_failed_count=int(cleanup_failed_count or 0),
                oldest_indexing_age_seconds=_age_seconds(oldest_indexing, now),
                oldest_cleanup_pending_age_seconds=_age_seconds(
                    oldest_cleanup_pending, now
                ),
            ),
            database=_pool_summary(),
            process=ProcessRuntimeSummary(
                process_id=os.getpid(),
                started_at=PROCESS_STARTED_AT,
                uptime_seconds=max(0, int(time.monotonic() - PROCESS_STARTED_MONOTONIC)),
                python_version=platform.python_version(),
            ),
        )

    async def cleanup_synthetic_tenants(
        self,
        *,
        dry_run: bool,
        min_age_hours: int,
        confirm: bool = False,
        confirm_token: str | None = None,
    ) -> SyntheticCleanupResponse:
        if min_age_hours < MIN_CLEANUP_AGE_HOURS:
            raise ValueError(
                f"min_age_hours must be at least {MIN_CLEANUP_AGE_HOURS}"
            )
        if not dry_run and (
            not confirm or confirm_token != CLEANUP_CONFIRM_TOKEN
        ):
            raise ValueError(
                "Destructive cleanup requires confirm=true and the exact "
                f"confirm_token={CLEANUP_CONFIRM_TOKEN}"
            )

        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=min_age_hours)
        prefix_filter = or_(
            *(Tenant.slug.like(f"{prefix}%") for prefix in ALLOWED_SYNTHETIC_SLUG_PREFIXES)
        )
        candidates = list(
            (
                await self.db.execute(
                    select(Tenant)
                    .where(
                        Tenant.is_demo.is_(True),
                        Tenant.created_at <= cutoff,
                        prefix_filter,
                    )
                    .order_by(Tenant.created_at.asc())
                    .limit(MAX_CLEANUP_CANDIDATES + 1)
                )
            ).scalars().all()
        )
        truncated = len(candidates) > MAX_CLEANUP_CANDIDATES
        candidates = candidates[:MAX_CLEANUP_CANDIDATES]
        results: list[SyntheticCleanupResult] = []
        deleted_count = skipped_count = failed_count = 0
        deletion_service = SuperadminService(self.db)

        for candidate in candidates:
            created_at = candidate.created_at
            age_hours = round(
                max(0, (now - (created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC))).total_seconds())
                / 3600,
                2,
            )
            # Re-read the row before every destructive operation. A slug or
            # demo flag changed after the initial query must fail closed.
            current = await self.db.get(Tenant, candidate.id)
            if current is None or not _is_allowed_synthetic_tenant(current):
                skipped_count += 1
                results.append(
                    SyntheticCleanupResult(
                        tenant_id=candidate.id,
                        slug=candidate.slug,
                        created_at=created_at,
                        age_hours=age_hours,
                        action="skipped",
                        reason="tenant no longer matches synthetic cleanup guard",
                    )
                )
                continue

            if dry_run:
                results.append(
                    SyntheticCleanupResult(
                        tenant_id=current.id,
                        slug=current.slug,
                        created_at=current.created_at,
                        age_hours=age_hours,
                        action="would_delete",
                    )
                )
                continue

            try:
                snapshot = await deletion_service.delete_tenant(current.id)
            except Exception as exc:
                await self.db.rollback()
                failed_count += 1
                logger.exception(
                    "superadmin.synthetic_cleanup.failed tenant_id=%s slug=%s",
                    current.id,
                    current.slug,
                )
                results.append(
                    SyntheticCleanupResult(
                        tenant_id=current.id,
                        slug=current.slug,
                        created_at=current.created_at,
                        age_hours=age_hours,
                        action="failed",
                        reason=f"{type(exc).__name__}: cleanup failed",
                    )
                )
            else:
                deleted_count += 1
                logger.warning(
                    "superadmin.synthetic_cleanup.deleted tenant_id=%s slug=%s",
                    snapshot.id,
                    snapshot.slug,
                )
                results.append(
                    SyntheticCleanupResult(
                        tenant_id=snapshot.id,
                        slug=snapshot.slug,
                        created_at=snapshot.created_at,
                        age_hours=age_hours,
                        action="deleted",
                    )
                )

        return SyntheticCleanupResponse(
            dry_run=dry_run,
            min_age_hours=min_age_hours,
            allowed_slug_prefixes=list(ALLOWED_SYNTHETIC_SLUG_PREFIXES),
            matched_count=len(candidates),
            deleted_count=deleted_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            truncated=truncated,
            results=results,
        )


@router.get("/summary", response_model=OperationsSummary)
async def get_operations_summary(
    user: User = Depends(require_role("superadmin")),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> OperationsSummary:
    """Return aggregate operational health indicators for platform operators."""

    return await SuperadminOperationsService(db).summary()


@router.post(
    "/cleanup-synthetic",
    response_model=SyntheticCleanupResponse,
    status_code=status.HTTP_200_OK,
)
async def cleanup_synthetic_tenants(
    payload: SyntheticCleanupRequest | None = None,
    user: User = Depends(require_role("superadmin")),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> SyntheticCleanupResponse:
    """Preview or delete only old, demo-marked synthetic tenants."""

    payload = payload or SyntheticCleanupRequest()
    try:
        return await SuperadminOperationsService(db).cleanup_synthetic_tenants(
            dry_run=payload.dry_run,
            min_age_hours=payload.min_age_hours,
            confirm=payload.confirm,
            confirm_token=payload.confirm_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
