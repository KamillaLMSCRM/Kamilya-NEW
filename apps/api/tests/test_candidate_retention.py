from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.candidate_assessments import retention_tasks

ROOT = Path(__file__).parents[3]
MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0102_candidate_retention_enforcement.py"


def test_retention_migration_is_bounded_idempotent_and_least_privileged() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'down_revision = "0101"' in source
    assert "retention_until <= now() AND c.status <> 'deleted'" in source
    assert "FOR UPDATE SKIP LOCKED" in source
    assert "LIMIT p_limit" in source
    assert "p_limit < 1 OR p_limit > 100" in source
    assert "ON CONFLICT (tenant_id, campaign_id) DO UPDATE" in source
    assert "SET revoked_at = COALESCE(revoked_at, now())" in source
    assert "DELETE FROM candidate_assessment_attempts" in source
    assert "first_name = 'Deleted'" in source
    assert "Required role lms_candidate_retention is missing" in source
    assert "GRANT EXECUTE ON FUNCTION enforce_expired_candidate_retention(integer) TO lms_candidate_retention" in source
    assert "REVOKE ALL ON FUNCTION enforce_expired_candidate_retention(integer) FROM PUBLIC, lms_app" in source
    assert "GRANT SELECT ON TABLE candidate_assessment_retention_aggregates TO lms_app" in source
    assert "0102 downgrade refused" in source


def test_retention_sql_keeps_candidate_identity_out_of_aggregate_and_scopes_mutations() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    aggregate_section = source[
        source.index('"candidate_assessment_retention_aggregates"') : source.index("def downgrade")
    ]
    assert 'sa.Column("candidate_id"' not in aggregate_section
    for statement in ("UPDATE candidate_access_credentials", "DELETE FROM candidate_assessment_attempts"):
        start = source.index(statement)
        scoped = source[start : start + 700]
        assert "tenant_id = candidate_row.tenant_id" in scoped
        assert "campaign_id = candidate_row.campaign_id" in scoped
        assert "candidate_id = candidate_row.id" in scoped


class _Session:
    def __init__(self, values: list[int]):
        self.values = values
        self.calls: list[tuple[str, dict]] = []
        self.commits = 0

    async def scalar(self, statement, params):
        self.calls.append((str(statement), params))
        return self.values.pop(0)

    async def commit(self):
        self.commits += 1


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        return False


class _Engine:
    def __init__(self):
        self.disposed = False

    async def dispose(self):
        self.disposed = True


@pytest.mark.asyncio
async def test_recovery_is_bounded_committed_and_idempotent(monkeypatch) -> None:
    session = _Session([1, 0])
    engine = _Engine()
    monkeypatch.setattr(
        retention_tasks,
        "get_settings",
        lambda: SimpleNamespace(CANDIDATE_RETENTION_DATABASE_URL="postgresql+asyncpg://retention"),
    )
    monkeypatch.setattr(retention_tasks, "create_async_engine", lambda *_args, **_kwargs: engine)
    monkeypatch.setattr(
        retention_tasks, "async_sessionmaker", lambda *_args, **_kwargs: lambda: _SessionContext(session)
    )

    first = await retention_tasks.enforce_candidate_retention(limit=1000)
    second = await retention_tasks.enforce_candidate_retention(limit=1000)

    assert first == {"processed": 1, "limit": 100}
    assert second == {"processed": 0, "limit": 100}
    assert all(params == {"limit": 100} for _, params in session.calls)
    assert session.commits == 2
    assert engine.disposed is True


def test_broker_independent_hourly_timer_and_ci_role_contract() -> None:
    service = (ROOT / "infra/systemd/kamilya-candidate-retention.service").read_text(encoding="utf-8")
    timer = (ROOT / "infra/systemd/kamilya-candidate-retention.timer").read_text(encoding="utf-8")
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "app.modules.candidate_assessments.retention_recovery" in service
    assert "celery" not in service.lower()
    assert "OnUnitActiveSec=1h" in timer
    assert "Persistent=true" in timer
    assert "RandomizedDelaySec=5min" in timer
    assert "CANDIDATE_RETENTION_DATABASE_URL" in ci
    assert "CREATE ROLE lms_candidate_retention" in ci


def test_candidate_retention_task_routes_to_maintenance() -> None:
    from app.core.celery_app import celery_app
    from app.modules.admin.superadmin.operations import REQUIRED_CELERY_TASKS

    route = celery_app.amqp.router.route({}, "candidate_assessments.enforce_retention", args=(), kwargs={})
    assert route["queue"].name == "maintenance"
    assert "candidate_assessments.enforce_retention" in REQUIRED_CELERY_TASKS
