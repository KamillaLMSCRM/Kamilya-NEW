from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.ai.delivery_ownership import DeliveryOwnershipLostError, delivery_id, lock_owned_delivery


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current", "result", "allowed"),
    [
        ("job", {}, True),
        ("old", {}, False),
        ("job", {"resume_count": 1}, False),
        ("new", {"resume_count": 1, "delivery_task_id": "new"}, True),
        ("old", {"resume_count": 1, "delivery_task_id": "new"}, False),
    ],
)
async def test_locked_delivery_identity(current, result, allowed):
    session = AsyncMock()
    session.scalar.return_value = SimpleNamespace(result=result)
    token = delivery_id.set(current)
    try:
        if allowed:
            await lock_owned_delivery(session, "job", "tenant")
        else:
            with pytest.raises(DeliveryOwnershipLostError):
                await lock_owned_delivery(session, "job", "tenant")
        assert session.scalar.await_count == 1
        assert session.scalar.await_args.args[0]._for_update_arg is not None
    finally:
        delivery_id.reset(token)


@pytest.mark.asyncio
async def test_nonworker_compatibility_does_not_lock():
    session = AsyncMock()
    await lock_owned_delivery(session, "job", "tenant")
    session.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_running_guard_rejects_cancelled_same_delivery():
    session = AsyncMock()
    session.scalar.return_value = SimpleNamespace(status="cancelled", result={"delivery_task_id": "delivery"})
    token = delivery_id.set("delivery")
    try:
        with pytest.raises(DeliveryOwnershipLostError):
            await lock_owned_delivery(session, "job", "tenant", require_running=True)
    finally:
        delivery_id.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "allowed"), [("failed", True), ("cancelled", True), ("running", False), ("interrupted", False)])
async def test_refund_requires_terminal_status(status, allowed):
    session = AsyncMock()
    session.scalar.return_value = SimpleNamespace(status=status, result={"delivery_task_id": "delivery"})
    token = delivery_id.set("delivery")
    try:
        if allowed:
            await lock_owned_delivery(session, "job", "tenant", allowed_statuses=frozenset({"failed", "cancelled"}))
        else:
            with pytest.raises(DeliveryOwnershipLostError):
                await lock_owned_delivery(session, "job", "tenant", allowed_statuses=frozenset({"failed", "cancelled"}))
    finally:
        delivery_id.reset(token)


@pytest.mark.asyncio
async def test_pipeline_refund_locks_tenant_before_job_and_release(monkeypatch):
    from app.modules.ai import job_service, pipeline

    events = []
    session = AsyncMock()
    manager = AsyncMock()
    manager.__aenter__.return_value = session
    monkeypatch.setattr(pipeline, "async_session_factory", lambda: manager)

    async def tenant_lock(*args):
        events.append("tenant")

    async def owned_lock(*args, **kwargs):
        events.append("job")
        assert kwargs["allowed_statuses"] == frozenset({"failed", "cancelled"})

    async def release(*args, **kwargs):
        events.append("release")
        return True

    monkeypatch.setattr(job_service, "_lock_tenant_row", tenant_lock)
    monkeypatch.setattr(pipeline, "lock_owned_delivery", owned_lock)
    monkeypatch.setattr(job_service, "release_generation_reservation_once", release)
    assert await pipeline._release_generation_reservation("job", "tenant") is True
    assert events == ["tenant", "job", "release"]
    session.commit.assert_awaited_once()


def test_real_async_bridge_preserves_context_and_thread_isolation(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.core import db
    from app.modules.ai.tasks import _run_async

    monkeypatch.setattr(db, "engine", SimpleNamespace(dispose=AsyncMock()))
    barrier = Barrier(2)

    def run(value):
        token = delivery_id.set(value)
        try:
            barrier.wait(timeout=5)

            async def read():
                return delivery_id.get()

            return _run_async(read())
        finally:
            delivery_id.reset(token)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(run, "first")
        second = executor.submit(run, "second")
        assert first.result(timeout=10) == "first"
        assert second.result(timeout=10) == "second"
    assert delivery_id.get() is None
