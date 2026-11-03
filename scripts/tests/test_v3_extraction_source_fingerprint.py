"""Offline coverage for the V3 checkpoint source manifest."""
from __future__ import annotations

from pathlib import Path

from scripts.ops import v3_extraction_checkpoint_dev_check as gate


def test_source_manifest_covers_project_python_and_exact_executed_support():
    root = Path(gate.ROOT)
    listed = tuple(gate.base.SOURCE_PATHS)
    expected_app = {
        path.relative_to(root).as_posix()
        for path in (root / "apps" / "api" / "app").rglob("*.py")
    }
    expected_support = set(gate._EXECUTED_SUPPORT_PATHS)

    assert listed == tuple(sorted(set(listed)))
    assert expected_app <= set(listed)
    assert expected_support <= set(listed)
    assert "scripts/ops/v3_gate_timing.py" in expected_support
    assert all(path.startswith("apps/api/app/") or path in expected_support for path in listed)
    assert not any(".venv" in path or "site-packages" in path for path in listed)


def test_source_manifest_digest_is_stable_without_runtime_or_database_access():
    first = gate.base.source_digest()
    second = gate.base.source_digest()
    assert first == second and len(first) == 64
