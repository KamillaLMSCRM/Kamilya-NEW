"""Offline claim/retirement fencing on actual service and Celery task."""

import asyncio
from contextlib import asynccontextmanager
from uuid import UUID

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.sql.elements import TextClause

from app.models.ai_job import AIJob
from app.modules.ai import job_service, tasks
from app.modules.ai.generation_engine import CURRENT_GENERATION_ENGINE

TENANT = UUID("11111111-1111-1111-1111-111111111111")
USER = UUID("22222222-2222-2222-2222-222222222222")


class Session:
    def __init__(self, conn):
        self.conn = conn

    async def execute(self, statement, params=None):
        if isinstance(statement, TextClause):
            return None
        return self.conn.execute(statement)

    async def commit(self):
        self.conn.commit()


@pytest.fixture
def make_job(monkeypatch):
    async def lock_tenant(*args):
        return None

    monkeypatch.setattr(job_service, "_lock_tenant_row", lock_tenant)

    def make(result=None, engine=CURRENT_GENERATION_ENGINE):
        db = create_engine("sqlite://")
        AIJob.__table__.create(db)
        with db.begin() as c:
            c.execute(
                insert(AIJob).values(
                    id="job",
                    tenant_id=TENANT,
                    user_id=USER,
                    status="pending",
                    stage="queued",
                    params={"source_analysis": {"generation_engine": engine, "analysis_mode": "direct_source"}},
                    result=result,
                )
            )
        return db

    return make


@pytest.mark.asyncio
async def test_actual_claim_and_retire_cannot_consume_stale_resume(make_job, monkeypatch):
    db = make_job({"delivery_task_id": "new", "resume_count": 1})
    refund = []

    async def release(*args, **kwargs):
        refund.append(True)

    monkeypatch.setattr(job_service, "release_generation_reservation_once", release)
    with db.connect() as conn:
        session = Session(conn)
        assert not await job_service.claim_generation_execution(session, "job", TENANT, "old")
        assert not await job_service.retire_legacy_generation_execution(session, "job", TENANT, "old")
        assert not await job_service.retire_legacy_generation_execution(session, "job", TENANT, "new")
        assert not await job_service.claim_generation_execution(
            session, "job", UUID("33333333-3333-3333-3333-333333333333"), "new"
        )
        assert await job_service.claim_generation_execution(session, "job", TENANT, "new")
        assert not await job_service.claim_generation_execution(session, "job", TENANT, "new")
    assert refund == []


@pytest.mark.asyncio
async def test_actual_legacy_retire_and_initial_claim(make_job, monkeypatch):
    refund = []

    async def release(*args, **kwargs):
        refund.append(True)

    monkeypatch.setattr(job_service, "release_generation_reservation_once", release)
    db = make_job(engine="legacy")
    with db.connect() as conn:
        session = Session(conn)
        assert not await job_service.retire_legacy_generation_execution(session, "job", TENANT, "wrong")
        assert await job_service.retire_legacy_generation_execution(session, "job", TENANT, "job")
        assert not await job_service.retire_legacy_generation_execution(session, "job", TENANT, "job")
    assert refund == [True]
    db = make_job()
    with db.connect() as conn:
        assert await job_service.claim_generation_execution(Session(conn), "job", TENANT, "job")
    db = make_job({"resume_count": 1})
    with db.connect() as conn:
        assert not await job_service.claim_generation_execution(Session(conn), "job", TENANT, "job")


def test_actual_celery_task_passes_request_id_through_claim_and_retire(monkeypatch):
    import app.core.db as core_db

    events = []

    @asynccontextmanager
    async def session():
        yield object()

    async def claim(db, job, tenant, delivery):
        events.append(("claim", job, tenant, delivery))
        return False

    async def retire(db, job, tenant, delivery):
        events.append(("retire", job, tenant, delivery))
        return False

    monkeypatch.setattr(core_db, "async_session_factory", session)
    monkeypatch.setattr(job_service, "claim_generation_execution", claim)
    monkeypatch.setattr(job_service, "retire_legacy_generation_execution", retire)
    monkeypatch.setattr(tasks, "_run_async", asyncio.run)
    result = tasks.generate_course_task.apply(
        kwargs={
            "job_id": "job",
            "documents": ["doc"],
            "tenant_id": TENANT,
            "source_analysis": {"generation_engine": CURRENT_GENERATION_ENGINE, "analysis_mode": "direct_source"},
        },
        task_id="old",
        throw=True,
    ).get()
    assert result["status"] == "skipped"
    assert events == [("claim", "job", TENANT, "old"), ("retire", "job", TENANT, "old")]


