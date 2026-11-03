"""Unwired owner-scoped completed-save recovery; no retries or mutations."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.models.ai_job import AIJob
from app.modules.ai.v3.final_save_completed_reader import read_completed_snapshot


async def recover_completed_save(*, session_factory: Callable[[], Any], tenant_id: UUID,
                                 authenticated_actor_id: UUID, job_id: UUID) -> bool:
    """Read only; caller must obtain tenant and actor from authenticated server context.

    False covers absent, unauthorized, incomplete and uncertain evidence. It is
    never authority to refund, retry, clear a hold or report a definite failure.
    """
    try:
        if not all(isinstance(value, UUID) for value in (tenant_id, authenticated_actor_id, job_id)):
            return False
        async with session_factory() as session:
            return await read_completed_snapshot(session, tenant_id=tenant_id,
                                                 actor_id=authenticated_actor_id, job_id=job_id) is True
    except Exception:
        return False


async def recover_completed_course_id(*, session_factory: Callable[[], Any], tenant_id: UUID,
                                      authenticated_actor_id: UUID, job_id: UUID) -> UUID | None:
    """Return the owned course ID only after verified readback under the same locks."""
    try:
        if not all(isinstance(value, UUID) for value in (tenant_id, authenticated_actor_id, job_id)):
            return None
        async with session_factory() as session:
            if await read_completed_snapshot(session, tenant_id=tenant_id,
                    actor_id=authenticated_actor_id, job_id=job_id) is not True:
                return None
            job = await session.scalar(select(AIJob).where(AIJob.id == str(job_id), AIJob.tenant_id == tenant_id,
                AIJob.user_id == authenticated_actor_id, AIJob.status == "completed").with_for_update())
            return job.course_id if job is not None and isinstance(job.course_id, UUID) else None
    except Exception:
        return None
