from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "dev" / "run_api_pytest.ps1"


def test_api_pytest_runner_uses_only_the_canonical_root_runtime() -> None:
    source = RUNNER.read_text(encoding="utf-8")

    assert '.venv\\Scripts\\python.exe' in source
    assert "--git-common-dir" in source
    assert 'apps\\api' in source
    assert 'import pytest, pytest_asyncio' in source
    assert "^apps[\\\\/]api[\\\\/]" in source
    assert "^scripts[\\\\/]" in source
    assert "Push-Location -LiteralPath $apiRoot" in source
    assert "$apiRoot, $repoRoot -join [IO.Path]::PathSeparator" in source
    assert '-m pytest @normalizedArgs' in source
    assert '$normalizedArgs = @(' in source
    assert "poetry" not in source.lower()
    assert "uv sync" not in source.lower()
