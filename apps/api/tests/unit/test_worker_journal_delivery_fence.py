"""Worker journal write ownership must be locked inside the write transaction."""
from types import SimpleNamespace

import pytest

from app.modules.ai import delivery_ownership
from app.modules.ai.worker_lesson_cycle import WorkerCycleJournal


class Session:
    def __init__(self):
        self.events = []

    async def __aenter__(self):
        self.events.append("begin")
        return self

    async def __aexit__(self, typ, value, tb):
        self.events.append("rollback" if typ else "exit")

    async def commit(self):
        self.events.append("commit")


class Repo:
    async def _set_tenant(self, session, tenant):
        session.events.append("tenant")

    async def create_plan(self, session, **kwargs):
        session.events.append("plan")

    async def load_checkpoints(self, session, **kwargs):
        session.events.append("read")
        return [SimpleNamespace(assessment_payload=None)]

    async def checkpoint_content(self, session, **kwargs):
        session.events.append("content")

    async def checkpoint_review(self, session, **kwargs):
        session.events.append("review")

    async def checkpoint_assessment(self, session, **kwargs):
        session.events.append("assessment")


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["prepare", "save_value", "append_inventory_version"])
async def test_journal_writes_require_fence_in_same_transaction(monkeypatch, method):
    session = Session()
    journal = WorkerCycleJournal("tenant", "job", lambda: session)
    journal.repository = Repo()

    async def lock(s, job, tenant, *, require_running=False):
        assert s is session and (job, tenant) == ("job", "tenant") and require_running is True
        s.events.append("lock")

    monkeypatch.setattr(delivery_ownership, "lock_owned_delivery", lock)
    token = delivery_ownership.delivery_id.set("delivery")
    try:
        if method == "prepare":
            await journal.prepare("key", {})
        elif method == "save_value":
            await journal.save_value("key", {})
        else:
            await journal.append_inventory_version("key", {}, {})
    finally:
        delivery_ownership.delivery_id.reset(token)
    assert session.events[:3] == ["begin", "tenant", "lock"]
    assert session.events[-2:] == ["commit", "exit"]


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["prepare", "save_value", "append_inventory_version"])
@pytest.mark.parametrize("missing", [True, False])
async def test_missing_or_stale_delivery_never_writes(monkeypatch, method, missing):
    session = Session()
    journal = WorkerCycleJournal("tenant", "job", lambda: session)
    journal.repository = Repo()

    async def stale(*args, **kwargs):
        raise delivery_ownership.DeliveryOwnershipLostError("stale")

    monkeypatch.setattr(delivery_ownership, "lock_owned_delivery", stale)
    token = delivery_ownership.delivery_id.set(None if missing else "stale")
    try:
        with pytest.raises(delivery_ownership.DeliveryOwnershipLostError):
            if method == "prepare":
                await journal.prepare("key", {})
            elif method == "save_value":
                await journal.save_value("key", {})
            else:
                await journal.append_inventory_version("key", {}, {})
    finally:
        delivery_ownership.delivery_id.reset(token)
    assert not set(session.events) & {"plan", "content", "review", "assessment", "commit"}
    assert session.events[-1] == "rollback"

@pytest.mark.asyncio
@pytest.mark.parametrize("delivery,status,accepted", [("current", "running", True), ("old", "running", False), ("current", "interrupted", False)])
async def test_real_ownership_helper_fences_journal_write(delivery, status, accepted):
    session = Session()
    journal = WorkerCycleJournal("tenant", "job", lambda: session)
    journal.repository = Repo()

    async def scalar(_statement):
        session.events.append("real_lock")
        return SimpleNamespace(status=status, result={"delivery_task_id": "current", "resume_count": 1})

    session.scalar = scalar
    token = delivery_ownership.delivery_id.set(delivery)
    try:
        if accepted:
            await journal.save_value("key", {})
        else:
            with pytest.raises(delivery_ownership.DeliveryOwnershipLostError):
                await journal.save_value("key", {})
    finally:
        delivery_ownership.delivery_id.reset(token)
    assert session.events[:3] == ["begin", "tenant", "real_lock"]
    assert ("commit" in session.events) is accepted
    assert ("assessment" in session.events) is accepted
