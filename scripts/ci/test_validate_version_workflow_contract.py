"""Deterministic workflow-contract tests for the version-consistency CI gate.

Prove, without network or production access, that the GitHub workflow invokes
scripts/validate_version.py (stdlib-only, in release-security-gates) and its
focused tests (inside backend-unit, where pytest is installed via Poetry), so
version or changelog disagreement fails CI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
VALIDATOR = REPO_ROOT / "scripts" / "validate_version.py"


def _job_body(workflow_text: str, job_key: str) -> str:
    start = workflow_text.index(f"{job_key}:")
    next_keys = [
        m.start() for m in re.finditer(r"\n  [\w-]+:", workflow_text[start + 1 :])
    ]
    end = start + 1 + next_keys[0] if next_keys else len(workflow_text)
    return workflow_text[start:end]


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_file_exists() -> None:
    assert WORKFLOW.is_file(), ".github/workflows/ci.yml missing"


def test_validator_gate_is_in_release_security_gates(workflow_text: str) -> None:
    job_body = _job_body(workflow_text, "release-security-gates")
    assert re.search(r"python\s+scripts/validate_version\.py\b", job_body), (
        "release-security-gates must run the stdlib-only validator"
    )
    invocations = [
        line for line in job_body.splitlines() if "run:" in line or "run |" in line
    ]
    pytest_invocations = [line for line in invocations if "pytest" in line]
    assert not pytest_invocations, (
        "release-security-gates has no pytest dependency; "
        f"it must stay stdlib-only, found: {pytest_invocations}"
    )


def test_focused_tests_are_in_backend_unit(workflow_text: str) -> None:
    job_body = _job_body(workflow_text, "backend-unit")
    assert re.search(
        r"poetry run pytest -q\s+.*\.\./\.\./scripts/tests/test_validate_version\.py",
        job_body,
    ), "backend-unit must run the focused validator tests via poetry pytest"
    assert (
        "test_validate_version_workflow_contract.py" in job_body
    ), "backend-unit must also run the workflow-contract tests"
    install_at = job_body.find("poetry install --no-interaction --no-ansi --with dev")
    tests_at = job_body.find("poetry run pytest -q ../../scripts/tests/test_validate_version.py")
    assert install_at != -1 and tests_at != -1 and install_at < tests_at, (
        "focused tests must run after poetry install in backend-unit"
    )


def test_validator_module_reusable_and_main_returns_int() -> None:
    import sys

    sys.path.insert(0, str(VALIDATOR.parent))
    import validate_version

    assert callable(validate_version.validate)
    assert callable(validate_version.main)


def test_validator_main_exits_nonzero_on_version_mismatch(tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(VALIDATOR.parent))
    import validate_version

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    (repo / "apps" / "api").mkdir(parents=True)
    (repo / "apps" / "api" / "pyproject.toml").write_text(
        "[tool.poetry]\nversion = '0.1.0'\n", encoding="utf-8"
    )
    (repo / "apps" / "web").mkdir(parents=True)
    (repo / "apps" / "web" / "package.json").write_text(
        '{"name": "web", "version": "0.1.0"}', encoding="utf-8"
    )
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n", encoding="utf-8"
    )
    assert validate_version.main([str(VALIDATOR), str(repo)]) == 1


def test_validator_main_exits_nonzero_on_missing_unreleased(tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(VALIDATOR.parent))
    import validate_version

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (repo / "apps" / "api").mkdir(parents=True)
    (repo / "apps" / "api" / "pyproject.toml").write_text(
        "[tool.poetry]\nversion = '0.1.0'\n", encoding="utf-8"
    )
    (repo / "apps" / "web").mkdir(parents=True)
    (repo / "apps" / "web" / "package.json").write_text(
        '{"name": "web", "version": "0.1.0"}', encoding="utf-8"
    )
    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## [1.0.0]\n", encoding="utf-8")
    assert validate_version.main([str(VALIDATOR), str(repo)]) == 1


def test_validator_main_exits_zero_on_consistent_repo(tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(VALIDATOR.parent))
    import validate_version

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (repo / "apps" / "api").mkdir(parents=True)
    (repo / "apps" / "api" / "pyproject.toml").write_text(
        "[tool.poetry]\nversion = '0.1.0'\n", encoding="utf-8"
    )
    (repo / "apps" / "web").mkdir(parents=True)
    (repo / "apps" / "web" / "package.json").write_text(
        '{"name": "web", "version": "0.1.0"}', encoding="utf-8"
    )
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n", encoding="utf-8"
    )
    assert validate_version.main([str(VALIDATOR), str(repo)]) == 0
