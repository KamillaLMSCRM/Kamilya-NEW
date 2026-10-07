"""Database-free guard tests; real dependencies, no global module stubs."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

PATH = Path(__file__).with_name("capacity_fixture_dev_gate.py")
spec = importlib.util.spec_from_file_location("capacity_gate_guard_tests", PATH)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


@pytest.mark.parametrize("schema", ["public", "capacity_short", "capacity_0123456789AB", "capacity_012345abcdef;drop"])
def test_unsafe_schema_refused(schema):
    with pytest.raises(gate.GateBlocked):
        gate.safe_schema(schema)


def test_exact_owned_schema():
    assert gate.safe_schema("capacity_012345abcdef") == '"capacity_012345abcdef"'


def test_no_execute_never_loads_environment(monkeypatch, capsys):
    monkeypatch.setattr(gate.sys, "argv", ["gate", "--env-file", "missing.env",
                                         "--evidence-file", "missing.json"])
    monkeypatch.setattr(gate, "prepare", lambda *_: pytest.fail("preflight before execute"))
    assert gate.main() == 2
    assert json.loads(capsys.readouterr().out)["failure"] == "execute_flag_required"


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate.subprocess, "run", lambda *_a, **_kw:
                        SimpleNamespace(stdout=str(tmp_path / ".git")))
    config = {"owner_url": "postgresql+asyncpg://postgres@db.unitproject.supabase.co/postgres",
              "runtime_url": "postgresql+asyncpg://lms_app@db.unitproject.supabase.co/postgres",
              "supabase_url": "https://unitproject.supabase.co"}
    monkeypatch.setattr(gate, "canonical_config", lambda _: config)
    monkeypatch.setattr(gate, "PROJECT_HASH", hashlib.sha256(b"unitproject").hexdigest())
    monkeypatch.setattr(gate, "source_hashes", lambda: {"owned.py": "0" * 64})
    target = tmp_path / ".release-evidence/CAPACITY-HOTFIX-20261007/test.json"
    return tmp_path / ".env", target, config


def test_canonical_preflight_passes(prepared):
    env, target, _config = prepared
    assert gate.prepare(env, target)[1] == target


def test_noncanonical_env_refused(prepared):
    env, target, _config = prepared
    with pytest.raises(gate.GateBlocked, match="canonical_env"):
        gate.prepare(env.with_name("other.env"), target)


def test_existing_evidence_refused_before_config(prepared, monkeypatch):
    env, target, _config = prepared
    target.parent.mkdir(parents=True)
    target.write_text("{}")
    monkeypatch.setattr(gate, "canonical_config", lambda _: pytest.fail("read after existing evidence"))
    with pytest.raises(gate.GateBlocked, match="exclusive"):
        gate.prepare(env, target)


def test_wrong_project_refused(prepared):
    env, target, config = prepared
    config["supabase_url"] = "https://foreignproject.supabase.co"
    with pytest.raises(gate.GateBlocked, match="canonical_dev_project"):
        gate.prepare(env, target)


def test_wrong_owner_refused(prepared):
    env, target, config = prepared
    config["owner_url"] = "postgresql+asyncpg://lms_app@db.unit.supabase.co/postgres"
    with pytest.raises(gate.GateBlocked, match="migration_owner"):
        gate.prepare(env, target)


def test_service_seams_not_bypassed():
    source = PATH.read_text(encoding="utf-8")
    assert "async_sessionmaker(engine, expire_on_commit=False)" in source
    assert "._tenant_delete_statements()" in source
    assert "delete_tenant(" not in source
    assert "commit_changes=False, apply_rules=True" in source
    assert '"mark_success", "mark_failure"' in source
    assert "failure.await_count == 0" in source
    assert "UPDATE positions SET" in source and "DELETE FROM departments" in source
    assert "public_fk_identity_or_actions_changed" in source
    assert 'target.open("x"' in source
    assert len(gate.REQUIRED) == 7


def test_reviewed_trigger_rebound_only_to_owned_schema():
    source = ("CREATE OR REPLACE FUNCTION public.example() RETURNS trigger LANGUAGE plpgsql "
              "SET search_path TO 'public', 'pg_temp' AS $$ BEGIN "
              'PERFORM 1 FROM "public".departments; RETURN NEW; END $$')
    digest = hashlib.sha256(source.encode()).hexdigest()
    result = gate.owned_trigger_definition(source, digest, "capacity_012345abcdef")
    assert "public" not in result and "pg_temp" not in result
    assert '"capacity_012345abcdef".departments' in result
    assert "'capacity_012345abcdef', 'pg_catalog'" in result


def test_changed_trigger_refused():
    with pytest.raises(gate.GateBlocked, match="definition_changed"):
        gate.owned_trigger_definition("unexpected", "0" * 64, "capacity_012345abcdef")


@pytest.mark.parametrize("source", ["SELECT public", "SECURITY DEFINER"])
def test_unresolved_or_privileged_trigger_refused(source):
    with pytest.raises(gate.GateBlocked, match="resolution_refused"):
        gate.owned_trigger_definition(source, hashlib.sha256(source.encode()).hexdigest(),
                                      "capacity_012345abcdef")
