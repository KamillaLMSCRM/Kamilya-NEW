"""Block new Ruff/mypy debt while legacy findings are reduced incrementally."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
BASELINE_PATH = Path(__file__).with_name("python-quality-baseline.json")


def _relative_path(raw: str) -> str:
    path = Path(raw)
    try:
        return path.resolve().relative_to(API_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def summarize_ruff(payload: list[dict[str, Any]]) -> Counter[str]:
    return Counter(
        f"{_relative_path(str(item['filename']))}|{item.get('code') or 'unknown'}"
        for item in payload
    )


def summarize_mypy(lines: str) -> Counter[str]:
    issues: Counter[str] = Counter()
    for raw_line in lines.splitlines():
        try:
            item = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if item.get("severity", "error") != "error":
            continue
        issues[f"{_relative_path(str(item['file']))}|{item.get('code') or 'unknown'}"] += 1
    return issues


def compare_counts(current: Counter[str], allowed: Counter[str]) -> dict[str, tuple[int, int]]:
    return {
        key: (count, allowed.get(key, 0))
        for key, count in current.items()
        if count > allowed.get(key, 0)
    }


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=API_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(
            f"quality tool failed ({result.returncode}): {' '.join(command)}\n{result.stderr[-2000:]}"
        )
    return result


def collect_current() -> dict[str, Counter[str]]:
    ruff = _run(["ruff", "check", "app", "tests", "--output-format=json"])
    mypy = _run([sys.executable, "-m", "mypy", "app", "-O", "json", "--no-error-summary"])
    return {
        "ruff": summarize_ruff(json.loads(ruff.stdout or "[]")),
        "mypy": summarize_mypy(mypy.stdout),
    }


def _serializable(counts: dict[str, Counter[str]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "policy": "per-file-and-code counts are upper bounds; reductions are allowed",
        "tools": {
            tool: dict(sorted(tool_counts.items()))
            for tool, tool_counts in sorted(counts.items())
        },
    }


def write_baseline(counts: dict[str, Counter[str]]) -> None:
    BASELINE_PATH.write_text(
        json.dumps(_serializable(counts), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_baseline() -> dict[str, Counter[str]]:
    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise RuntimeError("unsupported Python quality baseline schema")
    return {
        tool: Counter({str(key): int(value) for key, value in values.items()})
        for tool, values in payload["tools"].items()
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args()
    current = collect_current()
    if args.write_baseline:
        write_baseline(current)
        print(
            "Wrote Python quality baseline: "
            + ", ".join(f"{tool}={sum(counts.values())}" for tool, counts in current.items())
        )
        return 0

    if not BASELINE_PATH.exists():
        print(f"Missing baseline: {BASELINE_PATH}", file=sys.stderr)
        return 2
    baseline = load_baseline()
    regressions: list[tuple[str, str, int, int]] = []
    for tool, counts in current.items():
        for key, (actual, allowed) in compare_counts(counts, baseline.get(tool, Counter())).items():
            regressions.append((tool, key, actual, allowed))
    if regressions:
        print("New Python quality violations exceed the committed baseline:", file=sys.stderr)
        for tool, key, actual, allowed in sorted(regressions)[:100]:
            print(f"  {tool}: {key}: actual={actual}, allowed={allowed}", file=sys.stderr)
        return 1
    print(
        "Python quality baseline passed: "
        + ", ".join(f"{tool}={sum(counts.values())}" for tool, counts in current.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
