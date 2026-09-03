"""Superadmin-only operational observability and synthetic cleanup.

The endpoint in this module intentionally returns aggregate operational data.
It never returns tenant names, emails, document names, job messages, or other
tenant-owned payloads. Cleanup is deliberately narrower than the existing
tenant deletion service: a tenant must be explicitly marked as a demo tenant,
match one of the fixed synthetic prefixes, and be older than the safety floor.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import psutil
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.celery_app import celery_app
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
CELERY_INSPECT_TIMEOUT_SECONDS = 0.75
CELERY_INSPECT_OUTER_MARGIN_SECONDS = 0.25
REQUIRED_CELERY_TASKS = (
    "ai.generate_course",
    "ai.ingest_document",
    "ai.regenerate_lesson",
    "ai.regenerate_module",
    "documents.cleanup",
    "documents.hash_backfill",
    "documents.reindex",
    "positions.apply_course_rules",
    "users.deliver_invitation",
    "enrollments.deliver_assignment_notification",
    "enrollments.recover_assignment_notifications",
    "learning_cycles.materialize",
    "learning_cycles.recover_due",
    "candidate_assessments.enforce_retention",
    "staff_import.cleanup_expired_sources",
    "crm.deliver_lead_outbox",
    "crm.recover_lead_outbox",
)


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
    cpu_percent: float | None = None
    rss_memory_bytes: int | None = None


class HostRuntimeSummary(BaseModel):
    cpu_percent: float | None = None


class FilesystemRuntimeSummary(BaseModel):
    total_bytes: int | None = None
    free_bytes: int | None = None
    used_percent: float | None = None


class CeleryWorkerSummary(BaseModel):
    status: Literal["available", "unavailable"]
    reachable: bool
    worker_count: int = 0
    registered_required_tasks: list[str] = Field(default_factory=list)
    missing_required_tasks: list[str] = Field(default_factory=list)


class CRMLeadOutboxOperationsSummary(BaseModel):
    integration_status: Literal["enabled", "disabled"]
    held_count: int
    pending_count: int
    retry_count: int
    claimed_count: int
    dead_count: int
    delivered_count: int
    oldest_due_age_seconds: int | None = None


class OperationsSummary(BaseModel):
    generated_at: datetime
    ai_jobs: AIJobOperationsSummary
    documents: DocumentOperationsSummary
    database: DatabasePoolSummary
    process: ProcessRuntimeSummary
    host: HostRuntimeSummary
    filesystem: FilesystemRuntimeSummary
    celery: CeleryWorkerSummary
    crm_lead_outbox: CRMLeadOutboxOperationsSummary


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


STALE_AI_JOB_RECOVERY_CONFIRM_TOKEN = "RECOVER_STALE_AI_JOBS"
MIN_STALE_AI_JOB_AGE_HOURS = 1
DEFAULT_STALE_AI_JOB_AGE_HOURS = 24
MAX_STALE_AI_JOB_AGE_HOURS = 24 * 30
MAX_STALE_AI_JOB_RECOVERY = 100
STALE_AI_JOB_TERMINAL_STATUS = "cancelled"


class StaleAIJobRecoveryRequest(BaseModel):
    """Bounded recovery controls for jobs that stopped making progress."""

    dry_run: bool = True
    min_age_hours: int = Field(
        default=DEFAULT_STALE_AI_JOB_AGE_HOURS,
        ge=MIN_STALE_AI_JOB_AGE_HOURS,
        le=MAX_STALE_AI_JOB_AGE_HOURS,
    )
    confirm: bool = False
    confirm_token: str | None = Field(default=None, max_length=64)


class StaleAIJobRecoveryResponse(BaseModel):
    dry_run: bool
    min_age_hours: int
    terminal_status: Literal["cancelled"]
    eligible_count: int
    queued_count: int
    running_count: int
    recovered_count: int
    skipped_count: int
    truncated: bool
    oldest_age_seconds: int | None = None
    newest_age_seconds: int | None = None


CRM_OUTBOX_REQUEUE_CONFIRM_TOKEN = "REQUEUE_FAILED_CRM_LEADS"
DEFAULT_CRM_OUTBOX_REQUEUE_LIMIT = 20
MAX_CRM_OUTBOX_REQUEUE_LIMIT = 100


class CRMLeadOutboxRequeueRequest(BaseModel):
    dry_run: bool = True
    limit: int = Field(
        default=DEFAULT_CRM_OUTBOX_REQUEUE_LIMIT,
        ge=1,
        le=MAX_CRM_OUTBOX_REQUEUE_LIMIT,
    )
    confirm: bool = False
    confirm_token: str | None = Field(default=None, max_length=64)


class CRMLeadOutboxRequeueResponse(BaseModel):
    dry_run: bool
    limit: int
    eligible_count: int
    requeued_count: int


def _age_seconds(when: datetime | None, now: datetime) -> int | None:
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0, int((now - when).total_seconds()))


def _job_activity_key(job: AIJob) -> tuple[datetime, datetime]:
    activity_at = job.updated_at or job.created_at
    created_at = job.created_at
    if activity_at.tzinfo is None:
        activity_at = activity_at.replace(tzinfo=UTC)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return activity_at, created_at


def _is_allowed_synthetic_tenant(tenant: Tenant) -> bool:
    """Return true only for explicitly demo-marked, fixed-prefix tenants."""

    return bool(tenant.is_demo) and any(tenant.slug.startswith(prefix) for prefix in ALLOWED_SYNTHETIC_SLUG_PREFIXES)


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


def _runtime_summaries() -> (
    tuple[
        HostRuntimeSummary,
        ProcessRuntimeSummary,
        FilesystemRuntimeSummary,
    ]
):
    """Collect local metrics without returning host identity or filesystem paths."""

    process = None
    host_cpu: float | None = None
    process_cpu: float | None = None
    rss_memory: int | None = None
    total_bytes: int | None = None
    free_bytes: int | None = None
    used_percent: float | None = None

    try:
        host_cpu = round(float(psutil.cpu_percent(interval=None)), 2)
    except Exception:
        pass
    try:
        process = psutil.Process(os.getpid())
        process_cpu = round(float(process.cpu_percent(interval=None)), 2)
        rss_memory = int(process.memory_info().rss)
    except Exception:
        pass
    try:
        usage = psutil.disk_usage(Path.cwd().anchor or os.sep)
        total_bytes = int(usage.total)
        free_bytes = int(usage.free)
        used_percent = round(float(usage.percent), 2)
    except Exception:
        pass

    return (
        HostRuntimeSummary(cpu_percent=host_cpu),
        ProcessRuntimeSummary(
            process_id=os.getpid(),
            started_at=PROCESS_STARTED_AT,
            uptime_seconds=max(0, int(time.monotonic() - PROCESS_STARTED_MONOTONIC)),
            python_version=platform.python_version(),
            cpu_percent=process_cpu,
            rss_memory_bytes=rss_memory,
        ),
        FilesystemRuntimeSummary(
            total_bytes=total_bytes,
            free_bytes=free_bytes,
            used_percent=used_percent,
        ),
    )


def _unavailable_celery_summary() -> CeleryWorkerSummary:
    return CeleryWorkerSummary(
        status="unavailable",
        reachable=False,
        missing_required_tasks=list(REQUIRED_CELERY_TASKS),
    )


def _inspect_celery_worker() -> CeleryWorkerSummary:
    """Inspect workers and retain only the code-owned required task names."""

    try:
        registered = celery_app.control.inspect(timeout=CELERY_INSPECT_TIMEOUT_SECONDS).registered()
    except Exception:
        return _unavailable_celery_summary()

    if not isinstance(registered, dict) or not registered:
        return _unavailable_celery_summary()

    registered_tasks = {
        task_name
        for task_names in registered.values()
        if isinstance(task_names, list)
        for task_name in task_names
        if isinstance(task_name, str)
    }
    registered_required = [task_name for task_name in REQUIRED_CELERY_TASKS if task_name in registered_tasks]
    return CeleryWorkerSummary(
        status="available",
        reachable=True,
        worker_count=len(registered),
        registered_required_tasks=registered_required,
        missing_required_tasks=[task_name for task_name in REQUIRED_CELERY_TASKS if task_name not in registered_tasks],
    )


async def _celery_worker_summary() -> CeleryWorkerSummary:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_inspect_celery_worker),
            timeout=CELERY_INSPECT_TIMEOUT_SECONDS + CELERY_INSPECT_OUTER_MARGIN_SECONDS,
        )
    except Exception:
        return _unavailable_celery_summary()


class SuperadminOperationsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _tenant_ids(self) -> list[uuid.UUID]:
        """Return tenant IDs through the established platform-admin boundary."""

        return list((await self.db.execute(select(Tenant.id).order_by(Tenant.id.asc()))).scalars().all())

    async def _set_tenant_context(self, tenant_id: uuid.UUID) -> None:
        """Scope a tenant-scoped table that lacks a platform-wide policy."""

        await self.db.execute(
            text("SELECT set_current_tenant(:tenant_id)"),
            {"tenant_id": str(tenant_id)},
        )

    async def _aggregate_ai_job_health(
        self,
    ) -> tuple[int, datetime | None, int, datetime | None, int]:
        """Aggregate AI jobs without requiring a cross-tenant RLS bypass."""

        queued_count = running_count = failed_count = 0
        oldest_queued: datetime | None = None
        oldest_running: datetime | None = None

        for tenant_id in await self._tenant_ids():
            await self._set_tenant_context(tenant_id)
            row = (
                await self.db.execute(
                    select(
                        func.count(AIJob.id).filter(AIJob.status == "pending").label("queued_count"),
                        func.min(AIJob.created_at).filter(AIJob.status == "pending").label("oldest_queued"),
                        func.count(AIJob.id).filter(AIJob.status == "running").label("running_count"),
                        func.min(AIJob.created_at).filter(AIJob.status == "running").label("oldest_running"),
                        func.count(AIJob.id).filter(AIJob.status.in_(("failed", "error"))).label("failed_count"),
                    )
                )
            ).one()
            queued_count += int(row.queued_count or 0)
            running_count += int(row.running_count or 0)
            failed_count += int(row.failed_count or 0)
            if row.oldest_queued is not None and (oldest_queued is None or row.oldest_queued < oldest_queued):
                oldest_queued = row.oldest_queued
            if row.oldest_running is not None and (oldest_running is None or row.oldest_running < oldest_running):
                oldest_running = row.oldest_running

        return (
            queued_count,
            oldest_queued,
            running_count,
            oldest_running,
            failed_count,
        )

    async def _stale_ai_job_candidates(
        self,
        *,
        cutoff: datetime,
        dry_run: bool,
    ) -> tuple[list[AIJob], bool]:
        """Collect bounded candidates across tenants under tenant-scoped RLS."""

        activity_at = func.coalesce(AIJob.updated_at, AIJob.created_at)
        candidates: list[AIJob] = []
        per_tenant_limit = MAX_STALE_AI_JOB_RECOVERY + 1
        for tenant_id in await self._tenant_ids():
            await self._set_tenant_context(tenant_id)
            query = (
                select(AIJob)
                .where(
                    AIJob.status.in_(("pending", "running")),
                    activity_at <= cutoff,
                )
                .order_by(activity_at.asc(), AIJob.created_at.asc())
                .limit(per_tenant_limit)
            )
            if not dry_run:
                query = query.with_for_update(skip_locked=True)
            candidates.extend(list((await self.db.execute(query)).scalars().all()))

        candidates.sort(key=_job_activity_key)
        truncated = len(candidates) > MAX_STALE_AI_JOB_RECOVERY
        return candidates[:MAX_STALE_AI_JOB_RECOVERY], truncated

    async def summary(self) -> OperationsSummary:
        now = datetime.now(UTC)

        (
            queued_count,
            oldest_queued,
            running_count,
            oldest_running,
            failed_count,
        ) = await self._aggregate_ai_job_health()

        indexing_count, oldest_indexing = (
            await self.db.execute(
                select(func.count(Document.id), func.min(Document.created_at)).where(
                    Document.index_status == "processing"
                )
            )
        ).one()
        failed_index_count = (
            await self.db.execute(select(func.count(Document.id)).where(Document.index_status == "failed"))
        ).scalar_one()
        failed_embedding_count = (
            await self.db.execute(select(func.count(Document.id)).where(Document.embedding_status == "failed"))
        ).scalar_one()
        cleanup_pending_count, oldest_cleanup_pending = (
            await self.db.execute(
                select(func.count(Document.id), func.min(Document.created_at)).where(
                    Document.lifecycle_status == "deletion_pending"
                )
            )
        ).one()
        cleanup_failed_count = (
            await self.db.execute(select(func.count(Document.id)).where(Document.lifecycle_status == "delete_failed"))
        ).scalar_one()

        host, process, filesystem = _runtime_summaries()
        celery = await _celery_worker_summary()
        crm_outbox = (await self.db.execute(text("SELECT * FROM crm_lead_outbox_summary()"))).mappings().one()
        crm_settings = get_settings()
        integration_enabled = bool(crm_settings.CRM_WEBHOOK_URL and crm_settings.CRM_WEBHOOK_SECRET)
        pending_count = int(crm_outbox["pending_count"] or 0)
        retry_count = int(crm_outbox["retry_count"] or 0)

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
                oldest_cleanup_pending_age_seconds=_age_seconds(oldest_cleanup_pending, now),
            ),
            database=_pool_summary(),
            process=process,
            host=host,
            filesystem=filesystem,
            celery=celery,
            crm_lead_outbox=CRMLeadOutboxOperationsSummary(
                integration_status="enabled" if integration_enabled else "disabled",
                held_count=(pending_count + retry_count) if not integration_enabled else 0,
                pending_count=pending_count,
                retry_count=retry_count,
                claimed_count=int(crm_outbox["claimed_count"] or 0),
                dead_count=int(crm_outbox["dead_count"] or 0),
                delivered_count=int(crm_outbox["delivered_count"] or 0),
                oldest_due_age_seconds=_age_seconds(
                    crm_outbox["oldest_due_at"],
                    now,
                ),
            ),
        )

    async def requeue_failed_crm_leads(
        self,
        *,
        dry_run: bool,
        limit: int,
        confirm: bool = False,
        confirm_token: str | None = None,
    ) -> CRMLeadOutboxRequeueResponse:
        if not 1 <= limit <= MAX_CRM_OUTBOX_REQUEUE_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_CRM_OUTBOX_REQUEUE_LIMIT}")
        if not dry_run and (not confirm or confirm_token != CRM_OUTBOX_REQUEUE_CONFIRM_TOKEN):
            raise ValueError(
                "CRM lead requeue requires confirm=true and the exact "
                f"confirm_token={CRM_OUTBOX_REQUEUE_CONFIRM_TOKEN}"
            )

        row = (
            (
                await self.db.execute(
                    text("SELECT * FROM crm_requeue_dead_lead_outbox(" ":limit, :execute)"),
                    {"limit": limit, "execute": not dry_run},
                )
            )
            .mappings()
            .one()
        )
        if not dry_run:
            await self.db.commit()
        return CRMLeadOutboxRequeueResponse(
            dry_run=dry_run,
            limit=limit,
            eligible_count=int(row["eligible_count"] or 0),
            requeued_count=int(row["requeued_count"] or 0),
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
            raise ValueError(f"min_age_hours must be at least {MIN_CLEANUP_AGE_HOURS}")
        if not dry_run and (not confirm or confirm_token != CLEANUP_CONFIRM_TOKEN):
            raise ValueError(
                "Destructive cleanup requires confirm=true and the exact " f"confirm_token={CLEANUP_CONFIRM_TOKEN}"
            )

        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=min_age_hours)
        prefix_filter = or_(*(Tenant.slug.like(f"{prefix}%") for prefix in ALLOWED_SYNTHETIC_SLUG_PREFIXES))
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
            )
            .scalars()
            .all()
        )
        truncated = len(candidates) > MAX_CLEANUP_CANDIDATES
        candidates = candidates[:MAX_CLEANUP_CANDIDATES]
        # ``delete_tenant`` commits and SQLAlchemy expires ORM instances in
        # this session.  Keep the initial listing as plain values so a later
        # candidate cannot trigger implicit async IO (MissingGreenlet).
        candidate_snapshots = [
            (candidate.id, candidate.slug, candidate.created_at)
            for candidate in candidates
        ]
        results: list[SyntheticCleanupResult] = []
        deleted_count = skipped_count = failed_count = 0
        deletion_service = SuperadminService(self.db)

        for candidate_id, candidate_slug, candidate_created_at in candidate_snapshots:
            created_at = candidate_created_at
            age_hours = round(
                max(0, (now - (created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC))).total_seconds())
                / 3600,
                2,
            )
            # Re-read the row before every destructive operation. A slug or
            # demo flag changed after the initial query must fail closed.
            current = await self.db.get(Tenant, candidate_id)
            if current is None or not _is_allowed_synthetic_tenant(current):
                skipped_count += 1
                results.append(
                    SyntheticCleanupResult(
                        tenant_id=candidate_id,
                        slug=candidate_slug,
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
                await deletion_service.delete_tenant(current.id)
            except Exception as exc:
                await self.db.rollback()
                failed_count += 1
                logger.exception(
                    "superadmin.synthetic_cleanup.failed tenant_id=%s slug=%s",
                    candidate_id,
                    candidate_slug,
                )
                results.append(
                    SyntheticCleanupResult(
                        tenant_id=candidate_id,
                        slug=candidate_slug,
                        created_at=created_at,
                        age_hours=age_hours,
                        action="failed",
                        reason=f"{type(exc).__name__}: cleanup failed",
                    )
                )
            else:
                deleted_count += 1
                logger.warning(
                    "superadmin.synthetic_cleanup.deleted tenant_id=%s slug=%s",
                    candidate_id,
                    candidate_slug,
                )
                results.append(
                    SyntheticCleanupResult(
                        tenant_id=candidate_id,
                        slug=candidate_slug,
                        created_at=created_at,
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

    async def recover_stale_ai_jobs(
        self,
        *,
        dry_run: bool,
        min_age_hours: int,
        confirm: bool = False,
        confirm_token: str | None = None,
    ) -> StaleAIJobRecoveryResponse:
        """Cancel bounded, inactive AI jobs without deleting history.

        The query uses ``updated_at`` as the activity clock. During execution
        PostgreSQL row locks with ``skip_locked`` prevent two superadmin
        requests from recovering the same job.
        """

        if not MIN_STALE_AI_JOB_AGE_HOURS <= min_age_hours <= MAX_STALE_AI_JOB_AGE_HOURS:
            raise ValueError(
                f"min_age_hours must be between {MIN_STALE_AI_JOB_AGE_HOURS} and " f"{MAX_STALE_AI_JOB_AGE_HOURS}"
            )
        if not dry_run and (not confirm or confirm_token != STALE_AI_JOB_RECOVERY_CONFIRM_TOKEN):
            raise ValueError(
                "Stale AI job recovery requires confirm=true and the exact "
                f"confirm_token={STALE_AI_JOB_RECOVERY_CONFIRM_TOKEN}"
            )

        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=min_age_hours)
        jobs, truncated = await self._stale_ai_job_candidates(
            cutoff=cutoff,
            dry_run=dry_run,
        )
        ages = [
            _age_seconds(
                job.updated_at or job.created_at,
                now,
            )
            for job in jobs
        ]
        queued_count = sum(1 for job in jobs if job.status == "pending")
        running_count = sum(1 for job in jobs if job.status == "running")
        recovered_count = 0
        skipped_count = 0

        if not dry_run:
            jobs_by_tenant: dict[uuid.UUID, list[AIJob]] = {}
            for job in jobs:
                jobs_by_tenant.setdefault(job.tenant_id, []).append(job)

            for tenant_id, tenant_jobs in jobs_by_tenant.items():
                # FORCE RLS evaluates UPDATE at flush time. Keep both the
                # mutations and their flush inside the matching tenant context.
                await self._set_tenant_context(tenant_id)
                dirty_jobs: list[AIJob] = []
                for job in tenant_jobs:
                    # The lock makes this check stable for this transaction.
                    # Keep the guard explicit so future statuses fail closed.
                    if job.status not in {"pending", "running"}:
                        skipped_count += 1
                        continue
                    previous_status = job.status
                    previous_errors = job.errors
                    recovery_record = {
                        "code": "stale_ai_job_recovered",
                        "previous_status": previous_status,
                        "recovered_at": now.isoformat(),
                    }
                    job.errors = {"recovery": recovery_record}
                    if previous_errors is not None:
                        job.errors["previous"] = previous_errors
                    recovery_note = " [stale AI job recovery: cancelled]"
                    if not job.message:
                        job.message = "AI job cancelled by stale-job recovery"
                    elif recovery_note not in job.message:
                        job.message = f"{job.message}{recovery_note}"
                    job.status = STALE_AI_JOB_TERMINAL_STATUS
                    job.stage = "cancelled"
                    job.completed_at = now
                    job.updated_at = now
                    dirty_jobs.append(job)
                    recovered_count += 1
                if dirty_jobs:
                    await self.db.flush(dirty_jobs)

        return StaleAIJobRecoveryResponse(
            dry_run=dry_run,
            min_age_hours=min_age_hours,
            terminal_status=STALE_AI_JOB_TERMINAL_STATUS,
            eligible_count=len(jobs),
            queued_count=queued_count,
            running_count=running_count,
            recovered_count=recovered_count,
            skipped_count=skipped_count,
            truncated=truncated,
            oldest_age_seconds=max(ages) if ages else None,
            newest_age_seconds=min(ages) if ages else None,
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


@router.post(
    "/recover-stale-ai-jobs",
    response_model=StaleAIJobRecoveryResponse,
    status_code=status.HTTP_200_OK,
)
async def recover_stale_ai_jobs(
    payload: StaleAIJobRecoveryRequest | None = None,
    user: User = Depends(require_role("superadmin")),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> StaleAIJobRecoveryResponse:
    """Preview or cancel old queued/running AI jobs."""

    payload = payload or StaleAIJobRecoveryRequest()
    try:
        return await SuperadminOperationsService(db).recover_stale_ai_jobs(
            dry_run=payload.dry_run,
            min_age_hours=payload.min_age_hours,
            confirm=payload.confirm,
            confirm_token=payload.confirm_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/requeue-failed-crm-leads",
    response_model=CRMLeadOutboxRequeueResponse,
    status_code=status.HTTP_200_OK,
)
async def requeue_failed_crm_leads(
    payload: CRMLeadOutboxRequeueRequest | None = None,
    user: User = Depends(require_role("superadmin")),  # noqa: B008
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> CRMLeadOutboxRequeueResponse:
    """Preview or requeue a bounded batch of terminal CRM deliveries."""

    payload = payload or CRMLeadOutboxRequeueRequest()
    try:
        return await SuperadminOperationsService(db).requeue_failed_crm_leads(
            dry_run=payload.dry_run,
            limit=payload.limit,
            confirm=payload.confirm,
            confirm_token=payload.confirm_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
