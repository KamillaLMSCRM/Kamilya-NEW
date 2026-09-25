from __future__ import annotations

import os

import pytest

from scripts.ops.with_project_github_token import (
    _credential_environment,
    _read_github_token,
)


def test_reads_only_root_github_token_without_echoing_other_values(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "UNRELATED=leave-me-alone\nGITHUB_TOKEN = 'github-project-token'\n",
        encoding="utf-8",
    )

    assert _read_github_token(env_file) == "github-project-token"


def test_missing_project_token_fails_closed(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("GH_TOKEN=ambient-token\n", encoding="utf-8")

    with pytest.raises(ValueError, match="project_github_token_missing"):
        _read_github_token(env_file)


def test_project_environment_removes_ambient_gh_precedence(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "wrong-account")
    monkeypatch.setenv("GITHUB_TOKEN", "stale-project-token")
    monkeypatch.setenv("UNCHANGED", "yes")

    environment = _credential_environment("exact-project-token")

    assert "GH_TOKEN" not in environment
    assert environment["GITHUB_TOKEN"] == "exact-project-token"
    assert environment["UNCHANGED"] == "yes"
    assert os.environ["GH_TOKEN"] == "wrong-account"
