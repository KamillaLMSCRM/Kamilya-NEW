#!/usr/bin/env python3
"""Fail-closed public-schema gate for the canonical Supabase DEV contour.

Render Free does not execute pre-deploy commands.  A DEV release that changes
the schema must therefore run this explicit gate before API and worker rollout.
The default mode is read-only. ``--apply`` is required for a mutation. Workbench
Workbench heads0172/0173 require explicit expand169/contract-head phases and compatible readback.
No database URL, host, username, or credential is rendered in the report.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from kb_rag_isolated_dev_gate import (
    normalize_database_url,
    same_supabase_project,
    supabase_project_ref,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"


class GateBlocked(RuntimeError):
    """The requested release cannot prove or safely update the DEV schema."""


def decide_schema_action(current: str, expected: str, *, apply: bool) -> str:
    if current == expected:
        return "verified"
    if not apply:
        raise GateBlocked(f"schema_upgrade_required:{current}:{expected}")
    return "upgrade"


def safe_report(
    *,
    status: str,
    current_revision: str,
    expected_revision: str,
    applied: bool,
    project_ref: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "target": "canonical_supabase_dev_public_schema",
        "current_revision": current_revision,
        "expected_revision": expected_revision,
        "applied": applied,
        "project_ref_sha256": hashlib.sha256(project_ref.encode("ascii")).hexdigest(),
    }


def repository_head() -> str:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise GateBlocked(f"repository_must_have_one_head:{len(heads)}")
    return heads[0]


def phase_target(head: str, phase: str | None) -> str:
    if phase is None:
        return head
    if head not in {"0172", "0173"} or phase not in {"expand", "contract"}:
        raise GateBlocked("unsupported_workbench_phase")
    return "0169" if phase == "expand" else head


def verify_compatibility_receipt(path: Path | None, sha: str | None) -> None:
    """Root-owned immutable readback binding; not a substitute for live release gates."""
    if path is None or sha is None or not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise GateBlocked("compatibility_receipt_required")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise GateBlocked("compatibility_receipt_unreadable") from None
    if not isinstance(receipt, dict) or any(
        receipt.get(key) != value for key, value in {
            "status": "PASS", "scope": "canonical_supabase_dev_compatibility",
            "schema_revision": "0169", "release_sha": sha,
            "api_sha": sha, "worker_sha": sha,
            "api_workbench_enabled": False, "frontend_workbench_enabled": False,
            "auth_bootstrap": "PASS", "workers_startup": "PASS",
        }.items()
    ):
        raise GateBlocked("compatibility_receipt_mismatch")
    # JSON booleans must not be interchangeable with numeric zero.
    if any(receipt.get(key) is not False for key in (
        "api_workbench_enabled", "frontend_workbench_enabled"
    )):
        raise GateBlocked("compatibility_flags_not_explicitly_off")


def verify_phase_path(current: str, head: str, phase: str | None, *, apply: bool) -> None:
    if head not in {"0172", "0173"}:
        return
    allowed = {"expand": {"0168", "0169"}, "contract": {"0169", "0172", head}}
    if phase is not None and current not in allowed[phase]:
        raise GateBlocked("workbench_phase_revision_mismatch")
    if phase is None and apply and current != head:
        raise GateBlocked("workbench_staged_rollout_required")


def resolve_env_file(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    try:
        common_dir = Path(
            subprocess.check_output(
                ["git", "-C", str(REPO_ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                text=True,
            ).strip()
        ).resolve()
    except (OSError, subprocess.CalledProcessError) as error:
        raise GateBlocked("canonical_checkout_could_not_be_resolved") from error
    canonical = common_dir.parent / "apps" / "api" / ".env"
    if not canonical.is_file():
        raise GateBlocked("canonical_dev_environment_file_is_missing")
    return canonical


async def database_revision(database_url: str) -> str:
    engine = create_async_engine(database_url, poolclass=NullPool, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            revisions = list(
                (
                    await connection.execute(
                        text("SELECT version_num FROM alembic_version ORDER BY version_num")
                    )
                ).scalars()
            )
    finally:
        await engine.dispose()
    if len(revisions) != 1:
        raise GateBlocked(f"database_must_have_one_revision:{len(revisions)}")
    if not re.fullmatch(r"[0-9]{4}", str(revisions[0])):
        raise GateBlocked("database_revision_format_invalid")
    return str(revisions[0])


def load_dev_environment(env_file: Path) -> tuple[dict[str, str], str, str]:
    values = {
        key: value
        for key, value in dotenv_values(env_file).items()
        if value is not None
    }
    owner_url = normalize_database_url(values.get("MIGRATION_DATABASE_URL", ""))
    runtime_url = normalize_database_url(values.get("DATABASE_URL", ""))
    supabase_url = values.get("SUPABASE_URL", "")
    if not owner_url or not runtime_url or not supabase_url:
        raise GateBlocked("canonical_dev_environment_is_incomplete")
    if not same_supabase_project(owner_url, supabase_url):
        raise GateBlocked("migration_database_is_not_canonical_supabase_dev")
    if not same_supabase_project(runtime_url, supabase_url):
        raise GateBlocked("runtime_database_is_not_canonical_supabase_dev")
    return values, owner_url, supabase_project_ref(supabase_url)


def run_upgrade(values: dict[str, str], owner_url: str, target: str = "head") -> None:
    environment = os.environ.copy()
    environment.update(values)
    environment["DATABASE_URL"] = owner_url
    environment["MIGRATION_DATABASE_URL"] = owner_url
    environment["PYTHONPATH"] = "."
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", target],
        cwd=API_ROOT,
        env=environment,
        check=True,
        capture_output=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--workbench-phase", choices=("expand", "contract"))
    parser.add_argument("--compatibility-evidence", type=Path)
    parser.add_argument("--compatibility-sha")
    parser.add_argument(
        "--expected-revision",
        help="Optional exact assertion of the selected target (head by default).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the exact selected target; workbench0172/0173 requires staged phases.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        head = repository_head()
        expected = phase_target(head, args.workbench_phase)
        if args.workbench_phase == "contract":
            verify_compatibility_receipt(args.compatibility_evidence, args.compatibility_sha)
        if args.expected_revision and args.expected_revision != expected:
            raise GateBlocked(
                f"expected_revision_does_not_match_repository_head:{args.expected_revision}:{expected}"
            )
        values, owner_url, project_ref = load_dev_environment(resolve_env_file(args.env_file))
        current = asyncio.run(database_revision(owner_url))
        verify_phase_path(current, head, args.workbench_phase, apply=args.apply)
        action = decide_schema_action(current, expected, apply=args.apply)
        applied = action == "upgrade"
        if applied:
            run_upgrade(values, owner_url, expected)
            current = asyncio.run(database_revision(owner_url))
            if current != expected:
                raise GateBlocked(f"schema_readback_mismatch:{current}:{expected}")
        print(
            json.dumps(
                safe_report(
                    status="EXPANDED_NOT_FINAL" if args.workbench_phase == "expand" else "PASS",
                    current_revision=current,
                    expected_revision=expected,
                    applied=applied,
                    project_ref=project_ref,
                ),
                sort_keys=True,
            )
        )
        return 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "target": "canonical_supabase_dev_public_schema",
                    "reason": str(error) if isinstance(error, GateBlocked) else (
                        "migration_subprocess_failed" if isinstance(error, subprocess.CalledProcessError)
                        else f"schema_gate_failed:{type(error).__name__}"
                    ),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
