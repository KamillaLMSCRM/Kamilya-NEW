"""Unit contracts for tenant-scoped AI admission and queue metadata.

These tests inspect the SQL contracts and call order. They do not claim to
prove PostgreSQL locking or transaction isolation; that requires a real DB
integration test outside this bounded slice.
"""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.ai import job_service


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class _RecordingSession:
    def __init__(self, values):
        self.values = iter(values)
        self.statements = []
        self.flushed = False
        self.added = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(next(self.values))

    async def flush(self):
        self.flushed = True

    def add(self, value):
        self.added.append(value)


class _ScalarSession:
    def __init__(self, value):
        self.value = value
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.value


def _sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def _job(*, tenant_id, status, created_at, job_id="current"):
    return SimpleNamespace(
        id=job_id,
        tenant_id=tenant_id,
        status=status,
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_active_count_is_tenant_scoped_and_excludes_terminal_statuses():
    tenant_id = uuid4()
    db = _RecordingSession([2])

    assert await job_service.count_active_ai_jobs(db, tenant_id) == 2

    statement = _sql(db.statements[0])
    assert "ai_jobs.tenant_id" in statement
    assert "ai_jobs.status IN" in statement
    assert "pending" in statement
    assert "running" in statement
    for terminal in ("completed", "failed", "cancelled"):
        assert terminal not in statement


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "settings,expected",
    [
        ({"ai_max_active_jobs": 4}, 4),
        ({"ai_max_active_jobs": 8}, 8),
        ({"ai_max_active_jobs": 0}, 2),
        ({"ai_max_active_jobs": 9}, 2),
        ({"ai_max_active_jobs": True}, 2),
        ({"ai_max_active_jobs": "4"}, 2),
        ({}, 2),
        (None, 2),
    ],
)
async def test_tenant_active_limit_override_is_bounded(settings, expected):
    db = _ScalarSession(settings)
    tenant_id = uuid4()

    assert await job_service.resolve_tenant_ai_active_limit(db, tenant_id) == expected

    statement = _sql(db.statements[0])
    assert "tenants.settings" in statement
    assert "tenants.id" in statement


@pytest.mark.asyncio
async def test_create_ai_job_remains_unadmitted_for_background_maintenance():
    tenant_id = uuid4()
    user_id = uuid4()
    db = _RecordingSession([])

    job = await job_service.create_ai_job(
        db,
        tenant_id,
        user_id,
        params={"action": "document_reindex"},
    )

    assert job.tenant_id == tenant_id
    assert job.status == "pending"
    assert db.flushed is True
    assert db.statements == []
    assert db.added == [job]


@pytest.mark.asyncio
async def test_admitted_generation_locks_tenant_before_count_and_insert():
    tenant_id = uuid4()
    user_id = uuid4()
    db = _RecordingSession([None, 0])

    job = await job_service.create_admitted_ai_job(
        db,
        tenant_id,
        user_id,
        params={"documents": [str(uuid4())]},
    )

    assert job.tenant_id == tenant_id
    assert job.status == "pending"
    assert db.flushed is True
    assert len(db.statements) == 2
    assert "FOR UPDATE" in _sql(db.statements[0])
    assert "tenants.id" in _sql(db.statements[0])
    assert "ai_jobs.status IN" in _sql(db.statements[1])


@pytest.mark.asyncio
async def test_limit_exception_is_stable_and_contains_admission_details():
    tenant_id = uuid4()
    db = _RecordingSession([None, 2])

    with pytest.raises(job_service.AIJobAdmissionLimitReachedError) as error:
        await job_service.create_admitted_ai_job(
            db,
            tenant_id,
            uuid4(),
            params={"documents": [str(uuid4())]},
            active_limit=2,
        )

    assert error.value.code == "tenant_ai_job_limit_reached"
    assert error.value.tenant_id == tenant_id
    assert error.value.active_count == 2
    assert error.value.active_limit == 2
    assert db.flushed is False


@pytest.mark.asyncio
async def test_pending_queue_position_and_eta_use_same_tenant_durable_jobs():
    tenant_id = uuid4()
    now = datetime.now(UTC)
    job = _job(tenant_id=tenant_id, status="pending", created_at=now, job_id="b")
    db = _RecordingSession([3, 2])

    metadata = await job_service.build_ai_job_queue_metadata(
        db,
        job,
        worker_concurrency=2,
        historical_estimate_seconds=510,
    )

    assert metadata["tenant_active_jobs"] == 3
    assert metadata["tenant_active_limit"] == 2
    assert metadata["queue_position"] == 3
    assert metadata["estimated_wait_seconds"] == 510
    ahead_sql = _sql(db.statements[1])
    assert "ai_jobs.tenant_id" in ahead_sql
    assert "ai_jobs.status IN" in ahead_sql
    assert "ai_jobs.created_at" in ahead_sql


@pytest.mark.asyncio
async def test_running_and_terminal_jobs_have_explicit_queue_semantics():
    tenant_id = uuid4()
    now = datetime.now(UTC)

    running_db = _RecordingSession([1])
    running = await job_service.build_ai_job_queue_metadata(
        running_db,
        _job(tenant_id=tenant_id, status="running", created_at=now),
    )
    assert running["queue_position"] is None
    assert running["estimated_wait_seconds"] is None
    assert len(running_db.statements) == 1

    terminal_db = _RecordingSession([0])
    terminal = await job_service.build_ai_job_queue_metadata(
        terminal_db,
        _job(
            tenant_id=tenant_id,
            status="completed",
            created_at=now - timedelta(minutes=1),
        ),
    )
    assert terminal["queue_position"] is None
    assert terminal["estimated_wait_seconds"] is None
    assert len(terminal_db.statements) == 1
