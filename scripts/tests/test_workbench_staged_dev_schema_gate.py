"""Database-free bounded phase routing and receipt validation."""

import importlib.util
import json
from pathlib import Path
from subprocess import CalledProcessError
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40


@pytest.fixture
def gate(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts/ops"))
    spec = importlib.util.spec_from_file_location("staged_dev_gate_fixture", ROOT / "scripts/ops/dev_public_schema_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def receipt():
    return dict(status="PASS", scope="canonical_supabase_dev_compatibility",
                schema_revision="0169", release_sha=SHA, api_sha=SHA, worker_sha=SHA,
                api_workbench_enabled=False, frontend_workbench_enabled=False,
                auth_bootstrap="PASS", workers_startup="PASS")


def test_default_head_stays_final_and_expand_has_exact_target(gate):
    assert gate.phase_target("0172", None) == "0172"
    assert gate.phase_target("0172", "expand") == "0169"
    assert gate.phase_target("0172", "contract") == "0172"
    with pytest.raises(gate.GateBlocked, match="unsupported_workbench_phase"):
        gate.phase_target("0174", "expand")


def test_final173_requires_staged_contract_from169_or172(gate):
    assert gate.phase_target("0173", "expand") == "0169"
    assert gate.phase_target("0173", "contract") == "0173"
    for current in ("0169", "0172", "0173"):
        gate.verify_phase_path(current, "0173", "contract", apply=True)
    for current in ("0168", "0170", "0171", "0174"):
        with pytest.raises(gate.GateBlocked, match="revision_mismatch"):
            gate.verify_phase_path(current, "0173", "contract", apply=True)
    with pytest.raises(gate.GateBlocked, match="staged_rollout_required"):
        gate.verify_phase_path("0172", "0173", None, apply=True)


def test_repair174_accepts_only_existing173_or174_and_cannot_bypass_phase(gate):
    assert gate.phase_target("0174", "repair") == "0174"
    for current in ("0173", "0174"):
        gate.verify_phase_path(current, "0174", "repair", apply=True)
    for current in ("0169", "0172", "0175"):
        with pytest.raises(gate.GateBlocked, match="revision_mismatch"):
            gate.verify_phase_path(current, "0174", "repair", apply=True)
    with pytest.raises(gate.GateBlocked, match="repair_phase_required"):
        gate.verify_phase_path("0173", "0174", None, apply=True)
    gate.verify_phase_path("0174", "0174", None, apply=True)
    gate.verify_phase_path("0173", "0174", None, apply=False)
    for phase in ("expand", "contract"):
        with pytest.raises(gate.GateBlocked, match="unsupported_workbench_phase"):
            gate.verify_phase_path("0173", "0174", phase, apply=True)


@pytest.mark.parametrize("current,phase", [("0167", "expand"), ("0172", "expand"), ("0168", "contract"), ("0171", "contract")])
def test_skips_backwards_or_unknown_states_are_rejected(gate, current, phase):
    with pytest.raises(gate.GateBlocked, match="workbench_phase_revision_mismatch"):
        gate.verify_phase_path(current, "0172", phase, apply=True)


def test_default_apply_cannot_skip_compatibility_phase(gate):
    with pytest.raises(gate.GateBlocked, match="staged_rollout_required"):
        gate.verify_phase_path("0168", "0172", None, apply=True)
    gate.verify_phase_path("0172", "0172", None, apply=True)
    gate.verify_phase_path("0168", "0172", None, apply=False)


@pytest.mark.parametrize("key,value", [("worker_sha", "b" * 40), ("schema_revision", "0172"), ("auth_bootstrap", "NOT_VERIFIED"), ("api_workbench_enabled", True), ("frontend_workbench_enabled", 0)])
def test_unproven_compatibility_cannot_authorize_contract(gate, tmp_path, key, value):
    payload = receipt()
    payload[key] = value
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(gate.GateBlocked):
        gate.verify_compatibility_receipt(path, SHA)


def test_exact_root_readback_receipt_is_bound_to_sha(gate, tmp_path):
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt()), encoding="utf-8")
    gate.verify_compatibility_receipt(path, SHA)
    with pytest.raises(gate.GateBlocked):
        gate.verify_compatibility_receipt(path, "b" * 40)
    with pytest.raises(gate.GateBlocked):
        gate.verify_compatibility_receipt(None, SHA)


def test_upgrade_uses_exact_target_and_captures_driver_output(gate, monkeypatch):
    run = MagicMock()
    monkeypatch.setattr(gate.subprocess, "run", run)
    gate.run_upgrade({}, "synthetic-never-connected", "0169")
    assert run.call_args.args[0][-1] == "0169"
    assert run.call_args.kwargs["capture_output"] is True


def test_failed_subprocess_output_never_reaches_report(gate, monkeypatch, capsys):
    monkeypatch.setattr(gate, "parse_args", lambda: SimpleNamespace(workbench_phase="expand", expected_revision=None, env_file=None, apply=True))
    monkeypatch.setattr(gate, "repository_head", lambda: "0172")
    monkeypatch.setattr(gate, "resolve_env_file", lambda _: Path("never-read.env"))
    monkeypatch.setattr(gate, "load_dev_environment", lambda _: ({}, "synthetic", "synthetic"))
    async def revision(_):
        return "0168"
    monkeypatch.setattr(gate, "database_revision", revision)
    monkeypatch.setattr(gate, "run_upgrade", MagicMock(side_effect=CalledProcessError(1, ["secret-url"], output="private-driver-text")))
    assert gate.main() == 2
    output = capsys.readouterr().err
    assert "migration_subprocess_failed" in output
    assert "secret-url" not in output and "private-driver-text" not in output


def test_contract_receipt_required_even_for_noop_before_credentials(gate, monkeypatch, capsys):
    monkeypatch.setattr(gate, "parse_args", lambda: SimpleNamespace(
        workbench_phase="contract", expected_revision=None, env_file=None,
        apply=False, compatibility_evidence=None, compatibility_sha=None,
    ))
    monkeypatch.setattr(gate, "repository_head", lambda: "0172")
    environment = MagicMock(side_effect=AssertionError("credential read before receipt"))
    monkeypatch.setattr(gate, "load_dev_environment", environment)
    assert gate.main() == 2
    assert "compatibility_receipt_required" in capsys.readouterr().err
    environment.assert_not_called()
