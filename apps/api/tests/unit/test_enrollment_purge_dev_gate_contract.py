"""Preconnection scope guards for the real, isolated DEV purge proof."""
import asyncio
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def gate(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts/ops"))
    spec = importlib.util.spec_from_file_location("purge_gate_contract", ROOT / "scripts/ops/enrollment_purge_dev_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "create_async_engine", lambda *a, **kw: pytest.fail("connection before scope validation"))
    return module


@pytest.mark.parametrize("schema", ["public", "enrollment_purge_123", "enrollment_purge_" + "a" * 13, 'enrollment_purge_";DROP'])
def test_cleanup_cannot_resolve_outside_owned_namespace(gate, schema):
    with pytest.raises(gate.GateBlocked, match="unsafe_owned_schema"):
        gate.safe_schema(schema)


def test_exact_owned_namespace_is_quoted(gate):
    assert gate.safe_schema("enrollment_purge_012345abcdef") == '"enrollment_purge_012345abcdef"'


def test_unknown_project_rejected_before_connection(gate):
    with pytest.raises(gate.GateBlocked, match="canonical_dev_project_required"):
        asyncio.run(gate.run_gate("", "", "https://unknown123.supabase.co"))


@pytest.mark.parametrize("owner,runtime,error", [
    ("other", "lms_app", "wrong_migration_owner_identity"),
    ("postgres", "other", "wrong_runtime_identity"),
])
def test_wrong_roles_rejected_before_connection(gate, monkeypatch, owner, runtime, error):
    monkeypatch.setattr(gate, "DEV_PROJECT_REF_SHA256", gate.hashlib.sha256(b"testproject123").hexdigest())
    monkeypatch.setattr(gate, "same_supabase_project", lambda *args: True)
    with pytest.raises(gate.GateBlocked, match=error):
        asyncio.run(gate.run_gate(f"postgresql+asyncpg://{owner}@host/postgres", f"postgresql+asyncpg://{runtime}@host/postgres", "https://testproject123.supabase.co"))
