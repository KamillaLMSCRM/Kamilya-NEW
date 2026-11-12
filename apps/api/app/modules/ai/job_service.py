"""AI Job service — DB-backed job state management."""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, cast
from uuid import UUID

from sqlalchemy import and_, false, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_job import AIJob
from app.models.tenants import Tenant
from app.modules.ai.generation_engine import (
    CURRENT_SOURCE_ANALYSIS_MODE,
    RETIRED_GENERATION_ENGINE_CODE,
    RETIRED_GENERATION_ENGINE_MESSAGE,
    SUPPORTED_GENERATION_ENGINES,
    job_uses_current_generation_engine,
)

DEFAULT_TENANT_AI_ACTIVE_LIMIT = 2
MAX_TENANT_AI_ACTIVE_LIMIT = 8
TENANT_AI_ACTIVE_LIMIT_SETTING = "ai_max_active_jobs"
DEFAULT_AI_WORKER_CONCURRENCY = 2
DEFAULT_HISTORICAL_JOB_SECONDS = 510
ACTIVE_AI_JOB_STATUSES = frozenset({"pending", "running"})
GENERATION_INTERRUPTED_MESSAGE = (
    "Генерация приостановлена и может быть продолжена без повторной обработки готовых частей"
)
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
    """The worker is known unavailable before a publish attempt."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


class AIJobDispatchOutcomeUnknownError(Exception):
    """A publish was attempted and its acceptance cannot be established."""

    def __init__(self, job_id: str):
        self.job_id = job_id
        super().__init__("ai_job_dispatch_outcome_unknown")


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
            task.apply_async(task_id=task_id, kwargs=kwargs, retry=False)
        except Exception:
            logger.warning("AI %s publish outcome unknown for delivery %s", task_name, task_id)
            raise AIJobDispatchOutcomeUnknownError("") from None


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
    db: AsyncSession,
    job_id: str,
    tenant_id: str | None = None,
    *,
    for_update: bool = False,
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
    if for_update:
        # A caller may already have loaded this job in the same identity map.
        # After waiting for a concurrent cancellation, FOR UPDATE must refresh
        # that object from PostgreSQL instead of returning stale ORM state and
        # accidentally resurrecting a terminal job.
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_ai_job(
    db: AsyncSession, job_id: str, tenant_id: str | None = None, **kwargs
) -> AIJob | None:
    """Update AI job fields, scoped to tenant.

    Same scoping rules as get_ai_job — pass tenant_id for safety. If
    omitted, the lookup is unscoped (superadmin only).
    """
    # Serialize every worker callback with cancellation. Without the row lock a
    # callback can observe "running", wait behind a cancelling transaction, and
    # then flush stale progress or a terminal state after cancellation commits.
    job = await get_ai_job(db, job_id, tenant_id=tenant_id, for_update=True)
    if not job:
        return None
    # Recovery/cancellation is terminal. Late worker callbacks must not
    # resurrect the job or overwrite its diagnostics/result.
    if job.status == "cancelled" and kwargs.get("status") != "cancelled":
        return job
    for k, v in kwargs.items():
        setattr(job, k, v)
    now = datetime.now(UTC)
    if kwargs.get("status") == "completed" and getattr(job, "completed_at", None) is None:
        job.completed_at = now  # type: ignore[assignment]
    job.updated_at = now
    await db.flush()
    return job


def _generation_budget_month(job: AIJob, params: dict[str, Any]) -> str:
    from app.modules.ai.budget import checked_budget_month

    if "generation_budget_month" in params:
        value = params["generation_budget_month"]
        if not isinstance(value, str):
            raise ValueError("generation_budget_period_unverified")
        return checked_budget_month(value)
    # Legacy admission charged after creation and before the worker started.
    # A single UTC month across that interval proves the period; crossing a
    # boundary without a persisted receipt must not refund an unrelated month.
    created = getattr(job, "created_at", None)
    upper = getattr(job, "started_at", None) or datetime.now(UTC)
    if (not isinstance(created, datetime) or created.tzinfo is None
            or not isinstance(upper, datetime) or upper.tzinfo is None):
        raise ValueError("generation_budget_period_unverified")
    created, upper = created.astimezone(UTC), upper.astimezone(UTC)
    period = created.strftime("%Y-%m")
    if upper < created or upper.strftime("%Y-%m") != period:
        raise ValueError("generation_budget_period_unverified")
    return period


def _abandon_marker_digest(job: Any) -> str | None:
    from app.modules.ai.v3.final_save_contract import INTENT_KEY, RECEIPT_KEY, SOURCE_FIRST_KEYS
    from app.modules.ai.v3.pending_stage_transactions import checked_entries
    if not isinstance(getattr(job, "result", None), dict) or any(key in job.result for key in (INTENT_KEY, RECEIPT_KEY, *SOURCE_FIRST_KEYS)):
        return None
    if "v3_pending_stages" in job.result and job.result["v3_pending_stages"] is None:
        # A server-created unclassified hold cannot be resumed or refunded. Its
        # owner may explicitly terminally fence it, retaining NULL and all usage.
        from app.modules.ai.v3.revision_policy import REVIEW_KEY, is_practical_policy
        params = job.params if isinstance(getattr(job, "params", None), dict) else {}
        analysis = params.get("source_analysis")
        if (getattr(job, "errors", None) != ["generation_stage_outcome_unknown"]
                or not isinstance(analysis, dict) or analysis.get("generation_engine") != "evidence_v3"
                or analysis.get("analysis_mode") != CURRENT_SOURCE_ANALYSIS_MODE
                or not is_practical_policy(analysis.get(REVIEW_KEY))):
            return None
        return hashlib.sha256(b"null").hexdigest()
    try:
        if not checked_entries(job.result):
            return None
        return hashlib.sha256(json.dumps(job.result["v3_pending_stages"], sort_keys=True,
            separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
    except (ValueError, TypeError):
        return None


def is_abandoned_unknown(job: Any) -> bool:
    params = job.params if isinstance(getattr(job, "params", None), dict) else {}
    prior = params.get("generation_abandonment")
    digest = _abandon_marker_digest(job)
    return bool(digest and isinstance(prior, dict) and prior.get("policy") == "unknown-provider-abandon-v1"
        and prior.get("actor_id") == str(getattr(job, "user_id", None)) and prior.get("acknowledged") is True
        and prior.get("provider_outcome") == "unknown" and prior.get("cost") == "unknown"
        and prior.get("pending_marker_sha256") == digest and job.status == "failed" and getattr(job, "course_id", None) is None)


def can_abandon_unknown(job: Any) -> bool:
    params = getattr(job, "params", None)
    if not isinstance(params, dict):
        return False
    if (isinstance(getattr(job, "result", None), dict) and "v3_pending_stages" in job.result
            and job.result["v3_pending_stages"] is None and getattr(job, "status", None) != "interrupted"):
        return False
    return (getattr(job, "status", None) in {"running", "interrupted"}
            and getattr(job, "course_id", None) is None
            and "generation_abandonment" not in params
            and _abandon_marker_digest(job) is not None)


async def abandon_unknown_generation(
    db: AsyncSession, *, job_id: str, tenant_id: UUID, user_id: UUID,
) -> str:
    """Terminally fence an owned unknown stage without touching its reservation or journal."""
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('ai_generation_admission' || :tenant_id))"),
                     {"tenant_id": str(tenant_id)})
    await _lock_tenant_row(db, tenant_id)
    job = await get_ai_job(db, job_id, tenant_id=str(tenant_id), for_update=True)
    if job is None or job.user_id != user_id:
        return "not_found"
    params: dict[str, Any] = dict(job.params) if isinstance(job.params, dict) else {}
    marker_digest = _abandon_marker_digest(job)
    if marker_digest is None:
        return "conflict"
    if "generation_abandonment" in params:
        if is_abandoned_unknown(job):
            return "abandoned"
        return "conflict"
    if not can_abandon_unknown(job):
        return "conflict"
    now = datetime.now(UTC)
    params["generation_abandonment"] = {"policy": "unknown-provider-abandon-v1", "actor_id": str(user_id),
        "acknowledged": True, "provider_outcome": "unknown", "cost": "unknown", "recorded_at": now.isoformat(),
        "pending_marker_sha256": marker_digest}
    job.params = params  # type: ignore[assignment]
    job.status = "failed"  # type: ignore[assignment]
    job.stage = "abandoned"  # type: ignore[assignment]
    job.message = "Генерация остановлена; результат и стоимость вызова провайдера неизвестны."  # type: ignore[assignment]
    job.completed_at = now  # type: ignore[assignment]
    job.updated_at = now  # type: ignore[assignment]
    await db.commit()
    return "abandoned"


def is_quarantined_generation(job: Any) -> bool:
    params = job.params if isinstance(getattr(job, "params", None), dict) else {}
    prior = params.get("generation_quarantine")
    digest = _abandon_marker_digest(job)
    return bool(digest and isinstance(prior, dict) and prior.get("policy") == "retained-pending-stop-v1"
        and prior.get("actor_id") == str(getattr(job, "user_id", None)) and prior.get("acknowledged") is True
        and prior.get("pending_marker_sha256") == digest and isinstance(prior.get("observed_updated_at"), str)
        and job.status == "failed" and job.stage == "quarantined" and getattr(job, "course_id", None) is None)


async def quarantine_generation(
    db: AsyncSession, *, job_id: str, tenant_id: UUID, user_id: UUID, expected_updated_at: datetime,
) -> str:
    """Fence an interrupted unaccepted stage; retain all evidence and its reservation.

    Unlike unknown-outcome abandonment, this action makes no statement about
    whether a provider replied, whether a reply was valid, or what it cost.
    It neither cancels an in-flight provider request nor permits its late save.
    """
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('ai_generation_admission' || :tenant_id))"),
                     {"tenant_id": str(tenant_id)})
    await _lock_tenant_row(db, tenant_id)
    job = await get_ai_job(db, job_id, tenant_id=str(tenant_id), for_update=True)
    if job is None or job.user_id != user_id:
        return "not_found"
    if expected_updated_at.tzinfo is None:
        return "conflict"
    observed = expected_updated_at.astimezone(UTC).isoformat()
    params: dict[str, Any] = dict(job.params) if isinstance(job.params, dict) else {}
    if "generation_quarantine" in params:
        prior = params["generation_quarantine"]
        return "quarantined" if (is_quarantined_generation(job) and isinstance(prior, dict)
            and prior.get("observed_updated_at") == observed) else "conflict"
    if (job.status != "interrupted" or job.course_id is not None
            or "generation_abandonment" in params or not isinstance(job.updated_at, datetime)
            or job.updated_at.tzinfo is None or job.updated_at.astimezone(UTC) != expected_updated_at.astimezone(UTC)):
        return "conflict"
    marker_digest = _abandon_marker_digest(job)
    if marker_digest is None:
        return "conflict"
    now = datetime.now(UTC)
    params["generation_quarantine"] = {"policy": "retained-pending-stop-v1", "actor_id": str(user_id),
        "acknowledged": True, "recorded_at": now.isoformat(), "observed_updated_at": observed,
        "pending_marker_sha256": marker_digest}
    job.params = params
    job.status = "failed"
    job.stage = "quarantined"
    job.message = "Задача остановлена без повтора вызова. Состояние, журнал и резерв сохранены для проверки."
    job.completed_at = now
    job.updated_at = now
    await db.commit()
    return "quarantined"


async def release_generation_reservation_once(
    db: AsyncSession,
    *,
    job_id: str,
    tenant_id: UUID | str | None,
) -> bool:
    """Release a new-course quota/budget reservation exactly once.

    The durable marker prevents the HTTP cancellation path and an already
    running worker from double-refunding the same logical job.
    """

    if tenant_id is None:
        return False
    tenant_value = str(tenant_id)
    job = await get_ai_job(db, job_id, tenant_id=tenant_value, for_update=True)
    from app.modules.ai.v3.pending_stage_transactions import has_pending

    if job is None or job.course_id is not None or has_pending(getattr(job, "result", None)):
        return False
    params = dict(job.params or {})
    legacy_new_course = "documents" in params and not params.get("action")
    reservation_required = (
        params.get("generation_reservation_required") is True or legacy_new_course
    )
    if not reservation_required or params.get("generation_reservation_released") is True:
        return False

    from app.core.trial_limits import release_ai_course_generation
    from app.modules.ai.budget import refund_llm_budget

    month_key = _generation_budget_month(job, params)
    await release_ai_course_generation(db, tenant_id)
    await refund_llm_budget(db, tenant_value, "generate_course", month_key=month_key)
    params["generation_reservation_released"] = True
    job.params = params
    await db.flush()
    return True


def _generation_delivery_predicate(job_id: str, delivery_id: str) -> Any:
    """Match the active delivery; old initial jobs used the job ID as task ID."""
    stored = AIJob.result["delivery_task_id"].as_string()
    resume_count = AIJob.result["resume_count"].as_integer()
    legacy_initial = and_(stored.is_(None), or_(resume_count.is_(None), resume_count == 0)) if delivery_id == job_id else false()
    return or_(stored == delivery_id, legacy_initial)


def _no_pending_stage() -> Any:
    from app.modules.ai.v3.pending_stage_transactions import pending_sql_predicate

    return ~pending_sql_predicate()


async def claim_generation_execution(
    db: AsyncSession, job_id: str, tenant_id: str | None = None, delivery_id: str | None = None
) -> bool:
    """Atomically claim one pending generation delivery.

    Celery is at-least-once. The durable job row is the execution seam: only
    the delivery that changes ``pending`` to ``running`` may call providers.
    """
    if tenant_id is None or not isinstance(delivery_id, str) or not delivery_id:
        raise ValueError("tenant_id and delivery_id are required for worker generation execution")
    await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": tenant_id})
    # The server-issued marker is created only after private checkpoint checks
    # while holding the job lock. Worker inspection rechecks all custody before
    # replay; this predicate admits only its exact delivery to that inspection.
    from app.modules.ai.v3.retained_author_replay import AUTHORIZATION_KEY, AUTHORIZATION_POLICY
    marker = AIJob.params[AUTHORIZATION_KEY]
    replay_delivery = and_(marker["policy"].as_string() == AUTHORIZATION_POLICY,
                           marker["delivery_id"].as_string() == delivery_id,
                           func.length(marker["stage"].as_string()) == 64,
                           func.length(marker["body_sha256"].as_string()) == 64,
                           func.length(marker["pending_sha256"].as_string()) == 64)
    predicates = [
        AIJob.id == job_id,
        AIJob.status == "pending",
        AIJob.tenant_id == tenant_id,
        _generation_delivery_predicate(job_id, delivery_id),
        AIJob.params["source_analysis"]["generation_engine"].as_string().in_(SUPPORTED_GENERATION_ENGINES),
        AIJob.params["source_analysis"]["analysis_mode"].as_string()
        == CURRENT_SOURCE_ANALYSIS_MODE,
    ]
    predicates.append(or_(_no_pending_stage(), replay_delivery))
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


async def interrupt_pending_generation_execution(
    db: AsyncSession, job_id: str, tenant_id: str | None, delivery_id: str | None
) -> bool:
    """Hold only an unclaimed, current delivery for explicit manual resume."""
    if tenant_id is None or not isinstance(delivery_id, str) or not delivery_id:
        raise ValueError("tenant_id and delivery_id are required for worker generation execution")
    await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": tenant_id})
    result = await db.execute(
        update(AIJob).where(
            AIJob.id == job_id,
            AIJob.tenant_id == tenant_id,
            AIJob.status == "pending",
            _generation_delivery_predicate(job_id, delivery_id),
            AIJob.params["source_analysis"]["generation_engine"].as_string().in_(SUPPORTED_GENERATION_ENGINES),
            AIJob.params["source_analysis"]["analysis_mode"].as_string() == CURRENT_SOURCE_ANALYSIS_MODE,
            _no_pending_stage(),
        ).values(
            status="interrupted", stage="interrupted", message=GENERATION_INTERRUPTED_MESSAGE,
            errors=["generation_interrupted"], completed_at=None, updated_at=datetime.now(UTC),
        )
    )
    await db.commit()
    return bool(getattr(result, "rowcount", 0))


async def retire_legacy_generation_execution(
    db: AsyncSession, job_id: str, tenant_id: str | None = None, delivery_id: str | None = None
) -> bool:
    """Fail an old queued job before providers run and refund its reservation once."""
    if tenant_id is None or not isinstance(delivery_id, str) or not delivery_id:
        raise ValueError("tenant_id and delivery_id are required for worker generation execution")
    await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": tenant_id})
    await _lock_tenant_row(db, tenant_id)
    now = datetime.now(UTC)
    result = await db.execute(
        update(AIJob)
        .where(
            AIJob.id == job_id,
            AIJob.status == "pending",
            AIJob.tenant_id == tenant_id,
            _generation_delivery_predicate(job_id, delivery_id),
            _no_pending_stage(),
            or_(
                AIJob.params["source_analysis"]["generation_engine"].as_string().is_(None),
                AIJob.params["source_analysis"]["generation_engine"].as_string().notin_(SUPPORTED_GENERATION_ENGINES),
                AIJob.params["source_analysis"]["analysis_mode"].as_string().is_(None),
                AIJob.params["source_analysis"]["analysis_mode"].as_string() != CURRENT_SOURCE_ANALYSIS_MODE,
            ),
        )
        .values(
            status="failed",
            stage="failed",
            message=RETIRED_GENERATION_ENGINE_MESSAGE,
            errors=[RETIRED_GENERATION_ENGINE_CODE],
            updated_at=now,
            completed_at=now,
        )
    )
    retired = bool(result.rowcount)  # type: ignore[attr-defined]
    if retired:
        await release_generation_reservation_once(
            db,
            job_id=job_id,
            tenant_id=tenant_id,
        )
    await db.commit()
    return retired


async def fail_claimed_generation_execution(
    db: AsyncSession, job_id: str, message: str, tenant_id: str | None = None, delivery_id: str | None = None
) -> bool:
    """Terminally fail only the execution this worker previously claimed."""
    if tenant_id is None or not isinstance(delivery_id, str) or not delivery_id:
        raise ValueError("tenant_id and delivery_id are required for worker generation execution")
    await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": tenant_id})
    predicates = [AIJob.id == job_id, AIJob.status == "running", AIJob.tenant_id == tenant_id,
                  _generation_delivery_predicate(job_id, delivery_id), _no_pending_stage()]
    result = await db.execute(
        update(AIJob).where(*predicates).values(
            status="failed", stage="failed", message=message,
            updated_at=datetime.now(UTC), completed_at=datetime.now(UTC),
        )
    )
    await db.commit()
    return bool(result.rowcount)


async def interrupt_claimed_generation_execution(
    db: AsyncSession, job_id: str, tenant_id: str | None = None, delivery_id: str | None = None,
    *, reason: str = "generation_interrupted",
) -> bool:
    """Pause before new work; preserve completed checkpoints and the reservation."""
    if tenant_id is None or not isinstance(delivery_id, str) or not delivery_id:
        raise ValueError("tenant_id and delivery_id are required for worker generation execution")
    if reason not in {"generation_interrupted", "source_reference_review_required"}:
        raise ValueError("generation_interruption_reason_invalid")
    message = ("Проверьте подтвержденные отсылки источника. Готовые части генерации сохранены."
               if reason == "source_reference_review_required" else GENERATION_INTERRUPTED_MESSAGE)
    await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": tenant_id})
    predicates = [AIJob.id == job_id, AIJob.status == "running", AIJob.tenant_id == tenant_id,
                  _generation_delivery_predicate(job_id, delivery_id), _no_pending_stage()]
    result = await db.execute(
        update(AIJob).where(*predicates).values(
            status="interrupted",
            stage="interrupted",
            message=message,
            errors=[reason],
            updated_at=datetime.now(UTC),
            completed_at=None,
        )
    )
    await db.commit()
    return bool(getattr(result, "rowcount", 0))


def is_resumable_generation_job(job: AIJob) -> bool:
    """Only explicit evidence_v2 interruptions can be resumed."""
    from app.modules.ai.v3.pending_stage_transactions import has_pending

    return bool(job.status == "interrupted" and job_uses_current_generation_engine(job)
                and not (isinstance(getattr(job, "errors", None), list) and "source_reference_review_required" in job.errors)
                and not has_pending(getattr(job, "result", None)))


def may_resume_retained_author(job: AIJob) -> bool:
    """Preserve ordinary engine, status and source-review holds for replay."""
    return bool(job.status == "interrupted" and job_uses_current_generation_engine(job)
                and not (isinstance(getattr(job, "errors", None), list)
                         and "source_reference_review_required" in job.errors))


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
    before_commit: Callable[[AIJob], Awaitable[None]] | None = None,
) -> tuple[AIJob, dict[str, int | None]]:
    """Durably admit, commit and dispatch one AI job.

    Generation alone receives trial reservation and LLM-budget charging.  The
    regeneration jobs deliberately share queue admission but not those product
    limits.  A failed dispatch is made visible on the durable job and reverses
    the generation charges made by this submission.
    """
    params = dict(params)
    if generation:
        from app.modules.ai.v3.retained_author_replay import AUTHORIZATION_KEY
        params.pop(AUTHORIZATION_KEY, None)
        params["generation_reservation_required"] = bool(reserve_course_generation)
        params["generation_reservation_released"] = False
        params.pop("generation_budget_month", None)
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
    charged_month: str | None = None
    reserved = False
    if generation and reserve_course_generation:
        from app.core.trial_limits import reserve_ai_course_generation

        await reserve_ai_course_generation(db, tenant_id)
        reserved = True
    if generation and tenant_id:
        from app.modules.ai.budget import check_and_charge_llm_budget

        charged_month = datetime.now(UTC).strftime("%Y-%m")
        await check_and_charge_llm_budget(db, str(tenant_id), operation="generate_course", month_key=charged_month)
        cast(Any, job).params = {**dict(job.params or {}), "generation_budget_month": charged_month}
        charged = True

    queue_metadata = await build_ai_job_queue_metadata(
        db,
        job,
        active_limit=active_limit,
        worker_concurrency=worker_concurrency,
        historical_estimate_seconds=historical_estimate_seconds,
    )
    if before_commit is not None:
        # Caller-owned receipt joins the job/charges under the caller's lock.
        # A failure must propagate BEFORE commit and BEFORE remote dispatch.
        await before_commit(job)
    await db.commit()

    try:
        (dispatcher or CeleryAIJobDispatcher()).dispatch(
            task_name,
            task_id=str(job.id),
            kwargs=task_kwargs(job),
        )
    except AIJobDispatchOutcomeUnknownError:
        raise AIJobDispatchOutcomeUnknownError(str(job.id)) from None
    except AIJobSubmissionUnavailableError as exc:
        # Admission committed: transaction-local RLS identity has expired.
        # Bind the original caller before failure state/refund writes.
        from app.core.auth import _set_tenant_security_context, _set_user_security_context

        if tenant_id is not None:
            await _set_tenant_security_context(db, str(tenant_id))
        await _set_user_security_context(db, user_id)
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

            await refund_llm_budget(db, str(tenant_id), "generate_course", month_key=charged_month)
        await db.commit()
        raise

    return job, queue_metadata


async def resume_interrupted_ai_job(
    db: AsyncSession,
    *,
    job: AIJob,
    tenant_id: UUID | str,
    task_kwargs: dict[str, Any],
    active_limit: int,
    worker_concurrency: int,
    historical_estimate_seconds: int,
    dispatcher: AIJobDispatcher | None = None,
    retry_request: Any = None,
    retry_actor_id: UUID | None = None,
) -> tuple[AIJob, dict[str, int | None]]:
    """Requeue the same logical generation without charging quota again."""
    active_limit = _positive_int(active_limit, "active_limit")
    await _lock_tenant_row(db, tenant_id)
    locked = await get_ai_job(
        db,
        str(job.id),
        tenant_id=str(tenant_id),
        for_update=True,
    )
    if locked is None:
        raise AIJobSubmissionUnavailableError("AI job was not found")
    if not job_uses_current_generation_engine(locked):
        raise AIJobSubmissionUnavailableError(RETIRED_GENERATION_ENGINE_MESSAGE)
    from app.modules.ai.v3.retained_author_replay import AUTHORIZATION_KEY, AUTHORIZATION_POLICY, owned_candidate
    candidate = await owned_candidate(db, locked) if may_resume_retained_author(locked) else None
    explicit_candidate = None
    if retry_request is not None:
        from app.core.config import get_settings
        from app.modules.ai.v3.explicit_stage_retry import retry_candidate
        explicit_candidate = await retry_candidate(db, locked, retry_actor_id, get_settings())
        if explicit_candidate is None:
            raise AIJobSubmissionUnavailableError('Unfinished stage retry could not be verified')
    if not is_resumable_generation_job(locked) and candidate is None and explicit_candidate is None:
        raise AIJobSubmissionUnavailableError("AI job is not resumable")
    active_count = await count_active_ai_jobs(db, tenant_id)
    if active_count >= active_limit:
        raise AIJobAdmissionLimitReachedError(
            tenant_id=tenant_id,
            active_count=active_count,
            active_limit=active_limit,
        )

    if explicit_candidate is not None:
        from app.modules.ai.v3.explicit_stage_retry import authorize_retry
        try:
            await authorize_retry(db, locked, retry_actor_id, get_settings(), retry_request)
        except ValueError:
            raise AIJobSubmissionUnavailableError('Unfinished stage retry could not be verified') from None

    previous_result: dict[str, Any] = locked.result if isinstance(locked.result, dict) else {}
    resume_count = int(previous_result.get("resume_count", 0) or 0) + 1
    delivery_task_id = str(uuid.uuid4())
    mutable_locked = cast(Any, locked)
    if candidate is not None:
        mutable_locked.params = {**dict(locked.params or {}), AUTHORIZATION_KEY: {
            "policy": AUTHORIZATION_POLICY, "stage": candidate["stage"], "body_sha256": candidate["body_sha256"],
            "pending_sha256": candidate["pending_sha256"], "delivery_id": delivery_task_id}}
    mutable_locked.status = "pending"
    mutable_locked.stage = "queued"
    mutable_locked.message = "Продолжение генерации поставлено в очередь"
    mutable_locked.errors = None
    mutable_locked.completed_at = None
    mutable_locked.started_at = None
    mutable_locked.result = {
        **previous_result,
        "resume_count": resume_count,
        "delivery_task_id": delivery_task_id,
    }
    mutable_locked.updated_at = datetime.now(UTC)
    await db.flush()
    queue_metadata = await build_ai_job_queue_metadata(
        db,
        locked,
        active_limit=active_limit,
        worker_concurrency=worker_concurrency,
        historical_estimate_seconds=historical_estimate_seconds,
    )
    await db.commit()

    try:
        (dispatcher or CeleryAIJobDispatcher()).dispatch(
            "generate_course",
            task_id=delivery_task_id,
            kwargs=task_kwargs,
        )
    except AIJobDispatchOutcomeUnknownError:
        raise AIJobDispatchOutcomeUnknownError(str(locked.id)) from None
    except AIJobSubmissionUnavailableError:
        await update_ai_job(
            db,
            str(locked.id),
            tenant_id=str(tenant_id),
            status="interrupted",
            stage="interrupted",
            message="Не удалось поставить продолжение в очередь",
        )
        await db.commit()
        raise

    return locked, queue_metadata
