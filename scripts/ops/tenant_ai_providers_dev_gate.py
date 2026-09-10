#!/usr/bin/env python3
"""Run the tenant-AI-provider RLS gate in an isolated Supabase DEV schema.

This command is deliberately opt-in. It uses only synthetic UUIDs, the
existing ``lms_app`` role, and a disposable schema; it never migrates or
writes public objects.
"""
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

MIGRATION_PATH = API_ROOT / "alembic" / "versions" / "0157_tenant_ai_providers.py"
SCHEMA_RE = re.compile(r"^byok_tap_[0-9a-f]{12}$")


def safe_schema_name(value: str) -> str:
    if not SCHEMA_RE.fullmatch(value):
        raise GateBlocked("unsafe_schema_name")
    return value


def _migration_module():
    spec = importlib.util.spec_from_file_location("tenant_ai_providers_0157", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise GateBlocked("migration_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_0157_schema_helper() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    required = (
        'revision = "0157"',
        'down_revision = "0156"',
        'op.get_context().opts.get("version_table_schema")',
        'return f\'"{schema}"\'',
        "CREATE TABLE {table}",
        "FORCE ROW LEVEL SECURITY",
    )
    if any(token not in source for token in required):
        raise GateBlocked("migration_schema_helper_contract_missing")
    if re.search(r"(?:CREATE|ALTER|DROP|GRANT|REVOKE)\s+[^\n;]*\bpublic\.", source, re.I):
        raise GateBlocked("migration_hard_codes_public")


async def apply_0157(connection: AsyncConnection, schema: str) -> None:
    """Apply the actual migration body with an Alembic Operations context."""
    safe_schema_name(schema)
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


async def verify_runtime_role(connection: AsyncConnection) -> None:
    attributes = (
        await connection.execute(
            text("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")
        )
    ).one_or_none()
    if attributes != ("lms_app", False, False):
        raise GateBlocked("lms_app_not_non_bypass_runtime_role")


async def _set_tenant_context(connection: AsyncConnection, tenant_id: uuid.UUID | None) -> None:
    await connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": "" if tenant_id is None else str(tenant_id)},
    )


async def cleanup_isolated_schema(engine: Any, schema: str) -> bool:
    """Drop only this gate's validated disposable schema."""
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


