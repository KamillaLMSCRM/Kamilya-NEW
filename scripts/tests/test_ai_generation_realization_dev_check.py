"""Offline safety/lifecycle checks for the isolated-schema realization gate."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def load_gate():
    path = Path(__file__).resolve().parents[1] / "ops" / "ai_generation_realization_dev_check.py"
    spec = importlib.util.spec_from_file_location("realization_dev_gate_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_source_drift_stops_before_any_database_call(monkeypatch, tmp_path):
    gate = load_gate()
    monkeypatch.setattr(gate, "source_digest", lambda: "changed")
    with pytest.raises(ValueError, match="source_identity_invalid"):
        await gate.execute(env_file=tmp_path / "unused.env", revision="0183",
            expected_source="expected", custody_path=tmp_path / "custody.json")
    assert not (tmp_path / "custody.json").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_canonical_lifecycle_preserves_custody_and_restores_hooks(monkeypatch, tmp_path, failure):
    gate = load_gate()
    monkeypatch.setattr(gate, "source_digest", lambda: "expected")
    custody = tmp_path / "custody.json"
    sentinel = object()
    def validate(value):
        return value

    async def run(env, revision):
        assert canonical.validate_schema("aicp_dev_0123456789ab") == "aicp_dev_0123456789ab"
        intent = json.loads(custody.read_text())
        assert intent["state"] == "CREATE_INTENT" and intent["source_sha256"] == "expected"
        assert canonical.exercise_runtime is gate.exercise
        if failure:
            raise RuntimeError("synthetic failure")
        return {"passed": True, "cleanup": True, "shared_migration_head_unchanged": True}

    canonical = SimpleNamespace(exercise_runtime=sentinel, validate_schema=validate, run=run)
    monkeypatch.setitem(sys.modules, "ai_generation_checkpoint_dev_check", canonical)
    operation = gate.execute(env_file=tmp_path / "unused.env", revision="0183",
        expected_source="expected", custody_path=custody)
    if failure:
        with pytest.raises(RuntimeError, match="synthetic"):
            await operation
    else:
        result = await operation
        assert result["source_unchanged"]
    assert canonical.exercise_runtime is sentinel
    assert canonical.validate_schema is validate


def test_default_preflight_has_no_env_or_database_access(monkeypatch, capsys):
    gate = load_gate()
    monkeypatch.setattr(sys, "argv", ["gate"])
    monkeypatch.setattr(gate, "canonical_env_file", lambda: pytest.fail("preflight accessed env"))
    assert gate.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "OFFLINE_PREFLIGHT" and not output["network_attempted"]
    assert len(output["source_sha256"]) == 64
