"""Fail closed when a write-capable task starts in the shared primary checkout."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


SCHEMA_VERSION = "kamilya-primary-checkout-guard-v1"


def git(repo: Path, *args: str, required: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if required and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise RuntimeError(message)
    return result.stdout.strip()


def same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(
        os.path.realpath(right)
    )


def inspect(repo: Path) -> dict[str, object]:
    current_root = Path(
        git(repo, "rev-parse", "--path-format=absolute", "--show-toplevel")
    ).resolve()
    common_dir = Path(
        git(current_root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    ).resolve()
    if common_dir.name.lower() != ".git":
        raise RuntimeError(f"unsupported Git common directory: {common_dir}")
    primary_root = common_dir.parent.resolve()
    primary_head = git(primary_root, "rev-parse", "HEAD")
    origin_master = git(
        primary_root,
        "rev-parse",
        "--verify",
        "refs/remotes/origin/master",
        required=False,
    )
    primary_branch = git(
        primary_root, "symbolic-ref", "--quiet", "--short", "HEAD", required=False
    )
    changes = git(
        primary_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    ).splitlines()
    primary_clean = not changes
    primary_aligned = bool(origin_master) and primary_head == origin_master
    primary_on_master = primary_branch == "master"
    return {
        "schema_version": SCHEMA_VERSION,
        "current_root": str(current_root),
        "primary_root": str(primary_root),
        "current_is_primary": same_path(current_root, primary_root),
        "current_head": git(current_root, "rev-parse", "HEAD"),
        "primary_head": primary_head,
        "origin_master": origin_master or None,
        "primary_branch": primary_branch or None,
        "primary_clean": primary_clean,
        "primary_aligned": primary_aligned,
        "primary_on_master": primary_on_master,
        "change_count": len(changes),
        "changes": changes[:50],
        "changes_truncated": len(changes) > 50,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--mode", choices=("write", "primary-status"), default="write"
    )
    args = parser.parse_args()

    try:
        payload = inspect(args.repo)
    except (OSError, RuntimeError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "GUARD_ERROR",
                    "write_allowed": False,
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 4

    if args.mode == "write":
        if payload["current_is_primary"]:
            payload.update(
                status="PRIMARY_WRITE_FORBIDDEN",
                write_allowed=False,
                next="create_or_reuse_linked_worktree",
            )
            exit_code = 3
        else:
            payload.update(status="LINKED_WORKTREE_OK", write_allowed=True)
            exit_code = 0
    else:
        healthy = bool(
            payload["primary_clean"]
            and payload["primary_aligned"]
            and payload["primary_on_master"]
        )
        payload.update(
            status="PRIMARY_OK" if healthy else "PRIMARY_NEEDS_HYGIENE",
            write_allowed=False,
        )
        exit_code = 0 if healthy else 2

    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
