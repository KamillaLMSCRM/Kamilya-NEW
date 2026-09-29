#!/usr/bin/env python3
"""Verify migration 0168 against a disposable Supabase DEV schema."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from kb_rag_isolated_dev_gate import (
    API_ROOT,
    GateBlocked,
    assert_sanitized_evidence,
    file_sha256,
    normalize_database_url,
    public_revision,
    same_supabase_project,
    scalar,
    supabase_project_ref,
)
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

MIGRATION_PATH = (
    API_ROOT / "alembic" / "versions" / "0168_privacy_processing_audit_immutability.py"
)
SCHEMA_RE = re.compile(r"^privacy_audit_[0-9a-f]{12}$")


def safe_schema_name(value: str) -> str:
    if not SCHEMA_RE.fullmatch(value):
        raise GateBlocked("unsafe_schema_name")
    return value


def _migration_module():
    spec = importlib.util.spec_from_file_location("privacy_audit_0168", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise GateBlocked("migration_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def apply_0168(connection: AsyncConnection, schema: str) -> None:
    safe_schema_name(schema)
    await connection.execute(text(f'SET search_path TO "{schema}", public'))
    migration = _migration_module()

    def run(sync_connection) -> None:
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        context = MigrationContext.configure(
            sync_connection,
            opts={"version_table_schema": schema},
        )
        with Operations.context(context):
            migration.upgrade()

    await connection.run_sync(run)


async def cleanup_isolated_schema(engine: Any, schema: str) -> bool:
    safe_schema_name(schema)
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await connection.commit()
            return not bool(
                await scalar(
                    connection,
                    "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:schema)",
                    schema=schema,
                )
            )
    except Exception:
        return False


async def _assert_privilege_denied(
    connection: AsyncConnection,
    statement: str,
    *,
    unexpected: str,
) -> None:
    denied = False
    try:
        async with connection.begin_nested():
            await connection.execute(text(statement))
    except Exception as exc:
        original = getattr(exc, "orig", None)
        sqlstate = getattr(original, "sqlstate", None) or getattr(
            original, "pgcode", None
        )
        if sqlstate != "42501":
            raise GateBlocked(f"{unexpected}_wrong_failure") from None
        denied = True
    if not denied:
        raise GateBlocked(unexpected)


async def run_gate(
    owner_url: str,
    runtime_url: str,
    supabase_url: str,
    schema: str,
) -> dict[str, Any]:
    safe_schema_name(schema)
    if not all(
        same_supabase_project(url, supabase_url) for url in (owner_url, runtime_url)
    ):
        raise GateBlocked("database_and_supabase_project_mismatch")
    if make_url(runtime_url).username.split(".")[0] != "lms_app":
        raise GateBlocked("wrong_runtime_role")
    if any(make_url(url).database != "postgres" for url in (owner_url, runtime_url)):
        raise GateBlocked("unexpected_database")

    options = {"poolclass": NullPool, "pool_pre_ping": True, "hide_parameters": True}
    owner_engine = create_async_engine(owner_url, **options)
    runtime_engine = create_async_engine(runtime_url, **options)
    stage = "preflight"
    created = False
    cleanup_ok = False
    failure: Exception | None = None
    started_at = datetime.now(UTC)
    public_before: str | None = None
    checks: dict[str, bool] = {}
    table = f'"{schema}".audit_logs'
    try:
        async with owner_engine.connect() as connection:
            public_before = await public_revision(connection)
            if await scalar(
                connection,
                "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:schema)",
                schema=schema,
            ):
                raise GateBlocked("disposable_schema_already_exists")
            stage = "create_isolated_ledger"
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(
                text(f'GRANT USAGE ON SCHEMA "{schema}" TO lms_app')
            )
            await connection.execute(
                text(
                    f"CREATE TABLE {table} ("
                    "id uuid PRIMARY KEY, tenant_id uuid NOT NULL, "
                    "details jsonb NOT NULL DEFAULT '{}')"
                )
            )
            await connection.execute(
                text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO lms_app")
            )
            await connection.commit()
            created = True

            stage = "apply_actual_0168"
            await apply_0168(connection, schema)
            await connection.commit()
            privileges = {
                name: bool(
                    await scalar(
                        connection,
                        "SELECT has_table_privilege('lms_app', :table, :privilege)",
                        table=f"{schema}.audit_logs",
                        privilege=name,
                    )
                )
                for name in ("SELECT", "INSERT", "UPDATE", "DELETE")
            }
            expected_privileges = {
                "SELECT": True,
                "INSERT": True,
                "UPDATE": False,
                "DELETE": False,
            }
            if privileges != expected_privileges:
                raise GateBlocked("unexpected_runtime_privileges")

        synthetic_id = uuid.uuid4()
        synthetic_tenant = uuid.uuid4()
        async with runtime_engine.connect() as connection:
            stage = "runtime_append_only"
            identity = (
                await connection.execute(
                    text(
                        "SELECT current_user, rolsuper, rolbypassrls "
                        "FROM pg_roles WHERE rolname=current_user"
                    )
                )
            ).one_or_none()
            if identity != ("lms_app", False, False):
                raise GateBlocked("lms_app_not_non_bypass_runtime_role")
            await connection.execute(
                text(f"INSERT INTO {table} (id, tenant_id) VALUES (:id, :tenant_id)"),
                {"id": synthetic_id, "tenant_id": synthetic_tenant},
            )
            if await scalar(connection, f"SELECT count(*) FROM {table}") != 1:
                raise GateBlocked("runtime_insert_or_read_failed")
            await _assert_privilege_denied(
                connection,
                f"UPDATE {table} SET details='{{}}'::jsonb WHERE id='{synthetic_id}'",
                unexpected="runtime_update_succeeded",
            )
            await _assert_privilege_denied(
                connection,
                f"DELETE FROM {table} WHERE id='{synthetic_id}'",
                unexpected="runtime_delete_succeeded",
            )
            await connection.rollback()

        async with owner_engine.connect() as connection:
            if await public_revision(connection) != public_before:
                raise GateBlocked("public_alembic_revision_changed")
        checks = {
            "actual_0168_applied_with_alembic_operations": True,
            "lms_app_non_superuser_nobypassrls": True,
            "runtime_insert_select_allowed": True,
            "runtime_update_denied": True,
            "runtime_delete_denied": True,
            "public_revision_unchanged": True,
        }
    except Exception as exc:
        failure = exc
    finally:
        if created:
            cleanup_ok = await cleanup_isolated_schema(owner_engine, schema)
        await runtime_engine.dispose()
        await owner_engine.dispose()

    if failure is not None:
        detail = (
            str(failure)
            if isinstance(failure, GateBlocked)
            else type(failure).__name__
        )
        cleanup = "passed" if cleanup_ok else ("not_owned" if not created else "failed")
        raise GateBlocked(f"stage={stage};cause={detail};cleanup={cleanup}") from None
    if not cleanup_ok:
        raise GateBlocked(f"cleanup_failed_at:{stage}")

    evidence = {
        "status": "PASSED",
        "evidence_labels": ["RUNTIME-DERIVED"],
        "scope": "isolated_supabase_dev_privacy_audit",
        "executed_at": started_at.isoformat().replace("+00:00", "Z"),
        "project_ref_sha256": hashlib.sha256(
            supabase_project_ref(supabase_url).encode("ascii")
        ).hexdigest(),
        "migration_sha256": file_sha256(MIGRATION_PATH),
        "disposable_schema_digest": hashlib.sha256(schema.encode("ascii")).hexdigest(),
        "checks": checks,
    }
    assert_sanitized_evidence(evidence)
    return evidence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.execute:
        print(json.dumps({"status": "BLOCKED", "error_class": "execute_flag_required"}))
        return 2
    config = dotenv_values(args.env_file)
    owner_url = normalize_database_url(config.get("MIGRATION_DATABASE_URL") or "")
    runtime_url = normalize_database_url(config.get("DATABASE_URL") or "")
    supabase_url = config.get("SUPABASE_URL") or ""
    if not owner_url or not runtime_url or not supabase_url:
        print(json.dumps({"status": "BLOCKED", "error_class": "required_env_missing"}))
        return 2
    schema = f"privacy_audit_{uuid.uuid4().hex[:12]}"
    try:
        result = asyncio.run(run_gate(owner_url, runtime_url, supabase_url, schema))
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "error_class": type(exc).__name__,
                    "reason": str(exc)
                    if isinstance(exc, GateBlocked)
                    else "sanitized_unexpected_error",
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
