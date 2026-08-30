"""AI Job service — DB-backed job state management."""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_job import AIJob
from app.models.tenants import Tenant

DEFAULT_TENANT_AI_ACTIVE_LIMIT = 2
MAX_TENANT_AI_ACTIVE_LIMIT = 8
TENANT_AI_ACTIVE_LIMIT_SETTING = "ai_max_active_jobs"
DEFAULT_AI_WORKER_CONCURRENCY = 2
DEFAULT_HISTORICAL_JOB_SECONDS = 510
ACTIVE_AI_JOB_STATUSES = frozenset({"pending", "running"})
AIJobTaskName = Literal["generate_course", "regenerate_module", "regenerate_lesson"]
logger = logging.getLogger(__name__)


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


class AIJobSubmissionUnavailableError(Exception):
    """The worker is absent or rejected a job after it was admitted."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


class AIJobDispatcher(Protocol):
    """Remote queue boundary used by durable AI job submission."""

    def dispatch(self, task_name: AIJobTaskName, *, task_id: str, kwargs: dict[str, Any]) -> None: ...


class CeleryAIJobDispatcher:
    """Production adapter. Task imports stay behind the submission boundary."""

    _tasks = {
        "generate_course": "generate_course_task",
        "regenerate_module": "regenerate_module_task",
        "regenerate_lesson": "regenerate_lesson_task",
    }

    def dispatch(self, task_name: AIJobTaskName, *, task_id: str, kwargs: dict[str, Any]) -> None:
        from app.modules.ai import tasks

        task_attribute = self._tasks.get(task_name)
        task = getattr(tasks, task_attribute, None) if task_attribute else None
        if task is None:
            raise AIJobSubmissionUnavailableError("AI worker is unavailable")
        try:
            task.apply_async(task_id=task_id, kwargs=kwargs)
        except Exception as exc:
            logger.exception("Could not enqueue AI %s job %s", task_name, task_id)
            raise AIJobSubmissionUnavailableError("AI job could not be queued") from exc


@dataclass
class InMemoryAIJobDispatcher:
    """Test adapter recording dispatches without a Celery broker."""

    submissions: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)

    def dispatch(self, task_name: AIJobTaskName, *, task_id: str, kwargs: dict[str, Any]) -> None:
        self.submissions.append((task_name, task_id, kwargs))


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


async def resolve_tenant_ai_active_limit(
    db: AsyncSession,
    tenant_id: Any,
    *,
    default_limit: int = DEFAULT_TENANT_AI_ACTIVE_LIMIT,
) -> int:
    """Resolve an optional tenant override without weakening the global cap.

    Overrides live in the existing ``tenants.settings`` JSONB as
    ``ai_max_active_jobs``. Invalid, boolean, or out-of-range values fail
    closed to the configured environment default.
    """
    default_limit = _positive_int(default_limit, "default_limit")
    if tenant_id is None:
        return default_limit
    settings = await db.scalar(select(Tenant.settings).where(Tenant.id == tenant_id))
    if not isinstance(settings, dict):
        return default_limit
    value = settings.get(TENANT_AI_ACTIVE_LIMIT_SETTING)
    if isinstance(value, bool) or not isinstance(value, int):
        return default_limit
    if not 1 <= value <= MAX_TENANT_AI_ACTIVE_LIMIT:
        return default_limit
    return value


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


async def claim_generation_execution(
    db: AsyncSession, job_id: str, tenant_id: str | None = None
) -> bool:
    """Atomically claim one pending generation delivery.

    Celery is at-least-once. The durable job row is the execution seam: only
    the delivery that changes ``pending`` to ``running`` may call providers.
    """
    if tenant_id is None:
        raise ValueError("tenant_id is required for worker generation execution")
    await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": tenant_id})
    predicates = [AIJob.id == job_id, AIJob.status == "pending", AIJob.tenant_id == tenant_id]
    result = await db.execute(
        update(AIJob).where(*predicates).values(
            status="running",
            stage="ingestion",
            started_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    await db.commit()
    return bool(result.rowcount)


async def fail_claimed_generation_execution(
    db: AsyncSession, job_id: str, message: str, tenant_id: str | None = None
) -> bool:
    """Terminally fail only the execution this worker previously claimed."""
    if tenant_id is None:
        raise ValueError("tenant_id is required for worker generation execution")
    await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": tenant_id})
    predicates = [AIJob.id == job_id, AIJob.status == "running", AIJob.tenant_id == tenant_id]
    result = await db.execute(
        update(AIJob).where(*predicates).values(
            status="failed", stage="failed", message=message,
            updated_at=datetime.now(UTC), completed_at=datetime.now(UTC),
        )
    )
    await db.commit()
    return bool(result.rowcount)


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


async def submit_ai_job(
    db: AsyncSession,
    *,
    tenant_id,
    user_id,
    course_id,
    params: dict[str, Any],
    task_name: AIJobTaskName,
    task_kwargs: Callable[[AIJob], dict[str, Any]],
    active_limit: int,
    worker_concurrency: int,
    historical_estimate_seconds: int,
    generation: bool = False,
    reserve_course_generation: bool = False,
    dispatcher: AIJobDispatcher | None = None,
) -> tuple[AIJob, dict[str, int | None]]:
    """Durably admit, commit and dispatch one AI job.

    Generation alone receives trial reservation and LLM-budget charging.  The
    regeneration jobs deliberately share queue admission but not those product
    limits.  A failed dispatch is made visible on the durable job and reverses
    the generation charges made by this submission.
    """
    try:
        job = await create_admitted_ai_job(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            course_id=course_id,
            params=params,
            active_limit=active_limit,
        )
    except AIJobAdmissionLimitReachedError:
        raise

    charged = False
    reserved = False
    if generation and reserve_course_generation:
        from app.core.trial_limits import reserve_ai_course_generation

        await reserve_ai_course_generation(db, tenant_id)
        reserved = True
    if generation and tenant_id:
        from app.modules.ai.budget import check_and_charge_llm_budget

        await check_and_charge_llm_budget(db, str(tenant_id), operation="generate_course")
        charged = True

    queue_metadata = await build_ai_job_queue_metadata(
        db,
        job,
        active_limit=active_limit,
        worker_concurrency=worker_concurrency,
        historical_estimate_seconds=historical_estimate_seconds,
    )
    await db.commit()

    try:
        (dispatcher or CeleryAIJobDispatcher()).dispatch(
            task_name,
            task_id=str(job.id),
            kwargs=task_kwargs(job),
        )
    except AIJobSubmissionUnavailableError as exc:
        await update_ai_job(
            db,
            str(job.id),
            tenant_id=str(tenant_id) if tenant_id else None,
            status="failed",
            stage="failed",
            message=exc.detail,
        )
        if reserved:
            from app.core.trial_limits import release_ai_course_generation

            await release_ai_course_generation(db, tenant_id)
        if charged:
            from app.modules.ai.budget import refund_llm_budget

            await refund_llm_budget(db, str(tenant_id), "generate_course")
        await db.commit()
        raise

    return job, queue_metadata
