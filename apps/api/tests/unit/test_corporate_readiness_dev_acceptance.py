from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "ops" / "corporate_readiness_dev_acceptance.py"
if str(SCRIPT.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("corporate_readiness_dev_acceptance", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_contract_builds_six_bounded_stages(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(MODULE, "_powershell_executable", lambda: "pwsh")
    env_file = tmp_path / "dev.env"
    env_file.write_text("APP_ENV=test\n", encoding="utf-8")

    stages = MODULE.build_stages(env_file, "0164")

    assert [stage.name for stage in stages] == [
        "local_contracts",
        "dev_database_contracts",
        "signed_copy_rls",
        "manual_reassignment_rls",
        "training_responsibility",
        "training_log",
    ]
    assert all(stage.timeout_seconds <= 900 for stage in stages)
    assert "--expected-revision" in stages[-1].command
    assert stages[-1].command[-1] == "0164"


def test_pytest_summary_rejects_zero_or_missing_test_count() -> None:
    assert MODULE._pytest_pass_count("10 passed, 1 warning in 2.0s") == 10
    with pytest.raises(MODULE.AcceptanceBlocked, match="nonzero"):
        MODULE._pytest_pass_count("0 passed")
    with pytest.raises(MODULE.AcceptanceBlocked, match="nonzero"):
        MODULE._pytest_pass_count("collected 0 items")


def test_gate_summary_requires_cleanup_and_terminal_pass() -> None:
    stage = MODULE.Stage("signed_copy_rls", ("python", "gate.py"), "gate", 30)
    passed, cleanup = MODULE._summarize_stage(
        stage,
        '{"status":"PASS"}\n{"cleanup":"PASS"}\n',
    )
    assert passed is None
    assert cleanup == "PASS"

    with pytest.raises(MODULE.AcceptanceBlocked, match="cleanup"):
        MODULE._summarize_stage(stage, '{"status":"PASS"}\n{"cleanup":"BLOCKED"}\n')


def test_sanitizer_removes_connections_and_secret_assignments() -> None:
    value = "postgresql://user:pass@example.test/postgres token=secret-value"
    sanitized = MODULE._sanitize_output(value)
    assert "pass" not in sanitized
    assert "secret-value" not in sanitized
    assert "[redacted-connection]" in sanitized
