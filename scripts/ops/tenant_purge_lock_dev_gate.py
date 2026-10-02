#!/usr/bin/env python3
"""Run the isolated non-bypass tenant-owner row-lock DEV gate.

The gate creates a validated ``tenant_lock_<12hex>`` schema and a transaction-only
NOLOGIN non-bypass owner following the canonical learning_owner_policy_check
procedure. Schema, role and membership roll back. It does not change the public
catalog, modify existing roles, or inspect customer data.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from dotenv import dotenv_values
from kb_rag_isolated_dev_gate import (
    GateBlocked,
    assert_sanitized_evidence,
    normalize_database_url,
    same_supabase_project,
    supabase_project_ref,
)
from source_actuality_dev_gate import expect_sqlstate_rejection, public_snapshot
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "apps/api/alembic/versions/0174_tenant_purge_owner_lock.py"
SCHEMA_RE = re.compile(r"^tenant_lock_[0-9a-f]{12}$")
DEV_PROJECT_REF_SHA256 = "5b535773cb7222384bbb54ad3f8c2e741fa6176bec4ce586abcd82d17ee0062e"


def safe_schema(schema: str) -> str:
    if not SCHEMA_RE.fullmatch(schema):
        raise GateBlocked("unsafe_owned_schema")
    return f'"{schema}"'


def migration_module():
    if not MIGRATION.is_file():
        raise GateBlocked("migration_0174_unavailable")
    spec = importlib.util.spec_from_file_location("tenant_owner_lock_0174", MIGRATION)
    if spec is None or spec.loader is None:
        raise GateBlocked("migration_0174_unloadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if (module.revision, module.down_revision) != ("0174", "0173"):
        raise GateBlocked("migration_0174_lineage_mismatch")
    if not callable(getattr(module, "lock_policy_sql", None)):
        raise GateBlocked("migration_0174_lock_factory_missing")
    return module


async def verify_role(connection, role: str, reason: str) -> None:
    identity = (
        await connection.execute(
            text("SELECT current_user, session_user, rolsuper, rolbypassrls "
                 "FROM pg_roles WHERE rolname=current_user")
        )
    ).one_or_none()
    if identity is None or identity[0] != role or identity[2:] != (False, False):
        raise GateBlocked(reason)


async def context(connection, tenant: UUID | None, superadmin: bool) -> None:
    await connection.execute(
        text("SELECT set_config('app.tenant_id',:tid,true), "
             "set_config('app.is_superadmin',:root,true)"),
        {"tid": "" if tenant is None else str(tenant), "root": "true" if superadmin else "false"},
    )


async def row_lock_count(connection, qualified: str, tenant: UUID | None) -> int:
    return int(await connection.scalar(text(
        f"SELECT count(*) FROM (SELECT id FROM {qualified}.tenants WHERE id=:tid FOR UPDATE) locked"
    ), {"tid": tenant}))


async def row_snapshot(connection, qualified: str):
    return tuple((row[0], row[1]) for row in (await connection.execute(
        text(f"SELECT id,slug FROM {qualified}.tenants ORDER BY id")
    )).all())


async def run_migration_action(connection, module, schema: str, action: str) -> None:
    """Run only the migration's schema-scoped downgrade through Alembic."""
    def apply(sync_connection) -> None:
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        context = MigrationContext.configure(
            sync_connection, opts={"version_table_schema": schema}
        )
        with Operations.context(context):
            getattr(module, action)()

    await connection.run_sync(apply)


