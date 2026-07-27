"""PostgreSQL concurrency regressions for trial generation reservations."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_parallel_ai_reservations_do_not_exceed_trial_limit():
    """Only one of several committed transactions may reserve a one-shot limit."""
    from app.core.db import async_session_factory
    from app.core.trial_limits import TrialLimitExceeded, reserve_ai_course_generation
    from app.models.tenants import Tenant, TenantUsage

    tenant_id = uuid4()
    slug = f"concurrency-{tenant_id.hex[:12]}"
    async with async_session_factory() as setup:
        setup.add(
            Tenant(
                id=tenant_id,
                name="Trial concurrency test",
                slug=slug,
                status="trial",
                plan="trial",
                trial_ends_at=datetime.now(UTC) + timedelta(days=1),
                settings={"trial_limits": {"ai_course_generations_limit": 1}},
            )
        )
        await setup.commit()

    async def attempt() -> bool:
        async with async_session_factory() as session:
            try:
                await reserve_ai_course_generation(session, tenant_id)
                await session.commit()
                return True
            except TrialLimitExceeded:
                await session.rollback()
                return False

    try:
        results = await asyncio.gather(*(attempt() for _ in range(8)))
        assert sum(results) == 1

        async with async_session_factory() as check:
            usage = await check.get(TenantUsage, tenant_id)
            assert usage is not None
            assert usage.ai_course_generations_used == 1
    finally:
        async with async_session_factory() as cleanup:
            tenant = await cleanup.get(Tenant, tenant_id)
            if tenant is not None:
                await cleanup.delete(tenant)
                await cleanup.commit()
