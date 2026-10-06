"""Verify the API-CWD CI entrypoint resolves repository release modules."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/ci.yml"


def _activation_step() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    marker = "      - name: Controlled workbench activation release contracts\n"
    assert text.count(marker) == 1
    return text.split(marker, 1)[1].split("      - name:", 1)[0]


def test_ci_activation_step_binds_api_and_repository_import_paths() -> None:
    step = _activation_step()
    value = re.search(r'^\s+PYTHONPATH: "([^"\n]+)"$', step, re.MULTILINE)
    assert value is not None, "Activation CI must explicitly bind PYTHONPATH"
    assert value.group(1) == "${{ github.workspace }}/apps/api:${{ github.workspace }}"
    child_env = dict(os.environ)
    child_env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "apps/api"), str(ROOT)))
    result = subprocess.run(
        [sys.executable, "-c", "from scripts.ops import ct137_native_release; from scripts.deploy import release_runner_bridge"],
        cwd=ROOT / "apps/api", env=child_env, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_ci_activation_step_runs_this_entrypoint_regression() -> None:
    assert "../../scripts/ci/test_workbench_activation_workflow_contract.py" in _activation_step()


def test_ci_activation_step_keeps_exact_release_contract_selectors() -> None:
    step = _activation_step()
    assert "poetry run pytest -q" in step
    for path in (
        "ops/test_ct137_native_release.py", "ops/test_ct137_workbench_activation.py",
        "ops/test_ct137_native_deploy_cli.py", "deploy/test_dev_workbench_activation.py",
        "deploy/test_dev_correction_activation.py",
        "deploy/test_correction_native_activation.py",
        "tests/test_workbench_staged_dev_schema_gate.py",
        "tests/test_workbench_correction_history_dev_gate.py",
    ):
        assert f"../../scripts/{path}" in step


def test_backend_activation_contracts_resolve_from_actual_ci_api_cwd() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    marker = "      - name: Render-like release-plane contract tests\n"
    assert text.count(marker) == 1
    step = text.split(marker, 1)[1].split("      - name:", 1)[0]
    value = re.search(r'^\s+PYTHONPATH: "([^"\n]+)"$', step, re.MULTILINE)
    assert value is not None, "Backend activation CI must explicitly bind PYTHONPATH"
    assert value.group(1) == "${{ github.workspace }}/apps/api:${{ github.workspace }}"
    child_env = dict(os.environ)
    child_env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "apps/api"), str(ROOT)))
    result = subprocess.run(
        [sys.executable, "-c", "from scripts.deploy import test_correction_backend_activation, test_correction_backend_runtime_contract"],
        cwd=ROOT / "apps/api", env=child_env, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
