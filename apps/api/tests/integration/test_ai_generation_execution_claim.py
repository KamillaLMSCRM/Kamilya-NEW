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
    job = AIJob(id=f"claim-{uuid4()}", tenant_id=tenant_a.id, user_id=user_a.id, status="pending", stage="queued")
    try:
        async with async_session_factory() as seed:
            seed.add_all([tenant_a, tenant_b])
            await seed.commit()
            await seed.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_a.id)})
            seed.add_all([user_a, job])
            await seed.commit()

        async def claim_in_independent_session(tenant_id: str) -> bool:
            async with async_session_factory() as session:
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