async def run_gate(owner_url: str, runtime_url: str, supabase_url: str) -> dict[str, object]:
    module = migration_module()
    if hashlib.sha256(supabase_project_ref(supabase_url).encode("ascii")).hexdigest() != DEV_PROJECT_REF_SHA256:
        raise GateBlocked("canonical_dev_project_required")
    if not same_supabase_project(owner_url, supabase_url) or not same_supabase_project(runtime_url, supabase_url):
        raise GateBlocked("canonical_dev_identity_mismatch")
    if (make_url(owner_url).username or "").split(".")[0] != "postgres":
        raise GateBlocked("wrong_migration_owner_identity")
    if (make_url(runtime_url).username or "").split(".")[0] != "lms_app":
        raise GateBlocked("wrong_runtime_identity")
    if any(make_url(url).database != "postgres" for url in (owner_url, runtime_url)):
        raise GateBlocked("wrong_database")

    schema = "tenant_lock_" + uuid4().hex[:12]
    owner_role = "tenant_lock_owner_" + schema.removeprefix("tenant_lock_")
    qualified = safe_schema(schema)
    owner = create_async_engine(owner_url, poolclass=NullPool, hide_parameters=True)
    runtime = create_async_engine(runtime_url, poolclass=NullPool, hide_parameters=True)
    cleanup = neutral = False
    role_absent = False
    public_before = None
    checks: list[str] = []
    failure: str | None = None
    failure_sqlstate = None
    stage = "runtime_identity"
    a, b, protected = uuid4(), uuid4(), uuid4()
    try:
        async with runtime.connect() as connection:
            await verify_role(connection, "lms_app", "lms_app_not_non_bypass_runtime_role")
        async with owner.begin() as connection:
            stage = "owner_identity"
            owner_identity = await connection.scalar(text(
                "SELECT current_user=pg_get_userbyid(datdba) FROM pg_database "
                "WHERE datname=current_database()"
            ))
            if not owner_identity:
                raise GateBlocked("migration_session_not_database_owner")
            stage = "public_snapshot_before"
            public_before = await public_snapshot(connection)
            stage = "non_bypass_owner_metadata"
            await connection.execute(text(f'CREATE ROLE "{owner_role}" NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT'))
            await connection.execute(text(f'GRANT "{owner_role}" TO CURRENT_USER'))
            role_flags = await connection.execute(text(
                "SELECT rolcanlogin, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=:role"
            ), {"role": owner_role})
            flags = role_flags.one_or_none()
            if flags is None or flags != (False, False, False):
                raise GateBlocked("owner_role_missing_or_bypass")
            if not await connection.scalar(text(
                "SELECT pg_has_role(current_user,:role,'MEMBER')"
            ), {"role": owner_role}):
                raise GateBlocked("owner_role_membership_missing")
            stage = "owned_schema_create"
            await connection.execute(text(f"CREATE SCHEMA {qualified}"))
            await connection.execute(text(f'GRANT USAGE, CREATE ON SCHEMA {qualified} TO "{owner_role}"'))
            stage = "owned_role_switch"
            await connection.execute(text(f'SET LOCAL ROLE "{owner_role}"'))
            await verify_role(connection, owner_role, "owner_role_switch_failed")
            if not await connection.scalar(text(
                "SELECT pg_has_role(session_user,:role,'MEMBER')"
            ), {"role": owner_role}):
                raise GateBlocked("owner_role_membership_missing")
            # Seed as the non-bypass table owner before enabling RLS. All
            # post-seed writes must fail; no temporary write policy is used.
            stage = "owned_table_seed"
            await connection.execute(text(f"CREATE TABLE {qualified}.tenants(id uuid PRIMARY KEY, slug text NOT NULL)"))
            for tid, slug in ((a, "owned-a"), (b, "owned-b"), (protected, "kamilya")):
                await connection.execute(text(f"INSERT INTO {qualified}.tenants VALUES(:tid,:slug)"), {"tid": tid, "slug": slug})
            stage = "fixture_rls"
            await connection.execute(text(f"ALTER TABLE {qualified}.tenants ENABLE ROW LEVEL SECURITY"))
            await connection.execute(text(f"ALTER TABLE {qualified}.tenants FORCE ROW LEVEL SECURITY"))
            await connection.execute(text(f'CREATE POLICY owner_select ON {qualified}.tenants FOR SELECT TO "{owner_role}" USING (true)'))
            stage = "fixture_catalog"
            metadata = (await connection.execute(text(
                "SELECT pg_get_userbyid(c.relowner),c.relrowsecurity,c.relforcerowsecurity,"
                "has_table_privilege('lms_app',c.oid,'INSERT,UPDATE,DELETE') "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=:schema AND c.relname='tenants'"
            ), {"schema": schema})).one()
            if metadata != (owner_role, True, True, False):
                raise GateBlocked("fixture_owner_rls_or_runtime_write_grant_drift")
            checks.append("isolated_schema_and_three_rows")
            before_rows = await row_snapshot(connection, qualified)
            await connection.execute(text(f'SET LOCAL ROLE "{owner_role}"'))
            await verify_role(connection, owner_role, "owner_role_switch_failed")
            stage = "red_lock"
            await context(connection, a, True)
            if await row_lock_count(connection, qualified, a) != 0:
                raise GateBlocked("red_lock_reproduction_failed")
            checks.append("original_owner_lock_filtered")
            stage = "policy_apply"
            lock_sql = module.lock_policy_sql(schema, owner_role)
            await connection.execute(text(lock_sql))
            checks.append("factory_sql_applied")
            await run_migration_action(connection, module, schema, "downgrade")
            if await row_lock_count(connection, qualified, a) != 0:
                raise GateBlocked("downgrade_lock_policy_not_removed")
            checks.append("downgrade_policy_removed")
            await connection.execute(text(lock_sql))
            if await row_lock_count(connection, qualified, a) != 1:
                raise GateBlocked("reapplied_lock_policy_failed")
            checks.append("lock_policy_reapplied")
            await context(connection, None, True)
            if await row_lock_count(connection, qualified, a) != 0:
                raise GateBlocked("empty_context_lock_not_rejected")
            checks.append("empty_context_lock_rejected")
            stage = "negative_matrix"
            await verify_role(connection, owner_role, "owner_role_switch_failed")
            for label, tenant, root in (("ordinary", a, False), ("foreign", b, True), ("protected", protected, True), ("missing", uuid4(), True), ("null", None, True)):
                await context(connection, tenant, root)
                if await row_lock_count(connection, qualified, tenant if label != "foreign" else a) != 0:
                    raise GateBlocked(label + "_lock_not_rejected")
            await context(connection, a, True)
            if await row_lock_count(connection, qualified, a) != 1:
                raise GateBlocked("exact_owner_lock_failed")
            checks.append("ordinary_foreign_protected_missing_lock_rejected")
            stage = "write_denials"
            await expect_sqlstate_rejection(connection, text(f"UPDATE {qualified}.tenants SET slug='changed' WHERE id=:tid"), {"tid": a}, "owner_update", "42501")
            await expect_sqlstate_rejection(connection, text(f"INSERT INTO {qualified}.tenants VALUES(:tid,'insert-denied')"), {"tid": uuid4()}, "owner_insert", "42501")
            delete_result = await connection.execute(text(f"DELETE FROM {qualified}.tenants WHERE id=:tid"), {"tid": a})
            if delete_result.rowcount != 0:
                raise GateBlocked("owner_delete_accepted")
            if await row_snapshot(connection, qualified) != before_rows:
                raise GateBlocked("rows_changed_after_denials")
            checks.append("owner_update_rejected")
            checks.append("direct_insert_delete_denied")
            checks.append("rows_unchanged")
            await connection.execute(text("RESET ROLE"))
            # Roll back the complete disposable schema, role and membership.
            await connection.rollback()
    except Exception as exc:
        failure = str(exc) if isinstance(exc, GateBlocked) else type(exc).__name__
        state = getattr(getattr(exc, "orig", None), "sqlstate", None)
        failure_sqlstate = state if isinstance(state, str) and re.fullmatch(r"[A-Z0-9]{5}", state) else None
    finally:
        try:
            async with owner.connect() as connection:
                cleanup = not bool(await connection.scalar(
                    text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:schema)"),
                    {"schema": schema},
                ))
                if not cleanup:
                    failure = failure or "owned_schema_remaining"
                role_absent = not bool(await connection.scalar(
                    text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:role)"),
                    {"role": owner_role},
                ))
                cleanup = cleanup and role_absent
            async with owner.connect() as connection:
                neutral = public_before is not None and public_before == await public_snapshot(connection)
        except Exception:
            cleanup = neutral = False
        await runtime.dispose()
        await owner.dispose()
    return {"status": "PASS" if failure is None and cleanup and neutral else "BLOCKED", "target": "canonical_supabase_dev_owned_schema", "migration": "0174", "checks": checks, "reason": failure, "failure_sqlstate": failure_sqlstate, "stage": stage, "owned_schema_and_role_absent": cleanup, "temporary_role_absent": role_absent, "public_revision_catalog_unchanged": neutral, "public_business_mutations": False, "checked_at": datetime.now(UTC).isoformat()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    values = dotenv_values(parser.parse_args().env_file)
    try:
        result = asyncio.run(run_gate(*(normalize_database_url(values.get(key) or "") for key in ("MIGRATION_DATABASE_URL", "DATABASE_URL")), values.get("SUPABASE_URL") or ""))
    except Exception as exc:
        result = {"status": "BLOCKED", "reason": str(exc) if isinstance(exc, GateBlocked) else type(exc).__name__}
    assert_sanitized_evidence(result)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
