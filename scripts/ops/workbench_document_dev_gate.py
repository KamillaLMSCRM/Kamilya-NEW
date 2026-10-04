#!/usr/bin/env python3
"""Fail-closed disposable Supabase DEV gate for document workbench 0175.

The gate is deliberately separate from the assignment gate.  It never targets
public for writes, never logs credentials or fixture bodies, and owns one
random ``workbench_<12hex>`` schema from creation through cleanup.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from dotenv import dotenv_values, load_dotenv
from sqlalchemy import event, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
API_ROOT = ROOT / "apps" / "api"
OPS_ROOT = ROOT / "scripts" / "ops"
MIGRATION = API_ROOT / "alembic" / "versions" / "0175_workbench_document_plans.py"
SCHEMA_RE = re.compile(r"^workbench_[0-9a-f]{12}$")
CLONE_TABLES = ("tenants", "users", "user_roles", "documents", "ai_jobs")
TENANT_SCOPED_CLONES = ("users", "user_roles", "documents", "ai_jobs")

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(OPS_ROOT) not in sys.path:
    sys.path.insert(0, str(OPS_ROOT))

from kb_rag_isolated_dev_gate import GateBlocked, assert_sanitized_evidence, normalize_database_url, same_supabase_project  # noqa: E402
from source_actuality_dev_gate import public_snapshot, verify_runtime_role  # noqa: E402


def safe_schema(value: str) -> str:
    if not SCHEMA_RE.fullmatch(value):
        raise GateBlocked("unsafe_schema_name")
    return f'"{value}"'


def canonical_config(env_file: Path) -> dict[str, str]:
    if not env_file.is_file():
        raise GateBlocked("env_file_missing")
    raw = {str(k): str(v) for k, v in dotenv_values(env_file).items() if v is not None}
    owner = normalize_database_url(raw.get("MIGRATION_DATABASE_URL", ""))
    runtime = normalize_database_url(raw.get("DATABASE_URL", ""))
    supabase = raw.get("SUPABASE_URL", "")
    if not owner or not runtime or not supabase:
        raise GateBlocked("required_env_missing")
    if (make_url(runtime).username or "").split(".", 1)[0] != "lms_app":
        raise GateBlocked("wrong_runtime_role")
    for url in (owner, runtime):
        parsed = make_url(url)
        if parsed.database != "postgres":
            raise GateBlocked("unexpected_database")
        if (parsed.username or "").split(".", 1)[0] not in {"postgres", "lms_app"}:
            raise GateBlocked("unexpected_database_role")
        if not same_supabase_project(url, supabase):
            raise GateBlocked("canonical_dev_identity_mismatch")
    return {"owner_url": owner, "runtime_url": runtime, "supabase_url": supabase}


def sanitize_failure(exc: BaseException) -> str:
    if isinstance(exc, GateBlocked):
        return str(exc)
    return type(exc).__name__


async def set_context(connection: AsyncConnection, schema: str, tenant: UUID | None = None, actor: UUID | None = None) -> None:
    """Rebind after every commit; no public or ambient search path is allowed."""
    await connection.execute(text(f"SET LOCAL search_path TO {safe_schema(schema)}, pg_catalog"))
    if tenant is not None:
        await connection.execute(text("SELECT set_config('app.tenant_id', :tenant, true), set_config('app.user_id', :actor, true), set_config('app.is_superadmin', 'false', true)"), {"tenant": str(tenant), "actor": str(actor)})


async def clone_tables(connection: AsyncConnection, schema: str) -> None:
    safe_schema(schema)
    qualified = safe_schema(schema)
    await connection.execute(text(f"CREATE SCHEMA {qualified}"))
    await connection.execute(text(f"REVOKE ALL ON SCHEMA {qualified} FROM PUBLIC"))
    await connection.execute(text(f"GRANT USAGE ON SCHEMA {qualified} TO lms_app"))
    for table in CLONE_TABLES:
        if not re.fullmatch(r"[a-z_]+", table):
            raise GateBlocked("unsafe_clone_table")
        await connection.execute(text(f"CREATE TABLE {qualified}.{table} (LIKE public.{table} INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES)"))
        await connection.execute(text(f"REVOKE ALL ON {qualified}.{table} FROM PUBLIC,lms_app"))
        await connection.execute(text(f"GRANT SELECT,INSERT,UPDATE,DELETE ON {qualified}.{table} TO lms_app"))
    # Neighbor tables are tenant scoped; the workbench table gets its own real
    # 0175 policies and trigger from Alembic below.
    for table in TENANT_SCOPED_CLONES:
        await connection.execute(text(f"ALTER TABLE {qualified}.{table} ENABLE ROW LEVEL SECURITY"))
        await connection.execute(text(f"ALTER TABLE {qualified}.{table} FORCE ROW LEVEL SECURITY"))
        await connection.execute(text(f"CREATE POLICY gate_{table}_tenant ON {qualified}.{table} FOR ALL TO lms_app USING (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid) WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)"))
    # Exact0019 invoker helper shadowed in the owned schema; no public fallback.
    await connection.execute(text(f"""CREATE FUNCTION {qualified}.set_current_tenant(tenant_uuid uuid)
        RETURNS void LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$ BEGIN
        PERFORM set_config('app.tenant_id',tenant_uuid::text,true); END $$"""))
    await connection.execute(text(f"REVOKE ALL ON FUNCTION {qualified}.set_current_tenant(uuid) FROM PUBLIC"))
    await connection.execute(text(f"GRANT EXECUTE ON FUNCTION {qualified}.set_current_tenant(uuid) TO lms_app"))


async def apply_0175(connection: AsyncConnection, schema: str, operation: str = "upgrade") -> None:
    safe_schema(schema)
    if operation not in {"upgrade", "downgrade"} or MIGRATION.resolve().parent != (API_ROOT / "alembic" / "versions").resolve():
        raise GateBlocked("invalid_migration_request")
    spec = importlib.util.spec_from_file_location("workbench_document_0175", MIGRATION)
    if spec is None or spec.loader is None:
        raise GateBlocked("migration_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def apply(sync: Connection) -> None:
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        with Operations.context(MigrationContext.configure(sync, opts={"version_table_schema": schema})):
            getattr(module, operation)()

    await connection.run_sync(apply)


async def cleanup(engine: Any, schema: str) -> bool:
    safe_schema(schema)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f"DROP SCHEMA IF EXISTS {safe_schema(schema)} CASCADE"))
        async with engine.connect() as connection:
            return not bool(await connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:schema)"), {"schema": schema}))
    except Exception:
        return False


async def run_gate(owner_url: str, runtime_url: str, supabase_url: str, schema: str) -> dict[str, Any]:
    """Execute the disposable proof; runtime failures are sanitized by main."""
    if not SCHEMA_RE.fullmatch(schema):
        raise GateBlocked("unsafe_schema_name")
    if not all(same_supabase_project(url, supabase_url) for url in (owner_url, runtime_url)):
        raise GateBlocked("canonical_dev_identity_mismatch")
    if (make_url(runtime_url).username or "").split(".", 1)[0] != "lms_app":
        raise GateBlocked("wrong_runtime_role")
    owner_engine = create_async_engine(owner_url, poolclass=NullPool, hide_parameters=True)
    runtime_engine = create_async_engine(runtime_url, poolclass=NullPool, hide_parameters=True)
    @event.listens_for(runtime_engine.sync_engine, "begin")
    def owned_transaction(connection):
        # A shared command may commit and open a new transaction for compensation.
        # Retain only owned object resolution, NOT caller RLS GUCs (must rebind).
        connection.exec_driver_sql(f"SET LOCAL search_path TO {safe_schema(schema)}, pg_catalog")
    owned = False
    cleanup_ok = False
    public_before: Any = None
    public_neutral, failure, checks = False, None, []
    stage = "migration"
    try:
        async with runtime_engine.connect() as connection:
            await verify_runtime_role(connection)
        async with owner_engine.connect() as connection:
            public_before = await public_snapshot(connection)
            await clone_tables(connection, schema)
            await apply_0175(connection, schema, "upgrade")
            await connection.commit()
            owned = True
        async with runtime_engine.connect() as connection:
            await verify_runtime_role(connection)
            await set_context(connection, schema)
            # No fixture bodies or provider calls are permitted in this gate.
            relations = set((await connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname=:schema"), {"schema": schema})).scalars().all())
            if "workbench_document_plans" not in relations:
                raise GateBlocked("document_plan_table_missing")
            await connection.commit()
            await set_context(connection, schema)
        stage = "service_transactions"
        from workbench_document_dev_checks import verify_service
        checks = await verify_service(owner_engine, runtime_engine, schema, set_context, apply_0175)
        async with owner_engine.connect() as connection:
            if await public_snapshot(connection) != public_before:
                raise GateBlocked("public_schema_changed")
    except Exception as exc:
        failure = sanitize_failure(exc)
    finally:
        if owned:
            cleanup_ok = await cleanup(owner_engine, schema)
            async with owner_engine.connect() as connection:
                public_neutral = public_before == await public_snapshot(connection)
        await runtime_engine.dispose()
        await owner_engine.dispose()
    evidence = {"status": "PASS" if failure is None and cleanup_ok and public_neutral and checks else "BLOCKED",
                "scope": "workbench_document_isolated_dev", "migration": "0175", "checks": checks,
                "cleanup": cleanup_ok, "public_schema_neutral": public_neutral,
                "stage": stage, "failure": failure, "dispatch": "STUB_COUNTER_ONLY", "generator_quality": "NOT_VERIFIED"}
    assert_sanitized_evidence(evidence)
    return evidence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.execute:
        print(json.dumps({"status": "BLOCKED", "error_class": "execute_flag_required"}, sort_keys=True))
        return 2
    schema = f"workbench_{uuid4().hex[:12]}"
    try:
        config = canonical_config(args.env_file)
        load_dotenv(args.env_file, override=True)
        evidence = asyncio.run(run_gate(config["owner_url"], config["runtime_url"], config["supabase_url"], schema))
        print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
        return 0 if evidence["status"] == "PASS" else 1
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error_class": type(exc).__name__, "stage": sanitize_failure(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
