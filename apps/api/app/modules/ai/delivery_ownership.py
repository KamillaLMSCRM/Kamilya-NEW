"""Transaction-bound generation delivery ownership checks."""

from contextvars import ContextVar
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_job import AIJob

delivery_id: ContextVar[str | None] = ContextVar[str | None]("generation_delivery_id", default=None)


class DeliveryOwnershipLostError(RuntimeError):
    """The current delivery no longer owns the durable job."""


def matches_generation_delivery(job_id: str, result: Any, current: str) -> bool:
    """Use the same initial/resumed identity at execution, save and readback."""
    if (not isinstance(job_id, str) or not job_id or not isinstance(current, str) or not current
            or result is not None and not isinstance(result, dict)):
        return False
    values = result or {}
    count = values.get('resume_count')
    if count is not None and (type(count) is not int or count < 0):
        return False
    stored = values.get('delivery_task_id')
    if stored is not None:
        return isinstance(stored, str) and bool(stored) and stored == current
    return (count is None or count == 0) and current == job_id


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
    if not matches_generation_delivery(job_id, job.result, current):
        raise DeliveryOwnershipLostError("generation_delivery_ownership_lost")
