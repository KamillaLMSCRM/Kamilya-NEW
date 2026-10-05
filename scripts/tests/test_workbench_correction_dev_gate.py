"""Database-free safety regressions; the runtime matrix is a separate DEV gate."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def gate():
    spec = importlib.util.spec_from_file_location(
        "correction_gate_test", ROOT / "scripts/ops/workbench_correction_dev_gate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_owned_schema_only(gate):
    assert gate.safe_schema("workbench_0123456789ab") == '"workbench_0123456789ab"'
    for name in (
        "public",
        "workbench_short",
        "workbench_0123456789AB",
        "workbench_0123456789ab;drop",
    ):
        with pytest.raises(gate.GateBlocked):
            gate.safe_schema(name)


def test_exact_migration_and_clone_inventory(gate):
    assert gate.MIGRATION.name == "0176_workbench_lesson_correction_previews.py"
    assert len(gate.CLONE_TABLES) == len(set(gate.CLONE_TABLES)) == 16
    assert {
        "tenant_settings",
        "tenant_llm_usage",
        "quiz_choices",
        "course_approval_revisions",
    } <= set(gate.CLONE_TABLES)


def test_raw_error_is_never_reflected(gate):
    assert (
        gate.sanitize_failure(
            RuntimeError("postgresql://private:secret@example.invalid")
        )
        == "RuntimeError"
    )


def test_partial_or_duplicated_matrix_cannot_pass(gate):
    complete = list(gate.REQUIRED_CHECKS)
    gate.validate_checks(complete)
    for partial in ([], complete[:-1], complete + [complete[0]]):
        with pytest.raises(gate.GateBlocked, match="required_checks_missing"):
            gate.validate_checks(partial)


@pytest.mark.asyncio
async def test_synthetic_source_uses_actual_converter_and_quality(gate, monkeypatch):
    from hashlib import sha256
    from types import SimpleNamespace
    from uuid import uuid4

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", "test_jwt_secret_for_ci_only_min_length_32")
    from app.modules.ai.lesson_quality import evaluate_lesson_quality
    from workbench_correction_dev_checks import BLOB, fixture_facts

    document = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        title="Synthetic",
        filename="source.md",
        s3_key="synthetic.md",
        size=len(BLOB),
        lifecycle_status="active",
        category="general",
        content_sha256=sha256(BLOB).hexdigest(),
    )
    content, references = await fixture_facts(
        document,
        SimpleNamespace(get_bytes=lambda key: BLOB if key == "synthetic.md" else None),
    )
    assert references and "steel" in content
    assert all(
        ref["source_locator"].startswith(f"doc_id={document.id};") for ref in references
    )
    assert evaluate_lesson_quality(
        title="Material", content=content, source_chunks=[content]
    ).accepted


@pytest.mark.asyncio
async def test_invalid_schema_never_opens_engine(gate, monkeypatch):
    monkeypatch.setattr(
        gate, "create_async_engine", lambda *_a, **_k: pytest.fail("engine created")
    )
    with pytest.raises(gate.GateBlocked, match="unsafe_schema_name"):
        await gate.run_gate("unused", "unused", "unused", "public")


class Connection:
    def __init__(self, *, exists=False):
        self.exists = exists
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def scalar(self, *_a, **_k):
        return self.exists

    async def execute(self, statement, *_a, **_k):
        self.calls.append(str(statement))

    async def commit(self):
        self.calls.append("COMMIT")


class Engine:
    def __init__(self, connection):
        self.connection = connection
        self.sync_engine = object()
        self.disposed = False

    def connect(self):
        return self.connection

    def begin(self):
        return self.connection

    async def dispose(self):
        self.disposed = True


def mock_engines(gate, monkeypatch, *, exists=False):
    owner, runtime = Engine(Connection(exists=exists)), Engine(Connection())
    queue = iter((owner, runtime))
    monkeypatch.setattr(gate, "create_async_engine", lambda *_a, **_k: next(queue))
    monkeypatch.setattr(gate.event, "listens_for", lambda *_a: lambda fn: fn)
    monkeypatch.setattr(gate, "same_supabase_project", lambda *_a: True)

    async def verify(_connection):
        return None

    async def snapshot(_connection):
        return "0175", ("tenants",)

    monkeypatch.setattr(gate, "verify_runtime_role", verify)
    monkeypatch.setattr(gate, "public_snapshot", snapshot)
    return owner, runtime


@pytest.mark.asyncio
async def test_collision_never_drops_preexisting_schema(gate, monkeypatch):
    owner, runtime = mock_engines(gate, monkeypatch, exists=True)
    monkeypatch.setattr(
        gate, "cleanup", lambda *_a: pytest.fail("preexisting schema dropped")
    )
    result = await gate.run_gate(
        "postgresql+asyncpg://postgres@localhost/x",
        "postgresql+asyncpg://lms_app@localhost/x",
        "unused",
        "workbench_0123456789ab",
    )
    assert result["status"] == "BLOCKED"
    assert result["failure"] == "schema_collision"
    assert not any("CREATE SCHEMA" in call for call in owner.connection.calls)
    assert owner.disposed and runtime.disposed


@pytest.mark.asyncio
async def test_post_create_failure_always_cleans_and_rechecks(gate, monkeypatch):
    owner, runtime = mock_engines(gate, monkeypatch)
    calls = []

    async def broken_clone(*_a):
        raise RuntimeError("secret raw SQL detail")

    async def cleanup(*_a):
        calls.append("cleanup")
        return True

    monkeypatch.setattr(gate, "clone_tables", broken_clone)
    monkeypatch.setattr(gate, "cleanup", cleanup)
    result = await gate.run_gate(
        "postgresql+asyncpg://postgres@localhost/x",
        "postgresql+asyncpg://lms_app@localhost/x",
        "unused",
        "workbench_0123456789ab",
    )
    assert result["status"] == "BLOCKED" and result["failure"] == "RuntimeError"
    assert result["cleanup"] and result["public_schema_neutral"]
    assert calls == ["cleanup"]
    assert any("CREATE SCHEMA" in call for call in owner.connection.calls)
    assert "COMMIT" in owner.connection.calls
    assert owner.disposed and runtime.disposed


@pytest.mark.asyncio
async def test_readback_failure_is_fail_closed_and_engines_disposed(gate, monkeypatch):
    owner, runtime = mock_engines(gate, monkeypatch)
    snapshots = 0

    async def snapshot(_connection):
        nonlocal snapshots
        snapshots += 1
        if snapshots > 1:
            raise RuntimeError("private connection detail")
        return "0175", ("tenants",)

    async def broken_clone(*_a):
        raise ValueError("private source")

    async def cleanup(*_a):
        return True

    monkeypatch.setattr(gate, "public_snapshot", snapshot)
    monkeypatch.setattr(gate, "clone_tables", broken_clone)
    monkeypatch.setattr(gate, "cleanup", cleanup)
    result = await gate.run_gate(
        "postgresql+asyncpg://postgres@localhost/x",
        "postgresql+asyncpg://lms_app@localhost/x",
        "unused",
        "workbench_0123456789ab",
    )
    assert result["status"] == "BLOCKED" and not result["public_schema_neutral"]
    assert result["readback_failure"] == "RuntimeError"
    assert result["failure"] == "ValueError"
    assert owner.disposed and runtime.disposed
