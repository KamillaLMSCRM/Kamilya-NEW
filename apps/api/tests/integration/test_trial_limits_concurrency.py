"""PostgreSQL concurrency regressions for trial generation reservations."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.models.users import User  # noqa: F401

# Register both sides of Course.modules before SQLAlchemy configures mappers.
from app.modules.courses.models import Course  # noqa: F401
from app.modules.lessons.models import Module  # noqa: F401


async def _set_tenant_context(session, tenant_id):
    from sqlalchemy import text

    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


async def _delete_test_tenant(tenant_id):
    from sqlalchemy import text

    from app.core.db import async_session_factory

    async with async_session_factory() as cleanup:
        await _set_tenant_context(cleanup, tenant_id)
        for table in ("courses", "users", "tenant_usage"):
            await cleanup.execute(text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        await cleanup.execute(text("DELETE FROM tenants WHERE id = :tenant_id"), {"tenant_id": tenant_id})
        await cleanup.commit()


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
            await _set_tenant_context(session, tenant_id)
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
            await _set_tenant_context(check, tenant_id)
            usage = await check.get(TenantUsage, tenant_id)
            assert usage is not None
            assert usage.ai_course_generations_used == 1
    finally:
        await _delete_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_parallel_course_creates_do_not_exceed_last_trial_slot():
    """The course guard serializes the check and the following insert."""
    from app.core.db import async_session_factory
    from app.core.trial_limits import TrialLimitExceeded, assert_can_create_courses
    from app.models.tenants import Tenant

    tenant_id = uuid4()
    async with async_session_factory() as setup:
        setup.add(
            Tenant(
                id=tenant_id,
                name="Course concurrency test",
                slug=f"course-concurrency-{tenant_id.hex[:12]}",
                status="trial",
                plan="trial",
                trial_ends_at=datetime.now(UTC) + timedelta(days=1),
                max_courses_per_month=1,
                settings={},
            )
        )
        await setup.commit()

    async def attempt() -> bool:
        async with async_session_factory() as session:
            await _set_tenant_context(session, tenant_id)
            try:
                await assert_can_create_courses(session, tenant_id)
                session.add(Course(tenant_id=tenant_id, title=f"Course {uuid4()}"))
                await session.commit()
                return True
            except TrialLimitExceeded:
                await session.rollback()
                return False

    try:
        results = await asyncio.gather(*(attempt() for _ in range(8)))
        assert sum(results) == 1
    finally:
        await _delete_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_parallel_learner_creates_do_not_exceed_last_trial_slot():
    """The learner guard serializes the count and the following user insert."""
    from app.core.db import async_session_factory
    from app.core.trial_limits import TrialLimitExceeded, assert_can_create_learners
    from app.models.tenants import Tenant

    tenant_id = uuid4()
    async with async_session_factory() as setup:
        setup.add(
            Tenant(
                id=tenant_id,
                name="Learner concurrency test",
                slug=f"learner-concurrency-{tenant_id.hex[:12]}",
                status="trial",
                plan="trial",
                trial_ends_at=datetime.now(UTC) + timedelta(days=1),
                settings={"trial_limits": {"max_students": 1}},
            )
        )
        await setup.commit()

    async def attempt() -> bool:
        async with async_session_factory() as session:
            await _set_tenant_context(session, tenant_id)
            try:
                await assert_can_create_learners(session, tenant_id)
                session.add(
                    User(
                        tenant_id=tenant_id,
                        email=f"learner-{uuid4()}@example.test",
                        first_name="Trial",
                        last_name="Learner",
                        role="student",
                        is_active=True,
                    )
                )
                await session.commit()
                return True
            except TrialLimitExceeded:
                await session.rollback()
                return False

    try:
        results = await asyncio.gather(*(attempt() for _ in range(8)))
        assert sum(results) == 1
    finally:
        await _delete_test_tenant(tenant_id)
