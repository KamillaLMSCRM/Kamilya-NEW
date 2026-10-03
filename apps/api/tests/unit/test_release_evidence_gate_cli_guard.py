from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
WRAPPER_PATH = ROOT / "scripts" / "ops" / "check_release_evidence_gate.py"
EVALUATOR_PATH = (
    ROOT / ".codex" / "skills" / "kamilya-release-evidence-gate" / "scripts" / "evaluate_release_gate.py"
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


WRAPPER = _load(WRAPPER_PATH, "release_evidence_gate_cli_guard")
EVALUATOR = _load(EVALUATOR_PATH, "release_evidence_gate_cli_evaluator")


def _envelope(profile: str = "no_migration_predeploy") -> dict:
    base = {
        "schema_version": 1,
        "profile": profile,
        "project": "Kamilya-NEW",
        "release_sha": "a" * 40,
        "repo_fingerprint": "b" * 64,
        "dev_fingerprint": "c" * 64,
        "prod_fingerprint": "d" * 64,
        "evidence": [],
        "approvals": [],
    }
    contract = EVALUATOR.PROFILE_CONTRACTS[profile]
    for index, evidence_id in enumerate(
        (item for _, stage in contract["stages"] for item in stage), start=1
    ):
        environment, kind, labels = EVALUATOR.EVIDENCE_CONTRACT[evidence_id]
        base["evidence"].append({
            "evidence_id": evidence_id,
            "state": "PASS",
            "evidence_label": sorted(labels)[0],
            "release_sha": base["release_sha"],
            "environment": environment,
            "target_fingerprint": base[f"{kind}_fingerprint"],
            "evidence_ref": f"REF-{index:016x}",
            "observed_at": "2026-08-23T12:00:00Z",
            "sensitive": False,
        })
    for index, scope in enumerate(contract["approvals"], start=1):
        kind = EVALUATOR.APPROVAL_CONTRACT[scope]
        base["approvals"].append({
            "approval_id": f"AP-{index:016x}",
            "scope": scope,
            "status": "APPROVED",
            "evidence_label": "OWNER-CONFIRMED",
            "release_sha": base["release_sha"],
            "target_fingerprint": base[f"{kind}_fingerprint"],
            "evidence_ref": f"REF-{index + 100:016x}",
            "approved_at": "2026-08-23T12:00:00Z",
            "sensitive": False,
        })
    return base


def _run(payload: object) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = WRAPPER.main(io.StringIO(json.dumps(payload)), stdout, stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def test_valid_go_preserves_result_and_returns_zero() -> None:
    payload = _envelope()
    expected = EVALUATOR.evaluate(payload)

    code, stdout, stderr = _run(payload)

    assert code == 0
    assert stderr == ""
    assert json.loads(stdout) == expected
    assert expected["verdict"] == "GO"
    assert expected["actionable"] is False


def test_valid_no_go_returns_one_and_preserves_result() -> None:
    payload = _envelope()
    payload["evidence"] = payload["evidence"][:-1]
    expected = EVALUATOR.evaluate(payload)

    code, stdout, stderr = _run(payload)

    assert code == 1
    assert stderr == ""
    assert json.loads(stdout) == expected
    assert expected["verdict"] == "NO_GO"


def test_malformed_input_returns_two_without_json_result() -> None:
    stdout, stderr = io.StringIO(), io.StringIO()
    code = WRAPPER.main(io.StringIO("not-json"), stdout, stderr)

    assert code == 2
    assert stdout.getvalue() == ""
    assert "input_json_invalid" in stderr.getvalue()


@pytest.mark.parametrize(
    "invalid_result",
    [
        None,
        {"verdict": "UNKNOWN"},
        {"verdict": "GO", "blockers": "none"},
        {"verdict": "GO", "blockers": [], "actionable": False},
        {
            "verdict": "GO",
            "blockers": [],
            "root_reference_verification_required": True,
            "actionable": True,
        },
        {
            "verdict": "GO",
            "blockers": ["unresolved"],
            "root_reference_verification_required": True,
            "actionable": False,
        },
    ],
)
def test_invalid_evaluator_result_fails_closed(monkeypatch, invalid_result) -> None:
    monkeypatch.setattr(WRAPPER, "_load_evaluator", lambda: EVALUATOR)
    monkeypatch.setattr(EVALUATOR, "evaluate", lambda _payload: invalid_result)

    code, _stdout, stderr = _run(_envelope())

    assert code == 2
    assert "kamilya-release-evidence-gate:" in stderr
