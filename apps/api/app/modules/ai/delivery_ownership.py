"""Transaction-bound generation delivery ownership checks."""

from contextvars import ContextVar
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_job import AIJob

delivery_id: ContextVar[str | None] = ContextVar[str | None]("generation_delivery_id", default=None)


class DeliveryOwnershipLostError(RuntimeError):
    """The current delivery no longer owns the durable job."""


async def lock_owned_delivery(
    session: AsyncSession, job_id: str, tenant_id: str, *, require_running: bool = False,
    allowed_statuses: frozenset[str] | None = None,
) -> None:
    """Lock and verify ownership in the same transaction as the subsequent write."""
    current = delivery_id.get()
    if current is None:
        return
    job = await session.scalar(
        select(AIJob).where(AIJob.id == job_id, AIJob.tenant_id == tenant_id).with_for_update()
    )
    if job is None:
        raise DeliveryOwnershipLostError("generation_delivery_ownership_lost")
    if require_running and job.status != "running":
        raise DeliveryOwnershipLostError("generation_delivery_ownership_lost")
    if allowed_statuses is not None and job.status not in allowed_statuses:
        raise DeliveryOwnershipLostError("generation_delivery_ownership_lost")
    result: dict[str, Any] = job.result if isinstance(job.result, dict) else {}
    stored = result.get("delivery_task_id")
    count = result.get("resume_count")
    legacy = stored is None and (count is None or count == 0) and current == job_id
    if stored != current and not legacy:
        raise DeliveryOwnershipLostError("generation_delivery_ownership_lost")
