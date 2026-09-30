from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "scripts" / "dev" / "check_primary_checkout.py"


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run("git", "-C", str(repo), *args)


def initialize_repository(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    assert git(repo, "init", "-b", "master").returncode == 0
    assert git(repo, "config", "user.name", "Kamilya Test").returncode == 0
    assert git(repo, "config", "user.email", "test@example.invalid").returncode == 0
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    assert git(repo, "add", "README.md").returncode == 0
    assert git(repo, "commit", "-m", "fixture").returncode == 0
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    assert git(repo, "update-ref", "refs/remotes/origin/master", head).returncode == 0
    return repo


def invoke(repo: Path, mode: str = "write") -> subprocess.CompletedProcess[str]:
    return run(
        sys.executable,
        str(GUARD),
        "--repo",
        str(repo),
        "--mode",
        mode,
    )


def test_write_mode_blocks_the_primary_checkout(tmp_path: Path) -> None:
    repo = initialize_repository(tmp_path)

    result = invoke(repo)

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["status"] == "PRIMARY_WRITE_FORBIDDEN"
    assert payload["write_allowed"] is False
    assert payload["primary_clean"] is True
    assert payload["primary_aligned"] is True


def test_write_mode_allows_a_linked_worktree(tmp_path: Path) -> None:
    repo = initialize_repository(tmp_path)
    worktree = tmp_path / "task-worktree"
    assert git(repo, "worktree", "add", "-b", "task/test", str(worktree), "HEAD").returncode == 0

    result = invoke(worktree)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "LINKED_WORKTREE_OK"
    assert payload["write_allowed"] is True
    assert Path(payload["primary_root"]).resolve() == repo.resolve()


def test_primary_status_reports_untracked_and_behind_state(tmp_path: Path) -> None:
    repo = initialize_repository(tmp_path)
    (repo / "leftover.txt").write_text("unfinished\n", encoding="utf-8")
    initial_head = git(repo, "rev-parse", "HEAD").stdout.strip()
    assert git(repo, "commit", "--allow-empty", "-m", "remote advance").returncode == 0
    remote_head = git(repo, "rev-parse", "HEAD").stdout.strip()
    assert git(repo, "update-ref", "refs/remotes/origin/master", remote_head).returncode == 0
    assert git(repo, "reset", "--soft", initial_head).returncode == 0

    result = invoke(repo, mode="primary-status")

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "PRIMARY_NEEDS_HYGIENE"
    assert payload["primary_clean"] is False
    assert payload["primary_aligned"] is False
    assert "?? leftover.txt" in payload["changes"]


def test_project_rules_require_the_executable_write_gate() -> None:
    rules = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "check_primary_checkout.py --mode write" in rules
    assert "PRIMARY_WRITE_FORBIDDEN" in rules


def test_ci_runs_repository_hygiene_contracts() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "Repository hygiene contract tests" in workflow
    assert "../../scripts/tests/test_primary_checkout_guard.py" in workflow
    assert "../../scripts/tests/test_governance_contracts.py" in workflow
