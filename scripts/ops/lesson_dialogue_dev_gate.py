#!/usr/bin/env python3
"""Owned Supabase DEV proof for private durable lesson dialogue migration 0179.

This driver owns one random ``workbench_<12hex>`` schema, uses a fake provider,
and never writes to ``public``.  It deliberately reuses the established
workbench identity, public-snapshot, clone, runtime-role and cleanup seams.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
API_ROOT = ROOT / "apps" / "api"
OPS_ROOT = ROOT / "scripts" / "ops"
for path in (API_ROOT, OPS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import event, text  # noqa: E402
from sqlalchemy.engine import Connection, make_url  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from workbench_correction_application_dev_gate import (  # noqa: E402
    clone_application_tables,
)
from workbench_document_dev_gate import (  # noqa: E402
    GateBlocked,
    assert_sanitized_evidence,
    canonical_config,
    cleanup,
    public_snapshot,
    safe_schema,
    same_supabase_project,
    sanitize_failure,
    set_context,
    verify_runtime_role,
)

MIGRATION = API_ROOT / "alembic" / "versions" / "0179_ai_lesson_dialogue.py"
CHECKS = OPS_ROOT / "lesson_dialogue_dev_checks.py"
SERVICE = API_ROOT / "app" / "modules" / "ai" / "lesson_dialogue.py"
MODEL = API_ROOT / "app" / "modules" / "ai" / "dialogue_models.py"
EXPIRY_CLOCK_EVIDENCE = "DETERMINISTIC_APP_CLOCK_PLUS_11_MINUTES"

# Freeze the complete safety and feature boundary.  A result is invalid if Root
# edits any of these files while a long real-DEV run is in progress.
CRITICAL_SOURCES = (
    Path(__file__).resolve(),
    CHECKS,
    MIGRATION,
    SERVICE,
    MODEL,
    API_ROOT / "app" / "modules" / "ai" / "schemas.py",
    API_ROOT / "app" / "modules" / "ai" / "router.py",
    API_ROOT / "app" / "modules" / "admin" / "superadmin" / "service.py",
    ROOT
    / "docs/product/contract-modules/methodologist-workbench/contracts"
    / "EDITOR_DURABLE_LESSON_DIALOGUE_PURGE_V1.md",
    ROOT
    / "docs/product/contract-modules/methodologist-workbench/contracts"
    / "EDITOR_DURABLE_LESSON_DIALOGUE_V1.md",
    ROOT
    / "docs/product/contract-modules/methodologist-workbench/contracts"
    / "EDITOR_DURABLE_LESSON_DIALOGUE_V1_1.md",
    OPS_ROOT / "workbench_document_dev_gate.py",
    OPS_ROOT / "workbench_correction_dev_gate.py",
    OPS_ROOT / "workbench_correction_application_dev_gate.py",
)

REQUIRED_CHECKS = frozenset(
    {
        "empty_upgrade_downgrade_reupgrade",
        "table_acl_force_rls",
        "no_context_denied",
        "foreign_tenant_denied",
        "sibling_actor_denied",
        "moved_scope_refused",
        "role_revocation_denied",
        "terminal_immutable",
        "sequential_replay_one_fake_call",
        "changed_body_conflict",
        "concurrent_pending_dedup",
        "late_completion_refused",
        "provider_connection_released",
        "history_read_no_model",
        "refusal_excluded_context_bounded",
        "scoped_history_paging",
        "fk_cascade",
        "purge_source_order",
        "guarded_tenant_purge_visibility",
        "populated_downgrade_refused",
        "same_tenant_move_interrupted",
        "absent_target_interrupted_no_inference",
        "expired_pending_get_interrupted",
        "sibling_api_private",
        "foreign_api_private",
        "different_language_api_empty",
        "bounded_connection_peak",
    }
)


def validate_checks(checks: list[str]) -> None:
    if set(checks) != REQUIRED_CHECKS or len(checks) != len(set(checks)):
        raise GateBlocked("required_checks_missing")


def source_manifest() -> dict[str, str]:
    manifest: dict[str, str] = {}
    for source in CRITICAL_SOURCES:
        resolved = source.resolve()
        if not resolved.is_file() or ROOT.resolve() not in resolved.parents:
            raise GateBlocked("critical_source_missing")
        key = resolved.relative_to(ROOT).as_posix()
        if key in manifest:
            raise GateBlocked("duplicate_critical_source")
        manifest[key] = hashlib.sha256(resolved.read_bytes()).hexdigest()
    return manifest


def failure_detail(exc: BaseException) -> dict[str, Any]:
    """Return only a safe source location and SQLSTATE, never SQL or values."""
    detail: dict[str, Any] = {}
    cause: BaseException | None = exc
    for _ in range(4):
        code = getattr(getattr(cause, "orig", None), "sqlstate", None)
        if isinstance(code, str) and re.fullmatch(r"[A-Z0-9]{5}", code):
            detail["state"] = code
            break
        cause = getattr(cause, "__cause__", None) or getattr(cause, "__context__", None)
        if cause is None:
            break
    allowed = {path.resolve() for path in CRITICAL_SOURCES}
    frame = exc.__traceback__
    while frame:
        path = Path(frame.tb_frame.f_code.co_filename).resolve()
        if path in allowed:
            detail.update(file=path.relative_to(ROOT).as_posix(), line=frame.tb_lineno)
        frame = frame.tb_next
    return detail


async def apply_0179(connection: Any, schema: str, operation: str = "upgrade") -> None:
    safe_schema(schema)
    if operation not in {"upgrade", "downgrade"}:
        raise GateBlocked("invalid_migration_request")
    spec = importlib.util.spec_from_file_location("lesson_dialogue_0179", MIGRATION)
    if spec is None or spec.loader is None:
        raise GateBlocked("migration_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.revision != "0179" or module.down_revision != "0178":
        raise GateBlocked("migration_identity_mismatch")

    def apply(sync: Connection) -> None:
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        with Operations.context(
            MigrationContext.configure(sync, opts={"version_table_schema": schema})
        ):
            getattr(module, operation)()

    await connection.run_sync(apply)


async def run_gate(
    owner_url: str,
    runtime_url: str,
    supabase_url: str,
    schema: str,
    *,
    verifier: Any = None,
) -> dict[str, Any]:
    started = monotonic()
    safe_schema(schema)
    if not all(
        same_supabase_project(url, supabase_url) for url in (owner_url, runtime_url)
    ):
        raise GateBlocked("canonical_dev_identity_mismatch")
    if (make_url(runtime_url).username or "").split(".", 1)[0] != "lms_app":
        raise GateBlocked("wrong_runtime_role")
    frozen = source_manifest()
    options = {
        "poolclass": NullPool,
        "hide_parameters": True,
        "connect_args": {
            "timeout": 15,
            "command_timeout": 45,
            "server_settings": {
                "statement_timeout": "45000",
                "lock_timeout": "5000",
            },
        },
    }
    owner_engine = create_async_engine(owner_url, **options)
    runtime_engine = create_async_engine(runtime_url, **options)
    active: set[tuple[str, int]] = set()
    peak = 0

    def checked_out(label: str, connection: Any) -> None:
        nonlocal peak
        active.add((label, id(connection)))
        peak = max(peak, len(active))
        if peak > 3:
            raise GateBlocked("connection_cap_exceeded")

    def checked_in(label: str, connection: Any) -> None:
        active.discard((label, id(connection)))

    for label, engine in (("owner", owner_engine), ("runtime", runtime_engine)):
        event.listen(
            engine.sync_engine,
            "checkout",
            lambda connection, *_args, label=label: checked_out(label, connection),
        )
        event.listen(
            engine.sync_engine,
            "checkin",
            lambda connection, *_args, label=label: checked_in(label, connection),
        )

    @event.listens_for(runtime_engine.sync_engine, "begin")
    def owned_transaction(connection: Any) -> None:
        connection.exec_driver_sql(
            f"SET LOCAL search_path TO {safe_schema(schema)}, pg_catalog"
        )

    owned = False
    cleaned = False
    neutral = False
    before: Any = None
    checks: list[str] = []
    failure = None
    detail: dict[str, Any] = {}
    readback_failure = None
    stage = "identity"
    source_unchanged = False
    try:
        async with runtime_engine.connect() as connection:
            await verify_runtime_role(connection)
        async with owner_engine.connect() as connection:
            before = await public_snapshot(connection)
            collision = await connection.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:s)"),
                {"s": schema},
            )
            if collision:
                raise GateBlocked("schema_collision")
            await connection.execute(text(f"CREATE SCHEMA {safe_schema(schema)}"))
            owned = True
            await connection.execute(
                text(f"REVOKE ALL ON SCHEMA {safe_schema(schema)} FROM PUBLIC")
            )
            await connection.commit()
            stage = "clone_migration"
            await set_context(connection, schema)
            # Canonical catalog-bound clone: exact source columns/defaults/checks,
            # immediate in-schema FKs, synthetic neighbor policies only.
            await clone_application_tables(connection, schema)
            await apply_0179(connection, schema, "upgrade")
            await apply_0179(connection, schema, "downgrade")
            await apply_0179(connection, schema, "upgrade")
            await connection.commit()
            checks.append("empty_upgrade_downgrade_reupgrade")
        stage = "dialogue_transactions"
        if verifier is None:
            from lesson_dialogue_dev_checks import verify_dialogue

            verifier = verify_dialogue
        async with asyncio.timeout(600):
            await verifier(
                owner_engine,
                runtime_engine,
                schema,
                checks,
                runtime_connections=lambda: sum(
                    1 for label, _identity in active if label == "runtime"
                ),
                migration=apply_0179,
            )
        if peak > 3:
            raise GateBlocked("connection_cap_exceeded")
        checks.append("bounded_connection_peak")
        validate_checks(checks)
        source_unchanged = source_manifest() == frozen
        if not source_unchanged:
            raise GateBlocked("critical_source_changed")
    except Exception as exc:
        failure = sanitize_failure(exc)
        detail = failure_detail(exc)
    finally:
        try:
            if owned:
                cleaned = await cleanup(owner_engine, schema)
            if before is not None:
                async with owner_engine.connect() as connection:
                    neutral = before == await public_snapshot(connection)
        except Exception as exc:
            readback_failure = sanitize_failure(exc)
        finally:
            await runtime_engine.dispose()
            await owner_engine.dispose()
    passed = (
        failure is None
        and readback_failure is None
        and cleaned
        and neutral
        and source_unchanged
        and set(checks) == REQUIRED_CHECKS
    )
    result = {
        "status": "PASS" if passed else "BLOCKED",
        "scope": "lesson_dialogue_isolated_dev",
        "migration": "0179",
        "checks": checks,
        "cleanup": cleaned,
        "public_schema_neutral": neutral,
        "source_unchanged": source_unchanged,
        "source_count": len(frozen),
        "source_hashes": frozen,
        "failure": failure,
        "detail": detail,
        "readback_failure": readback_failure,
        "stage": stage,
        "connection_peak": peak,
        "elapsed_seconds": round(monotonic() - started, 3),
        "provider": "FAKE_ONLY",
        "email": "NOT_USED",
        "production": "UNCHANGED",
        "semantic_quality": "NOT_VERIFIED",
        "expired_pending_clock": EXPIRY_CLOCK_EVIDENCE,
        "real_elapsed_ten_minutes": "NOT_VERIFIED",
    }
    assert_sanitized_evidence(result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        common = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if args.env_file.resolve() != (Path(common).parent / ".env").resolve():
            raise GateBlocked("noncanonical_env_file")
        target = (ROOT / ".release-evidence/LESSON-DIALOGUE-DEV-20261014").resolve()
        output = args.evidence.resolve()
        if output.parent != target or output.suffix != ".json" or output.exists():
            raise GateBlocked("invalid_evidence_target")
        config = canonical_config(args.env_file)
        load_dotenv(args.env_file, override=True)
        result = asyncio.run(
            run_gate(
                config["owner_url"],
                config["runtime_url"],
                config["supabase_url"],
                f"workbench_{uuid4().hex[:12]}",
            )
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    except Exception as exc:
        print(
            json.dumps(
                {"status": "BLOCKED", "failure": sanitize_failure(exc)},
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