def test_actual_celery_legacy_payload_cannot_retire_other_delivery(monkeypatch):
    import app.core.db as core_db

    events = []

    @asynccontextmanager
    async def session():
        yield object()

    async def retire(db, job, tenant, delivery):
        events.append((job, tenant, delivery))
        return False

    monkeypatch.setattr(core_db, "async_session_factory", session)
    monkeypatch.setattr(job_service, "retire_legacy_generation_execution", retire)
    monkeypatch.setattr(tasks, "_run_async", asyncio.run)
    result = tasks.generate_course_task.apply(
        kwargs={
            "job_id": "job",
            "documents": ["doc"],
            "tenant_id": TENANT,
            "source_analysis": {"generation_engine": "legacy"},
        },
        task_id="stale",
        throw=True,
    ).get()
    assert result["status"] == "skipped" and events == [("job", TENANT, "stale")]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["missing", "semantic"])
async def test_actual_persisted_noncurrent_mode_not_claimed(make_job, mode, monkeypatch):
    from sqlalchemy import update

    db = make_job({"delivery_task_id": "new", "resume_count": 1})
    refund = []

    async def release(*args, **kwargs):
        refund.append(True)

    monkeypatch.setattr(job_service, "release_generation_reservation_once", release)
    source = {"generation_engine": CURRENT_GENERATION_ENGINE}
    if mode != "missing":
        source["analysis_mode"] = mode
    with db.begin() as c:
        c.execute(update(AIJob).where(AIJob.id == "job").values(params={"source_analysis": source}))
    with db.connect() as c:
        session = Session(c)
        assert not await job_service.claim_generation_execution(session, "job", TENANT, "new")
        assert await job_service.retire_legacy_generation_execution(session, "job", TENANT, "new")
    assert refund == [True]


@pytest.mark.parametrize("exception_kind", ["timeout", "soft"])
def test_actual_task_preclaim_failure_never_mutates_running_job(monkeypatch, caplog, exception_kind):
    from billiard.exceptions import SoftTimeLimitExceeded

    import app.core.db as core_db

    events = []

    @asynccontextmanager
    async def session():
        yield object()

    async def claim(*args):
        raise (TimeoutError("secret-error-text") if exception_kind == "timeout" else SoftTimeLimitExceeded())

    async def forbidden(*args, **kwargs):
        events.append("write")
        return True

    monkeypatch.setattr(core_db, "async_session_factory", session)
    monkeypatch.setattr(job_service, "claim_generation_execution", claim)
    monkeypatch.setattr(job_service, "interrupt_claimed_generation_execution", forbidden)
    monkeypatch.setattr(job_service, "fail_claimed_generation_execution", forbidden)
    monkeypatch.setattr(tasks, "_run_async", asyncio.run)
    result = tasks.generate_course_task.apply(
        kwargs={
            "job_id": "job",
            "documents": ["doc"],
            "tenant_id": TENANT,
            "source_analysis": {"generation_engine": CURRENT_GENERATION_ENGINE, "analysis_mode": "direct_source"},
        },
        task_id="stale",
        throw=True,
    ).get()
    assert result["status"] == "claim_outcome_unknown" and not events
    assert "Generation claim outcome unknown:" in caplog.text
    assert "secret-error-text" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["fail", "interrupt"])
async def test_actual_terminal_updates_only_matching_running_delivery(make_job, operation):
    from sqlalchemy import select, update

    db = make_job({"delivery_task_id": "new", "resume_count": 1})
    with db.begin() as c:
        c.execute(update(AIJob).where(AIJob.id == "job").values(status="running"))

    async def invoke(session, delivery):
        if operation == "fail":
            return await job_service.fail_claimed_generation_execution(session, "job", "failure", TENANT, delivery)
        return await job_service.interrupt_claimed_generation_execution(session, "job", TENANT, delivery)

    with db.connect() as c:
        session = Session(c)
        assert not await invoke(session, "old")
        assert c.execute(select(AIJob.status).where(AIJob.id == "job")).scalar_one() == "running"
        assert await invoke(session, "new")
        assert c.execute(select(AIJob.status).where(AIJob.id == "job")).scalar_one() == (
            "failed" if operation == "fail" else "interrupted"
        )
        assert not await invoke(session, "new")


def test_actual_task_missing_delivery_reports_unknown_without_claim(monkeypatch, caplog):

    events = []

    async def forbidden(*args, **kwargs):
        events.append("write")

    monkeypatch.setattr(job_service, "claim_generation_execution", forbidden)
    result = tasks.generate_course_task.run(
        job_id="job",
        documents=["doc"],
        tenant_id=str(TENANT),
        source_analysis={"generation_engine": CURRENT_GENERATION_ENGINE, "analysis_mode": "direct_source"},
    )
    assert result == {"job_id": "job", "status": "claim_outcome_unknown"} and not events
    assert "Generation claim outcome unknown: missing delivery identity" in caplog.text
