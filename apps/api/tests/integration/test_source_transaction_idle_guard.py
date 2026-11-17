"""Native PG timeout/lease behavior, without any business table or model call."""
import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool


@pytest.mark.asyncio
async def test_source_idle_guard_releases_an_abandoned_lease_and_does_not_change_global_settings():
    from app.modules.source_editorial_review.service import guard_source_transaction

    engine = create_async_engine(os.environ['DATABASE_URL'], poolclass=NullPool, hide_parameters=True)
    key = int.from_bytes(uuid4().bytes[:4], 'big', signed=True)
    params = {'namespace': -117081, 'key': key}
    lease = text('SELECT pg_try_advisory_xact_lock(:namespace,:key)')
    setting = text("SELECT setting::int FROM pg_settings WHERE name='idle_in_transaction_session_timeout'")
    try:
        async with AsyncSession(engine) as healthy:
            original = await healthy.scalar(setting)
            await guard_source_transaction(healthy)
            assert await healthy.scalar(setting) == 60_000
            await healthy.commit()
            assert await healthy.scalar(setting) == original
            await healthy.rollback()
        async with AsyncSession(engine) as abandoned, AsyncSession(engine) as waiting:
            try:
                await guard_source_transaction(abandoned)
                assert await abandoned.scalar(setting) == 60_000
                # Establish both physical sessions before arming the short fixture.
                await waiting.scalar(text('SELECT 1'))
                await abandoned.execute(text("SET LOCAL idle_in_transaction_session_timeout = '3s'"))
                assert await abandoned.scalar(lease, params) is True
                assert await waiting.scalar(lease, params) is False
                await asyncio.sleep(3.5)
                assert await waiting.scalar(lease, params) is True
                await waiting.rollback()
            finally:
                # The server deliberately killed this session. Do not let a
                # rollback on its dead socket mask the lease-release assertion.
                await abandoned.invalidate()
        async with AsyncSession(engine) as after:
            assert await after.scalar(setting) == original
            assert await after.scalar(lease, params) is True
            await after.rollback()
    finally:
        await engine.dispose()
