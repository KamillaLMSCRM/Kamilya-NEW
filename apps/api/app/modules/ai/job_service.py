"""AI Job service — DB-backed job state management."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_job import AIJob
from app.models.tenants import Tenant

DEFAULT_TENANT_AI_ACTIVE_LIMIT = 2
DEFAULT_AI_WORKER_CONCURRENCY = 2
DEFAULT_HISTORICAL_JOB_SECONDS = 510
ACTIVE_AI_JOB_STATUSES = frozenset({"pending", "running"})


class AIJobAdmissionLimitReachedError(Exception):
    """Stable domain error raised when a tenant has no AI admission slot."""

    code = "tenant_ai_job_limit_reached"

    def __init__(self, *, tenant_id, active_count: int, active_limit: int):
        self.tenant_id = tenant_id
        self.active_count = active_count
        self.active_limit = active_limit
        super().__init__(
            f"Tenant AI job limit reached: {active_count}/{active_limit} active jobs"
        )


def _positive_int(value: int, name: str) -> int:
    if value < 1:
        raise ValueError(f"{name} must be greater than zero")
    return value


async def _lock_tenant_row(db: AsyncSession, tenant_id) -> None:
    """Serialize admission decisions for one tenant in PostgreSQL."""
    if tenant_id is None:
        return
    await db.execute(
        select(Tenant.id).where(Tenant.id == tenant_id).with_for_update()
    )


async def count_active_ai_jobs(db: AsyncSession, tenant_id) -> int:
    """Count only pending/running jobs for one tenant."""
    result = await db.execute(
        select(func.count(AIJob.id)).where(
            AIJob.tenant_id == tenant_id,
            AIJob.status.in_(ACTIVE_AI_JOB_STATUSES),
        )
    )
    return int(result.scalar_one() or 0)


async def create_ai_job(
    db: AsyncSession,
    tenant_id,
    user_id,
    course_id=None,
    params: dict | None = None,
) -> AIJob:
    """Create a job without generation admission control.

    Document indexing and other maintenance queues use this helper. Course
    generation must opt in explicitly through ``create_admitted_ai_job`` so a
    busy generation queue cannot block document recovery work.
    """
    return await _insert_ai_job(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        course_id=course_id,
        params=params,
    )


async def create_admitted_ai_job(
    db: AsyncSession,
    tenant_id,
    user_id,
    course_id=None,
    params: dict | None = None,
    *,
    active_limit: int = DEFAULT_TENANT_AI_ACTIVE_LIMIT,
) -> AIJob:
    """Create a generation job after an atomic tenant-scoped admission check.

    The caller owns the transaction. The tenant row lock and the job insert
    therefore remain in one transaction, preventing concurrent requests for
    the same tenant from both passing the capacity check.
    """
    active_limit = _positive_int(active_limit, "active_limit")
    await _lock_tenant_row(db, tenant_id)
    active_count = await count_active_ai_jobs(db, tenant_id)
    if active_count >= active_limit:
        raise AIJobAdmissionLimitReachedError(
            tenant_id=tenant_id,
            active_count=active_count,
            active_limit=active_limit,
        )

    return await _insert_ai_job(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        course_id=course_id,
        params=params,
    )


async def _insert_ai_job(
    db: AsyncSession,
    *,
    tenant_id,
    user_id,
    course_id=None,
    params: dict | None = None,
) -> AIJob:
    job = AIJob(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id=user_id,
        course_id=course_id,
        status="pending",
        stage="queued",
        progress=0,
        message="Job queued",
        params=params,
        created_at=datetime.now(UTC),
    )
    db.add(job)
    await db.flush()
    return job


async def build_ai_job_queue_metadata(
    db: AsyncSession,
    job: AIJob,
    *,
    active_limit: int = DEFAULT_TENANT_AI_ACTIVE_LIMIT,
    worker_concurrency: int = DEFAULT_AI_WORKER_CONCURRENCY,
    historical_estimate_seconds: int = DEFAULT_HISTORICAL_JOB_SECONDS,
) -> dict[str, int | None]:
    """Build queue metadata from durable jobs, scoped to ``job.tenant_id``.

    ``queue_position`` is one-based for pending jobs. Running and terminal
    jobs have no queue position. ETA is based on active jobs
    created before this job and the configured worker concurrency; it is an
    estimate, not an SLA.
    """
    active_limit = _positive_int(active_limit, "active_limit")
    worker_concurrency = _positive_int(worker_concurrency, "worker_concurrency")
    if historical_estimate_seconds < 0:
        raise ValueError("historical_estimate_seconds must not be negative")

    active_count = await count_active_ai_jobs(db, job.tenant_id)
    queue_position: int | None = None
    estimated_wait_seconds: int | None = None

    if job.status == "pending":
        before_current = and_(
            AIJob.created_at < job.created_at,
            AIJob.id != job.id,
        )
        same_timestamp_before = and_(
            AIJob.created_at == job.created_at,
            AIJob.id < job.id,
        )
        result = await db.execute(
            select(func.count(AIJob.id)).where(
                AIJob.tenant_id == job.tenant_id,
                AIJob.status.in_(ACTIVE_AI_JOB_STATUSES),
                or_(before_current, same_timestamp_before),
            )
        )
        ahead_count = int(result.scalar_one() or 0)
        queue_position = ahead_count + 1
        estimated_wait_seconds = (
            (ahead_count + worker_concurrency - 1) // worker_concurrency
        ) * historical_estimate_seconds

    return {
        "tenant_active_jobs": active_count,
        "tenant_active_limit": active_limit,
        "queue_position": queue_position,
        "estimated_wait_seconds": estimated_wait_seconds,
    }


async def get_ai_job(
    db: AsyncSession, job_id: str, tenant_id: str | None = None
) -> AIJob | None:
    """Get AI job by ID, scoped to tenant (defense-in-depth, see audit §3.3).

    Pass `tenant_id` to scope the lookup to a single tenant. If omitted
    (only acceptable for superadmin/global system jobs), the function
    returns the job regardless of tenant — but callers are expected to
    do their own permission check.
    """
    stmt = select(AIJob).where(AIJob.id == job_id)
    if tenant_id is not None:
        stmt = stmt.where(AIJob.tenant_id == tenant_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_ai_job(
    db: AsyncSession, job_id: str, tenant_id: str | None = None, **kwargs
) -> AIJob | None:
    """Update AI job fields, scoped to tenant.

    Same scoping rules as get_ai_job — pass tenant_id for safety. If
    omitted, the lookup is unscoped (superadmin only).
    """
    job = await get_ai_job(db, job_id, tenant_id=tenant_id)
    if not job:
        return None
    # Recovery/cancellation is terminal. Late worker callbacks must not
    # resurrect the job or overwrite its diagnostics/result.
    if job.status == "cancelled" and kwargs.get("status") != "cancelled":
        return job
    for k, v in kwargs.items():
        setattr(job, k, v)
    job.updated_at = datetime.now(UTC)
    await db.flush()
    return job


async def get_user_jobs(
    db: AsyncSession, tenant_id, user_id, limit: int = 20
) -> list[AIJob]:
    """Get recent AI jobs for a user."""
    result = await db.execute(
        select(AIJob)
        .where(AIJob.tenant_id == tenant_id, AIJob.user_id == user_id)
        .order_by(AIJob.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()
