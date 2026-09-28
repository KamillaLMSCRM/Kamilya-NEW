#!/usr/bin/env python3
"""Run the corporate-readiness contract against the approved DEV contour.

The runner is deliberately mechanical: selectors come from the journey
contract, API pytest always goes through the canonical PowerShell wrapper, and
runtime gates own their disposable-schema or rollback cleanup.  No provider,
deployment, production, customer-tenant or billing action is performed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
API_ROOT = ROOT / "apps" / "api"
CONTRACT = ROOT / "docs" / "critical-journeys" / "corporate-readiness.json"
PYTEST_WRAPPER = ROOT / "scripts" / "dev" / "run_api_pytest.ps1"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci.critical_journey_gate import load_contract  # noqa: E402


class AcceptanceBlocked(RuntimeError):
    """A deterministic acceptance invariant failed."""


@dataclass(frozen=True, slots=True)
class Stage:
    name: str
    command: tuple[str, ...]
    kind: str
    timeout_seconds: int


@dataclass(frozen=True, slots=True)
class StageResult:
    name: str
    status: str
    duration_seconds: float
    passed_tests: int | None = None
    cleanup: str | None = None


_CONNECTION_RE = re.compile(r"(?:postgres(?:ql)?(?:\+asyncpg)?|redis)://[^\s'\"]+", re.I)
_SECRET_RE = re.compile(r"(?i)(token|secret|password|api[_-]?key)\s*[=:]\s*[^\s,;]+")


def _sanitize_output(value: str) -> str:
    value = _CONNECTION_RE.sub("[redacted-connection]", value)
    value = _SECRET_RE.sub(lambda match: f"{match.group(1)}=[redacted]", value)
    return value[-2000:]


def _pytest_pass_count(output: str) -> int:
    matches = re.findall(r"\b([1-9]\d*) passed\b", output)
    if not matches:
        raise AcceptanceBlocked("pytest_nonzero_pass_count_missing")
    return int(matches[-1])


def _json_objects(output: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            objects.append(payload)
    return objects


def _summarize_stage(stage: Stage, output: str) -> tuple[int | None, str | None]:
    passed_tests = _pytest_pass_count(output) if stage.kind in {"pytest", "training_log"} else None
    if stage.kind == "pytest":
        return passed_tests, None

    payloads = _json_objects(output)
    statuses = {str(item.get("status")) for item in payloads if item.get("status") is not None}
    if stage.kind == "responsibility":
        if "PASSED" not in statuses:
            raise AcceptanceBlocked("responsibility_gate_not_passed")
        return None, "PASS"
    if "PASS" not in statuses:
        raise AcceptanceBlocked(f"{stage.name}_gate_not_passed")
    cleanup_values = {str(item.get("cleanup")) for item in payloads if item.get("cleanup") is not None}
    if "PASS" not in cleanup_values:
        raise AcceptanceBlocked(f"{stage.name}_cleanup_not_passed")
    return passed_tests, "PASS"


def _powershell_executable() -> str:
    executable = shutil.which("pwsh") or shutil.which("powershell")
    if executable is None:
        raise AcceptanceBlocked("powershell_unavailable")
    return executable


def build_stages(env_file: Path, expected_revision: str) -> tuple[Stage, ...]:
    (journey,) = load_contract(CONTRACT)
    shell = _powershell_executable()

    def pytest_command(selectors: tuple[str, ...], *, with_env: bool) -> tuple[str, ...]:
        prefix = [shell, "-NoProfile", "-File", str(PYTEST_WRAPPER)]
        if with_env:
            prefix.extend(("-EnvFile", str(env_file)))
        return tuple((*prefix, *selectors, "-q"))

    return (
        Stage("local_contracts", pytest_command(journey.required_tests, with_env=False), "pytest", 180),
        Stage("dev_database_contracts", pytest_command(journey.database_tests, with_env=True), "pytest", 900),
        Stage(
            "signed_copy_rls",
            (sys.executable, str(ROOT / "scripts/ops/training_evidence_signed_copy_dev_gate.py")),
            "gate",
            300,
        ),
        Stage(
            "manual_reassignment_rls",
            (sys.executable, str(ROOT / "scripts/ops/manual_reassignment_dev_gate.py")),
            "gate",
            300,
        ),
        Stage(
            "training_responsibility",
            (
                sys.executable,
                str(ROOT / "scripts/ops/training_responsibility_dev_gate.py"),
                "--env-file",
                str(env_file),
                "--execute",
            ),
            "responsibility",
            300,
        ),
        Stage(
            "training_log",
            (
                sys.executable,
                str(ROOT / "scripts/ops/training_log_dev_check.py"),
                "--execute-tests",
                "--expected-revision",
                expected_revision,
            ),
            "training_log",
            600,
        ),
    )


def run_acceptance(env_file: Path, expected_revision: str) -> dict[str, Any]:
    stages = build_stages(env_file, expected_revision)
    child_env = dict(os.environ)
    child_env["KAMILYA_DEV_ENV_FILE"] = str(env_file)
    started = time.monotonic()
    results: list[StageResult] = []
    for stage in stages:
        stage_started = time.monotonic()
        completed = subprocess.run(
            stage.command,
            cwd=ROOT,
            env=child_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=stage.timeout_seconds,
            check=False,
        )
        output = completed.stdout + completed.stderr
        duration = round(time.monotonic() - stage_started, 3)
        if completed.returncode != 0:
            raise AcceptanceBlocked(
                json.dumps(
                    {
                        "stage": stage.name,
                        "exit_code": completed.returncode,
                        "output_tail": _sanitize_output(output),
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                )
            )
        passed_tests, cleanup = _summarize_stage(stage, output)
        results.append(
            StageResult(
                name=stage.name,
                status="PASS",
                duration_seconds=duration,
                passed_tests=passed_tests,
                cleanup=cleanup,
            )
        )
    return {
        "status": "PASS",
        "scope": "corporate_readiness_isolated_supabase_dev",
        "expected_revision": expected_revision,
        "contract": str(CONTRACT.relative_to(ROOT)).replace("\\", "/"),
        "duration_seconds": round(time.monotonic() - started, 3),
        "stages": [asdict(result) for result in results],
        "customer_tenant_writes": 0,
        "provider_or_billing_changes": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    env_file = args.env_file.resolve()
    if not env_file.is_file():
        print(json.dumps({"status": "BLOCKED", "error_class": "env_file_missing"}, sort_keys=True))
        return 2
    if not re.fullmatch(r"[0-9]{4}", args.expected_revision):
        print(json.dumps({"status": "BLOCKED", "error_class": "expected_revision_invalid"}, sort_keys=True))
        return 2
    try:
        stages = build_stages(env_file, args.expected_revision)
        if not args.execute:
            print(
                json.dumps(
                    {
                        "status": "READY",
                        "execution": "NOT_STARTED",
                        "stages": [stage.name for stage in stages],
                        "requires_execute": True,
                    },
                    sort_keys=True,
                )
            )
            return 0
        result = run_acceptance(env_file, args.expected_revision)
        encoded = json.dumps(result, ensure_ascii=True, sort_keys=True)
        if args.report is not None:
            report = args.report.resolve()
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(encoded + "\n", encoding="utf-8")
        print(encoded)
        return 0
    except Exception as exc:
        reason = str(exc) if isinstance(exc, AcceptanceBlocked) else "sanitized_unexpected_error"
        print(
            json.dumps(
                {"status": "BLOCKED", "error_class": type(exc).__name__, "reason": reason},
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
