from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[4] / "scripts" / "ci" / "python_quality_baseline.py"
SPEC = importlib.util.spec_from_file_location("python_quality_baseline", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
quality_baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality_baseline)


def test_seeded_new_violation_exceeds_baseline() -> None:
    baseline = Counter({"app/example.py|F401": 2})
    seeded_current = Counter({"app/example.py|F401": 3})

    assert quality_baseline.compare_counts(seeded_current, baseline) == {
        "app/example.py|F401": (3, 2)
    }


def test_seeded_new_violation_makes_cli_gate_red(monkeypatch, tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(quality_baseline, "BASELINE_PATH", baseline_path)
    monkeypatch.setattr(
        quality_baseline,
        "collect_current",
        lambda: {"ruff": Counter({"app/example.py|F401": 2}), "mypy": Counter()},
    )
    monkeypatch.setattr(
        quality_baseline,
        "load_baseline",
        lambda: {"ruff": Counter({"app/example.py|F401": 1}), "mypy": Counter()},
    )
    monkeypatch.setattr(sys, "argv", ["python_quality_baseline.py"])

    assert quality_baseline.main() == 1


def test_reducing_legacy_debt_does_not_fail_gate() -> None:
    baseline = Counter({"app/example.py|F401": 2, "app/legacy.py|E402": 4})
    improved_current = Counter({"app/example.py|F401": 1, "app/legacy.py|E402": 4})

    assert quality_baseline.compare_counts(improved_current, baseline) == {}


def test_mypy_json_summary_is_stable_across_line_movement() -> None:
    first = '{"file":"app/example.py","line":2,"severity":"error","code":"arg-type"}'
    moved = '{"file":"app/example.py","line":200,"severity":"error","code":"arg-type"}'

    assert quality_baseline.summarize_mypy(first) == quality_baseline.summarize_mypy(moved)
