"""Database-free safety contracts for the isolated lesson dialogue DEV gate."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def gate():
    spec = importlib.util.spec_from_file_location(
        "lesson_dialogue_dev_gate_test",
        ROOT / "scripts" / "ops" / "lesson_dialogue_dev_gate.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_schema_is_owned_random_shape_and_public_is_rejected(gate):
    assert gate.safe_schema("workbench_0123456789ab") == '"workbench_0123456789ab"'
    for value in (
        "public",
        "workbench_short",
        "workbench_0123456789ABC",
        "workbench_0123456789ab;drop",
    ):
        with pytest.raises(gate.GateBlocked):
            gate.safe_schema(value)


def test_complete_unique_dialogue_matrix_is_required(gate):
    complete = list(gate.REQUIRED_CHECKS)
    gate.validate_checks(complete)
    for checks in ([], complete[:-1], complete + [complete[0]]):
        with pytest.raises(gate.GateBlocked, match="required_checks_missing"):
            gate.validate_checks(checks)


def test_v11_runtime_matrix_and_both_accepted_contracts_are_frozen(gate):
    assert {
        "same_tenant_move_interrupted",
        "absent_target_interrupted_no_inference",
        "expired_pending_get_interrupted",
        "sibling_api_private",
        "foreign_api_private",
        "different_language_api_empty",
    } <= gate.REQUIRED_CHECKS
    names = {path.name for path in gate.CRITICAL_SOURCES}
    assert {
        "EDITOR_DURABLE_LESSON_DIALOGUE_V1.md",
        "EDITOR_DURABLE_LESSON_DIALOGUE_V1_1.md",
    } <= names
    assert len(gate.REQUIRED_CHECKS) == 27
    assert gate.EXPIRY_CLOCK_EVIDENCE == "DETERMINISTIC_APP_CLOCK_PLUS_11_MINUTES"


def test_verifier_never_bypasses_database_trigger_for_clock_fixture():
    source = (
        ROOT / "scripts" / "ops" / "lesson_dialogue_dev_checks.py"
    ).read_text(encoding="utf-8").upper()
    assert "DISABLE TRIGGER" not in source
    assert "SESSION_REPLICATION_ROLE" not in source
    assert "ALTER TABLE" not in source


def test_tenant_fixture_reused_binds_are_uuid_anchored_before_slug_text():
    from lesson_dialogue_dev_checks import tenant_fixture_sql

    statement = tenant_fixture_sql('"workbench_0123456789ab"')
    assert statement.count("CAST(:tenant AS uuid)") == 2
    assert statement.count("CAST(:foreign AS uuid)") == 2
    assert "CAST(:tenant AS text)" not in statement
    assert "CAST(:foreign AS text)" not in statement
    assert "CAST(CAST(:tenant AS uuid) AS text)" in statement
    assert "CAST(CAST(:foreign AS uuid) AS text)" in statement


def test_critical_source_manifest_is_exact_and_content_bound(gate, monkeypatch, tmp_path):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("one\n", encoding="utf-8")
    second.write_text("two\n", encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "CRITICAL_SOURCES", (first, second))
    initial = gate.source_manifest()
    assert set(initial) == {"first.py", "second.py"}
    first.write_text("changed\n", encoding="utf-8")
    assert gate.source_manifest()["first.py"] != initial["first.py"]
    monkeypatch.setattr(gate, "CRITICAL_SOURCES", (first, first))
    with pytest.raises(gate.GateBlocked, match="duplicate_critical_source"):
        gate.source_manifest()


def test_source_manifest_refuses_outside_or_missing_files(gate, monkeypatch, tmp_path):
    outside = tmp_path.parent / "outside-dialogue-gate.py"
    outside.write_text("outside\n", encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "CRITICAL_SOURCES", (outside,))
    with pytest.raises(gate.GateBlocked, match="critical_source_missing"):
        gate.source_manifest()
    outside.unlink()


def test_canonical_config_requires_runtime_role_and_exact_project(gate, tmp_path, monkeypatch):
    import workbench_document_dev_gate as canonical

    path = tmp_path / ".env"
    path.write_text(
        "MIGRATION_DATABASE_URL=postgresql://postgres.project-ref:pw@example.supabase.co:5432/postgres\n"
        "DATABASE_URL=postgresql://lms_app.project-ref:pw@example.supabase.co:5432/postgres\n"
        "SUPABASE_URL=https://example.supabase.co\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(canonical, "same_supabase_project", lambda _database, _supabase: True)
    config = gate.canonical_config(path)
    assert config["runtime_url"].startswith("postgresql+asyncpg://lms_app")
    bad = tmp_path / "bad.env"
    bad.write_text(
        path.read_text(encoding="utf-8").replace("lms_app.project-ref", "service_role.project-ref"),
        encoding="utf-8",
    )
    with pytest.raises(gate.GateBlocked, match="wrong_runtime_role"):
        gate.canonical_config(bad)


def test_failure_evidence_never_contains_exception_message(gate):
    error = RuntimeError("postgresql://private:secret@example.invalid raw dialogue")
    assert gate.sanitize_failure(error) == "RuntimeError"
    assert gate.failure_detail(error) == {}
    payload = {
        "status": "BLOCKED",
        "failure": gate.sanitize_failure(error),
        "detail": gate.failure_detail(error),
    }
    assert "secret" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_invalid_schema_never_opens_database_engine(gate, monkeypatch):
    monkeypatch.setattr(
        gate, "create_async_engine", lambda *_args, **_kwargs: pytest.fail("engine opened")
    )
    with pytest.raises(gate.GateBlocked, match="unsafe_schema_name"):
        await gate.run_gate("unused", "unused", "unused", "public")


def test_apply_migration_rejects_unknown_operation_before_loading(gate):
    class Connection:
        async def run_sync(self, _call):
            pytest.fail("migration loaded")

    with pytest.raises(gate.GateBlocked, match="invalid_migration_request"):
        import asyncio

        asyncio.run(gate.apply_0179(Connection(), "workbench_0123456789ab", "stamp"))


class _Connection:
    def __init__(self, *, exists=False):
        self.exists = exists
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def scalar(self, *_args, **_kwargs):
        return self.exists

    async def execute(self, statement, *_args, **_kwargs):
        self.calls.append(str(statement))

    async def commit(self):
        self.calls.append("COMMIT")


class _Engine:
    def __init__(self, connection):
        self.connection = connection
        self.sync_engine = object()
        self.disposed = False

    def connect(self):
        return self.connection

    async def dispose(self):
        self.disposed = True


def _mock_engines(gate, monkeypatch, *, exists=False):
    owner = _Engine(_Connection(exists=exists))
    runtime = _Engine(_Connection())
    queue = iter((owner, runtime))
    monkeypatch.setattr(gate, "create_async_engine", lambda *_args, **_kwargs: next(queue))
    monkeypatch.setattr(gate.event, "listen", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate.event, "listens_for", lambda *_args, **_kwargs: lambda fn: fn)
    monkeypatch.setattr(gate, "same_supabase_project", lambda *_args: True)
    monkeypatch.setattr(gate, "source_manifest", lambda: {"source.py": "a" * 64})

    async def verify(_connection):
        return None

    async def snapshot(_connection):
        return "0178", ("tenants",)

    monkeypatch.setattr(gate, "verify_runtime_role", verify)
    monkeypatch.setattr(gate, "public_snapshot", snapshot)
    return owner, runtime


@pytest.mark.asyncio
async def test_collision_never_drops_preexisting_schema(gate, monkeypatch):
    owner, runtime = _mock_engines(gate, monkeypatch, exists=True)
    monkeypatch.setattr(
        gate, "cleanup", lambda *_args: pytest.fail("preexisting schema dropped")
    )
    result = await gate.run_gate(
        "postgresql+asyncpg://postgres@localhost/x",
        "postgresql+asyncpg://lms_app@localhost/x",
        "unused",
        "workbench_0123456789ab",
    )
    assert result["status"] == "BLOCKED" and result["failure"] == "schema_collision"
    assert not any("CREATE SCHEMA" in call for call in owner.connection.calls)
    assert owner.disposed and runtime.disposed


@pytest.mark.asyncio
async def test_partial_schema_creation_is_cleaned_and_public_rechecked(gate, monkeypatch):
    owner, runtime = _mock_engines(gate, monkeypatch)
    cleaned = []

    async def broken_clone(*_args, **_kwargs):
        raise RuntimeError("private fixture body")

    async def cleanup(*_args, **_kwargs):
        cleaned.append(True)
        return True

    monkeypatch.setattr(gate, "clone_application_tables", broken_clone)
    monkeypatch.setattr(gate, "cleanup", cleanup)
    result = await gate.run_gate(
        "postgresql+asyncpg://postgres@localhost/x",
        "postgresql+asyncpg://lms_app@localhost/x",
        "unused",
        "workbench_0123456789ab",
    )
    assert result["status"] == "BLOCKED" and result["failure"] == "RuntimeError"
    assert result["cleanup"] and result["public_schema_neutral"] and cleaned == [True]
    assert "private fixture body" not in json.dumps(result)
    assert owner.disposed and runtime.disposed
