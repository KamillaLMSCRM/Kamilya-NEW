"""PostgreSQL concurrency coverage for tenant-fair AI job admission."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.models.ai_job import AIJob
from app.models.tenants import Tenant
from app.models.users import User
from app.modules.ai.job_service import (
    AIJobAdmissionLimitReachedError,
    create_admitted_ai_job,
)

pytestmark = pytest.mark.asyncio

ACTIVE_LIMIT = 2
PARALLEL_ATTEMPTS = 8


async def _set_tenant_context(session, tenant_id) -> None:
    """Set the RLS tenant context on every runtime database session."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


async def _delete_test_data(tenant_ids: tuple) -> None:
    """Remove only rows created by this test, under each tenant's RLS context."""
    from app.core.db import async_session_factory

    async with async_session_factory() as cleanup:
        for tenant_id in tenant_ids:
            await _set_tenant_context(cleanup, tenant_id)
            await cleanup.execute(
                text("DELETE FROM ai_jobs WHERE tenant_id = :tenant_id"),
                {"tenant_id": str(tenant_id)},
            )
            await cleanup.execute(
                text("DELETE FROM users WHERE tenant_id = :tenant_id"),
                {"tenant_id": str(tenant_id)},
            )
            await cleanup.execute(
                text("DELETE FROM tenants WHERE id = :tenant_id"),
                {"tenant_id": str(tenant_id)},
            )
        await cleanup.commit()


async def _create_test_tenant_with_user(tenant_id) -> User:
    from app.core.db import async_session_factory

    async with async_session_factory() as setup:
        setup.add(
            Tenant(
                id=tenant_id,
                name=f"AI admission test {tenant_id.hex[:8]}",
                slug=f"ai-admission-{tenant_id.hex}",
                status="trial",
                plan="trial",
                settings={},
            )
        )
        await setup.commit()

    async with async_session_factory() as setup:
        await _set_tenant_context(setup, tenant_id)
        user = User(
            id=uuid4(),
            tenant_id=tenant_id,
            email=f"ai-admission-{tenant_id.hex}@example.test",
            first_name="Admission",
            last_name="Test",
            role="methodologist",
            is_active=True,
        )
        setup.add(user)
        await setup.commit()
        return user


async def _admit_once(tenant_id, user_id) -> str | AIJobAdmissionLimitReachedError:
    from app.core.db import async_session_factory

    async with async_session_factory() as session:
        await _set_tenant_context(session, tenant_id)
        try:
            job = await create_admitted_ai_job(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                params={"action": "generate_course", "source": "integration-test"},
                active_limit=ACTIVE_LIMIT,
            )
            await session.commit()
            return job.id
        except AIJobAdmissionLimitReachedError as exc:
            await session.rollback()
            return exc


async def _count_jobs(tenant_id, statuses: set[str]) -> int:
    from app.core.db import async_session_factory

    async with async_session_factory() as check:
        await _set_tenant_context(check, tenant_id)
        result = await check.execute(
            select(func.count(AIJob.id)).where(
                AIJob.tenant_id == tenant_id,
                AIJob.status.in_(statuses),
            )
        )
        return int(result.scalar_one())


async def test_parallel_admission_is_tenant_scoped_and_ignores_terminal_jobs():
    """Eight concurrent attempts yield two committed slots per tenant.

    Each tenant receives an independent eight-request contention wave.
    Completed jobs are terminal and must not consume either tenant's two
    active slots.
    """
    from app.core.db import async_session_factory

    tenant_a_id = uuid4()
    tenant_b_id = uuid4()
    tenant_ids = (tenant_a_id, tenant_b_id)
    user_a = None
    user_b = None
    try:
        user_a = await _create_test_tenant_with_user(tenant_a_id)
        user_b = await _create_test_tenant_with_user(tenant_b_id)

        async with async_session_factory() as seed:
            await _set_tenant_context(seed, tenant_a_id)
            seed.add(
                AIJob(
                    id=f"terminal-{tenant_a_id.hex}",
                    tenant_id=tenant_a_id,
                    user_id=user_a.id,
                    status="completed",
                    stage="completed",
                    progress=100,
                    message="already complete",
                    created_at=datetime.now(UTC),
                    completed_at=datetime.now(UTC),
                )
            )
            await seed.commit()

        # Run one eight-request contention wave per tenant. Keeping the waves
        # separate stays below the Supabase session-pool cap while still
        # proving the row lock under eight simultaneous requests.
        results_a = await asyncio.gather(
            *(
                _admit_once(tenant_a_id, user_a.id)
                for _ in range(PARALLEL_ATTEMPTS)
            )
        )
        results_b = await asyncio.gather(
            *(
                _admit_once(tenant_b_id, user_b.id)
                for _ in range(PARALLEL_ATTEMPTS)
            )
        )
        successes_a = [result for result in results_a if isinstance(result, str)]
        successes_b = [result for result in results_b if isinstance(result, str)]
        failures_a = [
            result for result in results_a if isinstance(result, AIJobAdmissionLimitReachedError)
        ]
        failures_b = [
            result for result in results_b if isinstance(result, AIJobAdmissionLimitReachedError)
        ]

        assert len(successes_a) == ACTIVE_LIMIT
        assert len(successes_b) == ACTIVE_LIMIT
        assert len(failures_a) == PARALLEL_ATTEMPTS - ACTIVE_LIMIT
        assert len(failures_b) == PARALLEL_ATTEMPTS - ACTIVE_LIMIT
        assert len(set(successes_a)) == ACTIVE_LIMIT
        assert len(set(successes_b)) == ACTIVE_LIMIT
        assert all(error.active_count == ACTIVE_LIMIT for error in failures_a + failures_b)
        assert all(error.active_limit == ACTIVE_LIMIT for error in failures_a + failures_b)

        assert await _count_jobs(tenant_a_id, {"pending", "running"}) == ACTIVE_LIMIT
        assert await _count_jobs(tenant_b_id, {"pending", "running"}) == ACTIVE_LIMIT
        assert await _count_jobs(tenant_a_id, {"completed"}) == 1
    finally:
        await _delete_test_data(tenant_ids)
