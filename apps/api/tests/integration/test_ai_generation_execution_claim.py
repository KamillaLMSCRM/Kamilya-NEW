"""PostgreSQL/RLS contracts for durable generation delivery claims."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete, text

from app.core.db import async_session_factory
from app.models.ai_job import AIJob
from app.models.tenants import Tenant
from app.models.users import User
from app.modules.ai.generation_engine import CURRENT_GENERATION_ENGINE
from app.modules.ai.job_service import claim_generation_execution


@pytest.mark.asyncio
async def test_generation_claim_is_single_winner_and_cross_tenant_is_denied():
    """Requires the PostgreSQL test database; SQLite cannot verify FORCE RLS."""
    tenant_a = Tenant(id=uuid4(), name="Claim tenant A", slug=f"claim-a-{uuid4().hex}")
    tenant_b = Tenant(id=uuid4(), name="Claim tenant B", slug=f"claim-b-{uuid4().hex}")
    user_a = User(
        id=uuid4(),
        tenant_id=tenant_a.id,
        email=f"claim-{uuid4().hex}@example.test",
        first_name="Claim",
        last_name="Worker",
        role="methodologist",
    )
    job = AIJob(
        id=f"claim-{uuid4()}",
        tenant_id=tenant_a.id,
        user_id=user_a.id,
        status="pending",
        stage="queued",
        params={"source_analysis": {"generation_engine": CURRENT_GENERATION_ENGINE}},
    )
    try:
        async with async_session_factory() as seed:
            seed.add_all([tenant_a, tenant_b])
            await seed.commit()
            await seed.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_a.id)})
            seed.add_all([user_a, job])
            await seed.commit()

        async def claim_in_independent_session(tenant_id: str) -> bool:
            async with async_session_factory() as session:
                # Exercise the same NOINHERIT/NOBYPASSRLS role used by workers,
                # not the migration owner that seeded the fixtures.
                await session.execute(text("SET LOCAL ROLE lms_app"))
                return await claim_generation_execution(session, job.id, tenant_id)

        first, second = await asyncio.gather(
            claim_in_independent_session(str(tenant_a.id)),
            claim_in_independent_session(str(tenant_a.id)),
        )
        assert sorted((first, second)) == [False, True]
        assert await claim_in_independent_session(str(tenant_b.id)) is False
    finally:
        async with async_session_factory() as cleanup:
            await cleanup.execute(delete(AIJob).where(AIJob.id == job.id))
            await cleanup.execute(delete(User).where(User.id == user_a.id))
            await cleanup.execute(delete(Tenant).where(Tenant.id.in_([tenant_a.id, tenant_b.id])))
            await cleanup.commit()


@pytest.mark.asyncio
async def test_generation_claim_rejects_job_without_current_engine_marker():
    """Retired jobs must never enter the sole supported generation engine."""
    tenant = Tenant(id=uuid4(), name="Retired claim tenant", slug=f"retired-claim-{uuid4().hex}")
    user = User(
        id=uuid4(),
        tenant_id=tenant.id,
        email=f"retired-claim-{uuid4().hex}@example.test",
        first_name="Retired",
        last_name="Worker",
        role="methodologist",
    )
    job = AIJob(
        id=f"retired-claim-{uuid4()}",
        tenant_id=tenant.id,
        user_id=user.id,
        status="pending",
        stage="queued",
        params={},
    )
    try:
        async with async_session_factory() as seed:
            seed.add(tenant)
            await seed.commit()
            await seed.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant.id)})
            seed.add_all([user, job])
            await seed.commit()

        async with async_session_factory() as session:
            await session.execute(text("SET LOCAL ROLE lms_app"))
            assert await claim_generation_execution(session, job.id, str(tenant.id)) is False
    finally:
        async with async_session_factory() as cleanup:
            await cleanup.execute(delete(AIJob).where(AIJob.id == job.id))
            await cleanup.execute(delete(User).where(User.id == user.id))
            await cleanup.execute(delete(Tenant).where(Tenant.id == tenant.id))
            await cleanup.commit()