async def run_gate(
    owner_url: str,
    runtime_url: str,
    supabase_url: str,
    schema: str,
) -> dict[str, Any]:
    safe_schema_name(schema)
    assert_0157_schema_helper()
    if not all(same_supabase_project(url, supabase_url) for url in (owner_url, runtime_url)):
        raise GateBlocked("database_and_supabase_project_mismatch")
    if make_url(runtime_url).username.split(".")[0] != "lms_app":
        raise GateBlocked("wrong_runtime_role")
    if any(make_url(url).database != "postgres" for url in (owner_url, runtime_url)):
        raise GateBlocked("unexpected_database")

    engine_options = {"poolclass": NullPool, "pool_pre_ping": True, "hide_parameters": True}
    owner_engine = create_async_engine(owner_url, **engine_options)
    runtime_engine = create_async_engine(runtime_url, **engine_options)
    stage = "preflight"
    cleanup_ok = False
    created_owned = False
    failure: Exception | None = None
    started_at = datetime.now(UTC)
    checks: dict[str, Any] = {}
    try:
        async with runtime_engine.connect() as runtime_connection:
            stage = "verify_runtime_lms_app_identity"
            await verify_runtime_role(runtime_connection)
        async with owner_engine.connect() as connection:
            public_before = await public_revision(connection)
            if await scalar(
                connection,
                "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:schema)",
                schema=schema,
            ):
                raise GateBlocked("disposable_schema_already_exists")

            stage = "create_isolated_schema"
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO lms_app'))
            await connection.execute(
                text(f'CREATE TABLE "{schema}".tenants (id uuid PRIMARY KEY)')
            )
            await connection.execute(
                text(f'CREATE TABLE "{schema}".alembic_version (version_num varchar(32) PRIMARY KEY)')
            )
            await connection.execute(
                text(f"INSERT INTO \"{schema}\".alembic_version(version_num) VALUES ('0156')")
            )
            await connection.commit()
            created_owned = True

            stage = "apply_actual_0157_with_version_table_schema"
            await apply_0157(connection, schema)
            table = f'"{schema}".tenant_ai_providers'
            rls = (
                await connection.execute(
                    text(
                        "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname=:schema AND c.relname='tenant_ai_providers'"
                    ),
                    {"schema": schema},
                )
            ).one_or_none()
            if rls != (True, True):
                raise GateBlocked("tenant_ai_providers_force_rls_missing")
            if not await scalar(
                connection,
                "SELECT has_table_privilege('lms_app', :table, 'SELECT,INSERT,UPDATE,DELETE')",
                table=f"{schema}.tenant_ai_providers",
            ):
                raise GateBlocked("lms_app_runtime_grants_missing")

            tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
            provider_id = uuid.uuid4()
            await connection.execute(
                text(f'INSERT INTO "{schema}".tenants(id) VALUES (:a), (:b)'),
                {"a": tenant_a, "b": tenant_b},
            )
            await connection.commit()

        async with runtime_engine.connect() as connection:
            stage = "runtime_role_missing_context_negative"
            await _set_tenant_context(connection, None)
            if await scalar(connection, f"SELECT count(*) FROM {table}") != 0:
                raise GateBlocked("missing_context_read_visible")

            stage = "runtime_role_tenant_a_positive"
            await _set_tenant_context(connection, tenant_a)
            await connection.execute(
                text(
                    f"INSERT INTO {table} (id, tenant_id, purpose, provider, model, encrypted_key) "
                    "VALUES (:id, :tenant_id, 'embedding', 'voyage', 'voyage-4-lite', 'synthetic-ciphertext')"
                ),
                {"id": provider_id, "tenant_id": tenant_a},
            )
            if await scalar(connection, f"SELECT count(*) FROM {table}") != 1:
                raise GateBlocked("tenant_a_positive_read_failed")

            stage = "runtime_role_cross_tenant_negatives"
            await _set_tenant_context(connection, tenant_b)
            if await scalar(connection, f"SELECT count(*) FROM {table}") != 0:
                raise GateBlocked("cross_tenant_read_visible")
            if (await connection.execute(text(f"UPDATE {table} SET enabled=false WHERE id=:id"), {"id": provider_id})).rowcount != 0:
                raise GateBlocked("cross_tenant_update_succeeded")
            if (await connection.execute(text(f"DELETE FROM {table} WHERE id=:id"), {"id": provider_id})).rowcount != 0:
                raise GateBlocked("cross_tenant_delete_succeeded")
            cross_insert_denied = False
            try:
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            f"INSERT INTO {table} (id, tenant_id, purpose, provider, model, encrypted_key) "
                            "VALUES (:id, :tenant_id, 'generation', 'deepseek', 'deepseek-v4-flash', 'synthetic-ciphertext')"
                        ),
                        {"id": uuid.uuid4(), "tenant_id": tenant_a},
                    )
            except Exception as exc:
                original = getattr(exc, "orig", None)
                sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
                if sqlstate != "42501":
                    raise GateBlocked("cross_tenant_insert_failed_for_unexpected_reason") from None
                cross_insert_denied = True
            if not cross_insert_denied:
                raise GateBlocked("cross_tenant_insert_succeeded")

            stage = "runtime_role_tenant_a_update_delete_positive"
            await _set_tenant_context(connection, tenant_a)
            if (await connection.execute(text(f"UPDATE {table} SET enabled=false WHERE id=:id"), {"id": provider_id})).rowcount != 1:
                raise GateBlocked("tenant_a_positive_update_failed")
            if (await connection.execute(text(f"DELETE FROM {table} WHERE id=:id"), {"id": provider_id})).rowcount != 1:
                raise GateBlocked("tenant_a_positive_delete_failed")
            await connection.commit()

        async with owner_engine.connect() as connection:
            if await public_revision(connection) != public_before:
                raise GateBlocked("public_alembic_revision_changed")
            checks = {
                "actual_0157_applied_with_alembic_operations": True,
                "migration_schema_helper_verified": True,
                "lms_app_non_superuser_nobypassrls": True,
                "force_rls_enabled": True,
                "missing_context_read_denied": True,
                "cross_tenant_read_denied": True,
                "cross_tenant_insert_denied": True,
                "cross_tenant_update_denied": True,
                "cross_tenant_delete_denied": True,
                "tenant_positive_crud": True,
                "public_revision_unchanged": True,
            }
    except Exception as exc:
        failure = exc
    finally:
        if created_owned:
            cleanup_ok = await cleanup_isolated_schema(owner_engine, schema)
        await runtime_engine.dispose()
        await owner_engine.dispose()

    if failure is not None:
        detail = str(failure) if isinstance(failure, GateBlocked) else type(failure).__name__
        if not isinstance(failure, GateBlocked):
            original = getattr(failure, "orig", None)
            state = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
            message = str(original).lower()
            flags = [flag for flag, term in {
                "permission_denied": "permission denied", "role_missing": "role",
                "regex_invalid": "regular expression", "syntax_error": "syntax error",
                "relation_exists": "already exists", "relation_missing": "does not exist",
            }.items() if term in message]
            detail += f";sqlstate={state};flags={','.join(flags)}"
        cleanup_state = "passed" if cleanup_ok else ("not_owned" if not created_owned else "failed")
        raise GateBlocked(f"stage={stage};cause={detail};cleanup={cleanup_state}") from None
    if not cleanup_ok:
        raise GateBlocked(f"cleanup_failed_at:{stage}")
    evidence = {
        "status": "PASSED",
        "evidence_labels": ["RUNTIME-DERIVED"],
        "scope": "isolated_supabase_dev_tenant_ai_providers",
        "executed_at": started_at.isoformat().replace("+00:00", "Z"),
        "project_ref_sha256": hashlib.sha256(supabase_project_ref(supabase_url).encode("ascii")).hexdigest(),
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
    schema = f"byok_tap_{uuid.uuid4().hex[:12]}"
    try:
        print(json.dumps(asyncio.run(run_gate(owner_url, runtime_url, supabase_url, schema)), ensure_ascii=True, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error_class": type(exc).__name__, "reason": str(exc) if isinstance(exc, GateBlocked) else "sanitized_unexpected_error"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
