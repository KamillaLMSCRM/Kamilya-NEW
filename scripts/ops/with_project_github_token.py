#!/usr/bin/env python3
"""Run one GitHub command with the canonical Kamilya repository token.

The token is read from the main checkout ``.env`` resolved through Git's
common directory.  It is injected only into the child process and is never
printed, written to Git configuration, or inherited from an ambient account.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path


EXPECTED_ORIGIN = "https://github.com/kamillalmscrm/kamilya-new.git"
_TOKEN_LINE = re.compile(r"^\s*(?:export\s+)?GITHUB_TOKEN\s*=\s*(.*?)\s*$")


def _read_github_token(env_file: Path) -> str:
    if not env_file.is_file():
        raise ValueError("project_env_missing")
    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        match = _TOKEN_LINE.match(line)
        if match is None:
            continue
        value = match.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if value:
            return value
    raise ValueError("project_github_token_missing")


def _credential_environment(token: str) -> dict[str, str]:
    environment = dict(os.environ)
    # gh gives GH_TOKEN precedence over GITHUB_TOKEN.  Remove ambient identity
    # so only the repository-owned credential can be selected by the child.
    environment.pop("GH_TOKEN", None)
    environment["GITHUB_TOKEN"] = token
    return environment


def _git_text(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _canonical_checkout(repo: Path) -> Path:
    common = Path(_git_text(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    return common.resolve().parent


def _normalized_origin(repo: Path) -> str:
    value = _git_text(repo, "remote", "get-url", "origin").strip().lower()
    if value.startswith("git@github.com:"):
        value = "https://github.com/" + value.removeprefix("git@github.com:")
    return value.rstrip("/")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a command is required after --")

    repo = Path(_git_text(args.repo, "rev-parse", "--show-toplevel")).resolve()
    if _normalized_origin(repo) != EXPECTED_ORIGIN:
        raise ValueError("unexpected_kamilya_origin")
    canonical_checkout = _canonical_checkout(repo)
    token = _read_github_token(canonical_checkout / ".env")
    completed = subprocess.run(
        command,
        cwd=repo,
        env=_credential_environment(token),
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
