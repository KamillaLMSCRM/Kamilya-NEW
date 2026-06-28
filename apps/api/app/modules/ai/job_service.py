"""AI Job service — DB-backed job state management."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_job import AIJob


async def create_ai_job(
    db: AsyncSession,
    tenant_id,
    user_id,
    course_id=None,
    params: dict | None = None,
) -> AIJob:
    """Create a new AI job record."""
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
        created_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.flush()
    return job


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
    for k, v in kwargs.items():
        setattr(job, k, v)
    job.updated_at = datetime.now(timezone.utc)
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
