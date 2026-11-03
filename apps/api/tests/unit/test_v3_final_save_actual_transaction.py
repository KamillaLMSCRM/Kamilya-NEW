"""Guarded in-memory transaction harness using the actual writer and reader."""
import asyncio
import socket
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest

from app.modules.ai import pipeline
from app.modules.ai.delivery_ownership import delivery_id
from app.modules.ai.lesson_cycle import POLICY_VERSION
from app.modules.ai.source_assessment_plan import PLAN_POLICY
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.final_save_owned_checkpoint import checkpoint_final_output
from app.modules.ai.v3.final_save_recovery import recover_completed_save
from app.modules.ai.v3.pending_stage_transactions import has_pending
from app.modules.courses.models import Course
from app.modules.lessons.models import Lesson, Module
from app.modules.quizzes.models import Question, Quiz, QuizChoice
from tests.unit.test_v3_final_save_completed_reader import Session
from tests.unit.test_v3_final_save_owned_checkpoint import setup


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(httpx, "Client", deny)
    monkeypatch.setattr(httpx, "AsyncClient", deny)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["ok", "lost_ack", "rollback", "cancel", "committed_cancel"])
async def test_checkpoint_actual_save_and_completed_reader(monkeypatch, mode):
    from app.modules.ai.v3 import final_save_completed_reader as reader

    data, journal, context = setup(monkeypatch)
    state, intent, job = data["state"], data["intent"], journal.job
    state.owned_v3_source_context = context
    state.owned_v3_route_fingerprint = intent["route_fingerprint"]
    await checkpoint_final_output(journal=journal, context=context, state=state, intent=intent)
    with pytest.raises(ExtractionOutcomeUnknownError):
        from app.modules.ai.v3.final_save_contract import make_intent
        alternative = make_intent(**{key: intent[key] for key in (
            "tenant_id", "user_id", "job_id", "delivery_id", "route_policy", "route_fingerprint", "documents", "output_digest")})
        assert alternative["attempt_id"] != intent["attempt_id"]
        await checkpoint_final_output(journal=journal, context=context, state=state, intent=alternative)
    pre_job = deepcopy(job.__dict__)
    saved = []
    committed = False

    def add(row):
        if getattr(row, "id", None) is None:
            row.id = uuid4()
        if isinstance(row, Course):
            row.delivery_type, row.review_status = "native", "pending"
            row.reviewed_by = row.reviewed_at = row.review_comment = None
        if isinstance(row, Lesson):
            row.published_at = None
        if isinstance(row, Quiz):
            row.time_limit, row.deferral_days = None, 7
        saved.append(row)

    class SaveSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            if not committed:
                job.__dict__.clear()
                job.__dict__.update(deepcopy(pre_job))
                saved.clear()
        async def execute(self, *_args, **_kwargs):
            return None
        async def scalar(self, *_args, **_kwargs):
            return job
        def add(self, row):
            add(row)
        async def flush(self):
            return None
        async def commit(self):
            nonlocal committed
            if mode == "rollback":
                raise RuntimeError("rollback")
            if mode == "cancel":
                raise asyncio.CancelledError()
            committed = True
            if mode == "lost_ack":
                raise TimeoutError("ack lost")
            if mode == "committed_cancel":
                raise asyncio.CancelledError()

    monkeypatch.setattr(pipeline, "async_session_factory", SaveSession)
    monkeypatch.setattr(pipeline, "lock_owned_delivery", AsyncMock())
    token = delivery_id.set(intent["delivery_id"])
    try:
        if mode == "ok":
            await pipeline._save_generation_to_db(state, UUID(intent["tenant_id"]), UUID(intent["user_id"]),
                                                  final_intent=intent)
        else:
            with pytest.raises(ExtractionOutcomeUnknownError):
                await pipeline._save_generation_to_db(state, UUID(intent["tenant_id"]), UUID(intent["user_id"]),
                                                      final_intent=intent)
    finally:
        delivery_id.reset(token)
    if mode in {"rollback", "cancel"}:
        assert has_pending(job.result) and not saved
        return

    def rows(cls):
        return [row for row in saved if isinstance(row, cls)]
    run = SimpleNamespace(id=uuid4(), plan_revision=f"{PLAN_POLICY}/{POLICY_VERSION}",
                          plan_payload={"schema": "v3-final-snapshot-v1", "intent_digest": intent["intent_digest"]})
    checkpoint = SimpleNamespace(module_key="cycle", lesson_key="lesson", assessment_status="completed",
                                 assessment_payload=next(iter(journal.values.values())))
    async def source(*_args, **_kwargs):
        return data["source_corpus"]
    monkeypatch.setattr(reader, "build_direct_source_corpus", source)
    read_session = Session([job, run, rows(Course)[0]], [[checkpoint], data["documents"], rows(Module), rows(Lesson),
                           rows(Quiz), rows(Question), rows(QuizChoice)])
    class ReadManager:
        async def __aenter__(self):
            return read_session
        async def __aexit__(self, *_args):
            return None
    assert await recover_completed_save(session_factory=ReadManager, tenant_id=UUID(intent["tenant_id"]),
        authenticated_actor_id=UUID(intent["user_id"]), job_id=UUID(intent["job_id"]))


@pytest.mark.asyncio
async def test_completed_reader_foreign_actor_query_is_scoped_before_checkpoint(monkeypatch):
    from app.modules.ai.v3.final_save_completed_reader import read_completed_snapshot

    data, _journal, _context = setup(monkeypatch)
    intent = data["intent"]
    foreign = uuid4()
    seen = []

    class QuerySession:
        async def execute(self, *_args, **_kwargs):
            return None

        async def scalar(self, statement):
            compiled = statement.compile()
            seen.append((str(compiled), compiled.params))
            return None

        async def scalars(self, *_args, **_kwargs):
            raise AssertionError("foreign job must not read checkpoints")

    result = await read_completed_snapshot(QuerySession(), tenant_id=UUID(intent["tenant_id"]),
        actor_id=foreign, job_id=UUID(intent["job_id"]))
    assert result is False and len(seen) == 1
    sql, params = seen[0]
    assert "ai_jobs.tenant_id" in sql and "ai_jobs.user_id" in sql and "ai_jobs.id" in sql
    assert UUID(intent["tenant_id"]) in params.values() and foreign in params.values()
    assert intent["job_id"] in params.values()
