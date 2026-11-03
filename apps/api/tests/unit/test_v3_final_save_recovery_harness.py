"""Synthetic transactional model; not evidence of actual PostgreSQL behavior."""
import asyncio
import socket
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest

from app.modules.ai.lesson_cycle import POLICY_VERSION
from app.modules.ai.source_assessment_plan import PLAN_POLICY
from app.modules.ai.v3.final_save_completed_reader import completed_receipt
from app.modules.ai.v3.final_save_contract import INTENT_KEY, RECEIPT_KEY, install_intent, resolve_intent
from app.modules.ai.v3.final_save_recovery import recover_completed_course_id, recover_completed_save
from app.modules.ai.v3.final_save_snapshot import make_snapshot
from app.modules.ai.v3.pending_stage_transactions import has_pending
from tests.unit.test_v3_final_save_completed_reader import Session
from tests.unit.test_v3_final_save_readback import fixture


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(httpx, "Client", deny)
    monkeypatch.setattr(httpx, "AsyncClient", deny)


class Harness:
    def __init__(self, monkeypatch):
        from app.modules.ai.v3 import final_save_completed_reader as reader
        self.data = fixture()
        self.intent = self.data["intent"]
        self.snapshot = make_snapshot(self.data["state"], self.intent)
        self.job = self.data["job"]
        self.original_result = {"delivery_task_id": self.intent["delivery_id"]}
        self.job.result = deepcopy(self.original_result)
        self.checkpoint = None
        self.saved = False
        async def source(*_args, **_kwargs):
            return self.data["source_corpus"]
        monkeypatch.setattr(reader, "build_direct_source_corpus", source)

    def prepare(self, mode="ok"):
        # Model one atomic owned transaction: no durable writes before commit.
        next_result = install_intent(self.job.result, self.intent)
        if mode == "rollback":
            raise RuntimeError("rollback")
        if mode == "cancel":
            raise asyncio.CancelledError()
        self.job.result, self.checkpoint = next_result, deepcopy(self.snapshot)
        if mode == "lost_ack":
            raise TimeoutError("unknown")

    def save(self, mode="ok"):
        assert self.checkpoint == self.snapshot and self.job.result[INTENT_KEY] == self.intent
        next_result = resolve_intent(self.job.result, self.intent, course_id=str(self.data["course"].id),
                                     output_digest=self.intent["output_digest"])
        next_result[RECEIPT_KEY] = completed_receipt(self.intent, self.checkpoint, str(self.data["course"].id))
        if mode == "rollback":
            raise RuntimeError("rollback")
        if mode == "cancel":
            raise asyncio.CancelledError()
        self.job.result, self.saved = next_result, True
        if mode == "lost_ack":
            raise TimeoutError("unknown")

    def recovery_session(self, *, foreign=False):
        run = SimpleNamespace(id=uuid4(), plan_revision=f"{PLAN_POLICY}/{POLICY_VERSION}",
            plan_payload={"schema": "v3-final-snapshot-v1", "intent_digest": self.intent["intent_digest"]})
        checkpoint = SimpleNamespace(module_key="cycle", lesson_key="lesson", assessment_status="completed",
                                     assessment_payload=self.checkpoint)
        rows = [[checkpoint], self.data["documents"], self.data["modules"], self.data["lessons"],
                self.data["quizzes"], self.data["questions"], self.data["choices"]]
        session = Session([None if foreign else self.job, run, self.data["course"]], rows)
        class Manager:
            async def __aenter__(self):
                return session
            async def __aexit__(self, *_args):
                return None
        return Manager()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["rollback", "cancel", "lost_ack"])
async def test_prepare_uncertainty_never_triggers_save_or_retry(monkeypatch, mode):
    h = Harness(monkeypatch)
    with pytest.raises((RuntimeError, asyncio.CancelledError, TimeoutError)):
        h.prepare(mode)
    assert not h.saved
    if mode == "lost_ack":
        assert has_pending(h.job.result) and h.checkpoint == h.snapshot
        with pytest.raises(ValueError):
            h.prepare()
    else:
        assert not has_pending(h.job.result) and h.checkpoint is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["rollback", "cancel", "lost_ack"])
async def test_save_uncertainty_reconciles_only_exact_committed_receipt(monkeypatch, mode):
    h = Harness(monkeypatch)
    h.prepare()
    with pytest.raises((RuntimeError, asyncio.CancelledError, TimeoutError)):
        h.save(mode)
    expected = mode == "lost_ack"
    assert h.saved is expected
    assert has_pending(h.job.result) is not expected
    result = await recover_completed_save(session_factory=h.recovery_session,
        tenant_id=UUID(h.intent["tenant_id"]), authenticated_actor_id=UUID(h.intent["user_id"]),
        job_id=UUID(h.intent["job_id"]))
    assert result is expected
    if expected:
        result = await recover_completed_save(session_factory=lambda: h.recovery_session(foreign=True),
            tenant_id=UUID(h.intent["tenant_id"]), authenticated_actor_id=uuid4(), job_id=UUID(h.intent["job_id"]))
        assert result is False


@pytest.mark.asyncio
async def test_recovery_cancellation_propagates(monkeypatch):
    from app.modules.ai.v3 import final_save_recovery

    h = Harness(monkeypatch)
    async def cancelled(*_args, **_kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(final_save_recovery, "read_completed_snapshot", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await recover_completed_save(session_factory=h.recovery_session,
            tenant_id=UUID(h.intent["tenant_id"]), authenticated_actor_id=UUID(h.intent["user_id"]),
            job_id=UUID(h.intent["job_id"]))


@pytest.mark.asyncio
@pytest.mark.parametrize("verified", [True, False])
async def test_recovered_course_requires_verified_same_session(monkeypatch, verified):
    from app.modules.ai.v3 import final_save_recovery

    h = Harness(monkeypatch)
    session = SimpleNamespace()
    seen = []
    async def read(actual, **_kwargs):
        seen.append(actual)
        return verified
    async def scalar(statement):
        seen.append(session)
        assert isinstance(statement.compile().params["id_1"], str)
        return SimpleNamespace(course_id=h.data["course"].id)
    session.scalar = scalar
    class Manager:
        async def __aenter__(self):
            return session
        async def __aexit__(self, *_args):
            return None
    monkeypatch.setattr(final_save_recovery, "read_completed_snapshot", read)
    result = await recover_completed_course_id(session_factory=Manager, tenant_id=UUID(h.intent["tenant_id"]),
        authenticated_actor_id=UUID(h.intent["user_id"]), job_id=UUID(h.intent["job_id"]))
    assert result == (h.data["course"].id if verified else None)
    assert seen == ([session, session] if verified else [session])


@pytest.mark.asyncio
async def test_verified_readback_session_exit_failure_is_unknown(monkeypatch):
    from app.modules.ai.v3 import final_save_recovery

    h = Harness(monkeypatch)
    async def verified(*_args, **_kwargs):
        return True
    monkeypatch.setattr(final_save_recovery, "read_completed_snapshot", verified)
    class Session:
        async def scalar(self, _statement):
            return SimpleNamespace(course_id=h.data["course"].id)
    class Manager:
        async def __aenter__(self):
            return Session()
        async def __aexit__(self, *_args):
            raise RuntimeError("synthetic_close_failure")
    result = await recover_completed_course_id(session_factory=Manager, tenant_id=UUID(h.intent["tenant_id"]),
        authenticated_actor_id=UUID(h.intent["user_id"]), job_id=UUID(h.intent["job_id"]))
    assert result is None
