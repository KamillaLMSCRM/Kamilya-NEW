#!/usr/bin/env python3
"""Fail-closed exit-code adapter for the pure release-evidence evaluator."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import TextIO

EVALUATOR_PATH = (
    Path(__file__).resolve().parents[2]
    / ".codex"
    / "skills"
    / "kamilya-release-evidence-gate"
    / "scripts"
    / "evaluate_release_gate.py"
)


def _load_evaluator():
    spec = importlib.util.spec_from_file_location("kamilya_release_evidence_gate_evaluator", EVALUATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("evaluator_import_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _result_contract(result: object) -> dict[str, object]:
    if not isinstance(result, dict):
        raise ValueError("evaluator_result_invalid")
    if result.get("verdict") not in {"GO", "NO_GO"}:
        raise ValueError("evaluator_verdict_invalid")
    if not isinstance(result.get("blockers"), list):
        raise ValueError("evaluator_blockers_invalid")
    if result.get("root_reference_verification_required") is not True:
        raise ValueError("root_reference_verification_required")
    if result.get("actionable") is not False:
        raise ValueError("evaluator_actionable_contract_invalid")
    return result


def main(stdin: TextIO | None = None, stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    try:
        evaluator = _load_evaluator()
        envelope = evaluator.read_envelope(stdin)
        result = _result_contract(evaluator.evaluate(envelope))
        verdict = result["verdict"]
        blockers = result["blockers"]
        print(json.dumps(result, sort_keys=True), file=output)
        if verdict == "GO" and blockers == []:
            return 0
        if verdict == "NO_GO":
            return 1
        raise ValueError("evaluator_exit_contract_invalid")
    except Exception as exc:  # noqa: BLE001 - CLI boundary must fail closed
        print(f"kamilya-release-evidence-gate: {type(exc).__name__}: {exc}", file=errors)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
