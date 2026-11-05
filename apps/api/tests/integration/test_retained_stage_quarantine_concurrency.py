"""Real PostgreSQL/RLS row locks, repeated stop and concurrent state changes."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.models.ai_job import AIJob
from app.modules.ai.job_service import is_quarantined_generation, quarantine_generation
from tests.integration.test_ai_job_admission_concurrency import (
    _create_test_tenant_with_user,
    _delete_test_data,
    _set_tenant_context,
)

pytestmark = pytest.mark.asyncio


async def _runtime_context(session, tenant, actor):
    await session.execute(text("SET LOCAL ROLE lms_app"))
    await _set_tenant_context(session, tenant)
    await session.execute(text("SELECT set_config('app.user_id', :actor, true)"), {"actor": str(actor)})
    role = (await session.execute(text(
        "SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"))).one()
    assert tuple(role) == ("lms_app", False, False)


async def _seed_job(tenant, actor):
    from app.core.db import async_session_factory
    observed = datetime(2026, 11, 4, 16, 0, tzinfo=UTC)
    params = {"documents": [str(uuid4())], "generation_reservation_required": True,
        "received_rejected_usage": {"input_tokens": 74010, "output_tokens": 9612}}
    result = {"v3_pending_stages": {"policy": "v3-pending-stages-v1", "entries": {
        "a" * 64: {"claim_key": "claim", "result_key": "result", "token": "b" * 32}}}}
    job_id = f"retained-stop-{uuid4()}"
    async with async_session_factory() as session:
        await _set_tenant_context(session, tenant)
        session.add(AIJob(id=job_id, tenant_id=tenant, user_id=actor, status="interrupted", stage="interrupted",
            updated_at=observed, params=params, result=result))
        await session.commit()
    return job_id, observed, params, result


async def test_parallel_stop_is_idempotent_and_cross_tenant_or_actor_cannot_touch_history():
    from app.core.db import async_session_factory
    tenant_a, tenant_b = uuid4(), uuid4()
    try:
        actor_a = await _create_test_tenant_with_user(tenant_a)
        actor_b = await _create_test_tenant_with_user(tenant_b)
        job_id, observed, params, result = await _seed_job(tenant_a, actor_a.id)

        async def stop(tenant, actor):
            async with async_session_factory() as session:
                await _runtime_context(session, tenant, actor)
                return await quarantine_generation(session, job_id=job_id, tenant_id=tenant,
                    user_id=actor, expected_updated_at=observed)

        assert await stop(tenant_b, actor_b.id) == "not_found"
        assert await stop(tenant_a, actor_b.id) == "not_found"
        assert await asyncio.gather(stop(tenant_a, actor_a.id), stop(tenant_a, actor_a.id)) == [
            "quarantined", "quarantined"]
        async with async_session_factory() as session:
            await _runtime_context(session, tenant_a, actor_a.id)
            row = await session.get(AIJob, job_id)
            assert row is not None and is_quarantined_generation(row)
            assert row.result == result
            assert {k: v for k, v in row.params.items() if k != "generation_quarantine"} == params
            assert row.params["generation_quarantine"]["observed_updated_at"] == observed.isoformat()
            assert row.params.get("generation_reservation_released") is None
            assert "provider_outcome" not in row.params["generation_quarantine"]
    finally:
        await _delete_test_data((tenant_a, tenant_b))


async def test_concurrent_change_wins_row_lock_and_stale_stop_cannot_overwrite_it():
    from app.core.db import async_session_factory
    tenant = uuid4()
    try:
        actor = await _create_test_tenant_with_user(tenant)
        job_id, observed, params, original_result = await _seed_job(tenant, actor.id)
        locked, identified, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()
        backend_ids = {}
        changed_params = {**deepcopy(params), "concurrent_review": "preserve-this-revision"}

        async def edit():
            async with async_session_factory() as session:
                await _runtime_context(session, tenant, actor.id)
                row = (await session.execute(select(AIJob).where(AIJob.id == job_id,
                    AIJob.tenant_id == tenant).with_for_update())).scalar_one()
                backend_ids["editor"] = (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()
                locked.set()
                await asyncio.wait_for(finish.wait(), timeout=30)
                row.params = changed_params
                row.updated_at = observed + timedelta(seconds=1)
                await session.commit()

        async def stop():
            await asyncio.wait_for(locked.wait(), timeout=10)
            async with async_session_factory() as session:
                await _runtime_context(session, tenant, actor.id)
                backend_ids["stop"] = (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()
                identified.set()
                return await quarantine_generation(session, job_id=job_id, tenant_id=tenant,
                    user_id=actor.id, expected_updated_at=observed)

        editing = asyncio.create_task(edit())
        stopping = asyncio.create_task(stop())
        try:
            await asyncio.wait_for(identified.wait(), timeout=10)
            # Observe the real PostgreSQL blocker, not just task scheduling. If
            # the stop drops FOR UPDATE this assertion cannot pass on stale CAS.
            deadline = asyncio.get_running_loop().time() + 10
            async with async_session_factory() as observer:
                while True:
                    blocked_by = (await observer.execute(text("SELECT pg_blocking_pids(:pid)"),
                        {"pid": backend_ids["stop"]})).scalar_one()
                    if backend_ids["editor"] in blocked_by:
                        break
                    assert not stopping.done(), "stop did not wait for the held source row"
                    assert asyncio.get_running_loop().time() < deadline, "PostgreSQL row contention not observed"
                    await asyncio.sleep(0.02)
                assert not stopping.done()
        finally:
            finish.set()
            outcome = await asyncio.wait_for(asyncio.gather(editing, stopping), timeout=40)
        assert outcome == [None, "conflict"]
        async with async_session_factory() as session:
            await _runtime_context(session, tenant, actor.id)
            row = await session.get(AIJob, job_id)
            assert row is not None and row.status == "interrupted" and row.stage == "interrupted"
            assert row.params == changed_params and row.result == original_result
    finally:
        await _delete_test_data((tenant,))
