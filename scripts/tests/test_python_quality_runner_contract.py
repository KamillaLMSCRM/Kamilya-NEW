from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "dev" / "run_python_quality_baseline.ps1"


def test_python_quality_runner_uses_only_the_canonical_root_runtime() -> None:
    source = RUNNER.read_text(encoding="utf-8")

    assert '.venv\\Scripts\\python.exe' in source
    assert "--git-common-dir" in source
    assert "Push-Location -LiteralPath $repoRoot" in source
    assert "& $canonicalPython -m ruff --version" in source
    assert "& $canonicalPython -m mypy --version" in source
    assert "& $canonicalPython scripts/ci/python_quality_baseline.py" in source
    assert "poetry" not in source.lower()
    assert "uv sync" not in source.lower()
