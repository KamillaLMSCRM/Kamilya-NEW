"""Database-free safety contract tests for the document workbench DEV gate."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def gate():
    spec = importlib.util.spec_from_file_location(
        "workbench_document_dev_gate_test", ROOT / "scripts" / "ops" / "workbench_document_dev_gate.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_schema_is_random_workbench_shape_and_rejects_public(gate):
    assert gate.safe_schema("workbench_0123456789ab") == '"workbench_0123456789ab"'
    for value in ("public", "workbench_short", "workbench_0123456789ABC", "workbench_0123456789ab;drop"):
        with pytest.raises(gate.GateBlocked):
            gate.safe_schema(value)


def test_canonical_config_requires_exact_dev_identity_and_non_bypass_runtime(gate, tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(
        "MIGRATION_DATABASE_URL=postgresql://postgres.project-ref:pw@example.supabase.co:5432/postgres\n"
        "DATABASE_URL=postgresql://lms_app.project-ref:pw@example.supabase.co:5432/postgres\n"
        "SUPABASE_URL=https://example.supabase.co\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gate, "same_supabase_project", lambda database, supabase: True)
    config = gate.canonical_config(path)
    assert config["owner_url"].startswith("postgresql+asyncpg://")
    assert "postgres" in config["owner_url"]  # only an in-memory assertion; gate never emits config

    bad = tmp_path / "bad.env"
    bad.write_text(path.read_text(encoding="utf-8").replace("lms_app.project-ref", "service_role.project-ref"), encoding="utf-8")
    with pytest.raises(gate.GateBlocked, match="wrong_runtime_role"):
        gate.canonical_config(bad)


def test_canonical_config_rejects_missing_env_without_connection(gate, tmp_path):
    with pytest.raises(gate.GateBlocked, match="env_file_missing"):
        gate.canonical_config(tmp_path / "missing.env")


def test_sanitized_failure_never_returns_exception_payload(gate):
    error = RuntimeError("postgresql://private:secret@example.invalid")
    assert gate.sanitize_failure(error) == "RuntimeError"
    payload = {"status": "BLOCKED", "error_class": "RuntimeError", "stage": gate.sanitize_failure(error)}
    assert "secret" not in json.dumps(payload)


def test_gate_requires_explicit_env_and_execute_flags(gate, monkeypatch, capsys):
    monkeypatch.setattr(gate, "parse_args", lambda: type("Args", (), {"env_file": Path("never.env"), "execute": False})())
    assert gate.main() == 2
    assert "execute_flag_required" in capsys.readouterr().out
