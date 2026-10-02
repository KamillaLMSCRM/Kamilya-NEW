#!/usr/bin/env python3
"""Exercise actual0173 in one owned disposable Supabase DEV schema only.

Public schema/catalog reads only; no API, email, worker, provider or customer DML.
The minimal fixture verifies this helper's authority/FK/rollback, not every
historical tenant lifecycle. Full populated API coverage belongs to integration CI.
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
from uuid import uuid4

from dotenv import dotenv_values
from kb_rag_isolated_dev_gate import (
    GateBlocked, assert_sanitized_evidence, normalize_database_url,
    same_supabase_project, supabase_project_ref,
)
from source_actuality_dev_gate import (
    expect_sqlstate_rejection, public_snapshot, verify_runtime_role,
)
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "apps/api/alembic/versions/0173_bounded_enrollment_access_purge.py"
TABLES = ("assignment_access_credentials", "enrollment_access_policies",
          "course_assignment_notification_outbox")
DEV_PROJECT_REF_SHA256 = "5b535773cb7222384bbb54ad3f8c2e741fa6176bec4ce586abcd82d17ee0062e"


def safe_schema(schema: str) -> str:
    if not re.fullmatch(r"enrollment_purge_[0-9a-f]{12}", schema):
        raise GateBlocked("unsafe_owned_schema")
    return f'"{schema}"'


async def apply_migration(connection, schema: str, action: str) -> None:
    safe_schema(schema)
    if action not in {"upgrade", "downgrade"}:
        raise GateBlocked("unsafe_migration_action")
    spec = importlib.util.spec_from_file_location("owned_purge_0173", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if (module.revision, module.down_revision) != ("0173", "0172"):
        raise GateBlocked("migration_lineage_mismatch")

    def apply(sync):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        with Operations.context(MigrationContext.configure(
            sync, opts={"version_table_schema": schema}
        )):
            getattr(module, action)()

    await connection.run_sync(apply)


async def context(connection, tenant, superadmin=True):
    await connection.execute(text(
        "SELECT set_config('app.tenant_id',:tid,true), "
        "set_config('app.is_superadmin',:root,true)"
    ), {"tid": str(tenant), "root": "true" if superadmin else "false"})


async def public_acl(connection):
    return (await connection.execute(text(
        "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,"
        "has_table_privilege('lms_app',c.oid,'DELETE') "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relname=ANY(:tables) ORDER BY c.relname"
    ), {"tables": list(TABLES)})).all()


async def child_count(connection, qualified, tid):
    count = 0
    for table in TABLES:
        count += await connection.scalar(text(
            f"SELECT count(*) FROM {qualified}.{table} WHERE tenant_id=:tid"
        ), {"tid": tid})
    return count


async def run_gate(owner_url, runtime_url, supabase_url):
    if hashlib.sha256(supabase_project_ref(supabase_url).encode("ascii")).hexdigest() != DEV_PROJECT_REF_SHA256:
        raise GateBlocked("canonical_dev_project_required")
    if not all(same_supabase_project(url, supabase_url) for url in (owner_url, runtime_url)):
        raise GateBlocked("canonical_dev_identity_mismatch")
    if (make_url(owner_url).username or "").split(".")[0] != "postgres":
        raise GateBlocked("wrong_migration_owner_identity")
    if (make_url(runtime_url).username or "").split(".")[0] != "lms_app":
        raise GateBlocked("wrong_runtime_identity")
    if any(make_url(url).database != "postgres" for url in (owner_url, runtime_url)):
        raise GateBlocked("wrong_database")
    schema = "enrollment_purge_" + uuid4().hex[:12]
    qualified = safe_schema(schema)
    owner = create_async_engine(owner_url, poolclass=NullPool, hide_parameters=True)
    runtime = create_async_engine(runtime_url, poolclass=NullPool, hide_parameters=True)
    owned = cleanup = neutral = False
    before = acl_before = None
    checks = []
    failure = None
    a, b, protected, claimed = [uuid4() for _ in range(4)]
    ids = {tid: uuid4() for tid in (a, b, protected, claimed)}
    function = f"{qualified}.superadmin_purge_tenant_enrollment_access"
    call = text(f"SELECT {function}(:tid,:slug)")
    try:
        async with runtime.connect() as connection:
            await verify_runtime_role(connection)
        async with owner.begin() as connection:
            if not await connection.scalar(text(
                "SELECT current_user=pg_get_userbyid(datdba) "
                "FROM pg_database WHERE datname=current_database()"
            )):
                raise GateBlocked("migration_session_not_database_owner")
            before, acl_before = await public_snapshot(connection), await public_acl(connection)
            if len(acl_before) != 3 or any(not row[1] or not row[2] or row[3] for row in acl_before):
                raise GateBlocked("public_child_acl_or_force_rls_drift")
            await connection.execute(text(f"CREATE SCHEMA {qualified}"))
            owned = True
            await connection.execute(text(f"GRANT USAGE ON SCHEMA {qualified} TO lms_app"))
            await connection.execute(text(f"CREATE TABLE {qualified}.tenants(id uuid PRIMARY KEY,slug text NOT NULL)"))
            await connection.execute(text(f"CREATE TABLE {qualified}.enrollments(id uuid PRIMARY KEY,tenant_id uuid NOT NULL REFERENCES {qualified}.tenants(id))"))
            for table in TABLES:
                await connection.execute(text(
                    f"CREATE TABLE {qualified}.{table}(id uuid PRIMARY KEY,tenant_id uuid NOT NULL,"
                    f"enrollment_id uuid NOT NULL REFERENCES {qualified}.enrollments(id) ON DELETE RESTRICT,status text)"
                ))
            for table in ("tenants", "enrollments", *TABLES):
                column = "id" if table == "tenants" else "tenant_id"
                await connection.execute(text(f"ALTER TABLE {qualified}.{table} ENABLE ROW LEVEL SECURITY"))
                await connection.execute(text(f"ALTER TABLE {qualified}.{table} FORCE ROW LEVEL SECURITY"))
                await connection.execute(text(
                    f"CREATE POLICY exact_tenant ON {qualified}.{table} USING "
                    f"({column}::text=nullif(current_setting('app.tenant_id',true),''))"
                ))
                await connection.execute(text(f"GRANT SELECT ON {qualified}.{table} TO lms_app"))
            await connection.execute(text(f"GRANT DELETE ON {qualified}.enrollments TO lms_app"))
            for tid, slug in ((a, "owned-a"), (b, "owned-b"), (protected, "kamilya"), (claimed, "owned-claimed")):
                await context(connection, tid)
                await connection.execute(text(f"INSERT INTO {qualified}.tenants VALUES(:tid,:slug)"), {"tid": tid, "slug": slug})
                await connection.execute(text(f"INSERT INTO {qualified}.enrollments VALUES(:id,:tid)"), {"id": ids[tid], "tid": tid})
                for table in TABLES:
                    await connection.execute(text(f"INSERT INTO {qualified}.{table} VALUES(:id,:tid,:eid,:status)"),
                                             {"id": uuid4(), "tid": tid, "eid": ids[tid], "status": "claimed" if tid == claimed and table == TABLES[2] else "pending"})
            await apply_migration(connection, schema, "upgrade")
            metadata = (await connection.execute(text(
                "SELECT p.prosecdef,pg_get_userbyid(p.proowner)=pg_get_userbyid(d.datdba),"
                "has_function_privilege('lms_app',p.oid,'EXECUTE'),"
                "EXISTS(SELECT 1 FROM aclexplode(p.proacl) acl WHERE acl.grantee=0 AND acl.privilege_type='EXECUTE') "
                "FROM pg_proc p CROSS JOIN pg_database d WHERE p.oid=CAST(:name AS regprocedure) AND d.datname=current_database()"
            ), {"name": f"{function}(uuid,text)"})).one()
            if metadata != (True, True, True, False):
                raise GateBlocked("helper_owner_or_acl_mismatch")
            checks.append("actual_upgrade_owner_execute_only")
        async with runtime.begin() as connection:
            await verify_runtime_role(connection)
            for label, ctx, target, slug, root, state in (
                ("ordinary", a, a, "owned-a", False, "42501"),
                ("foreign", b, a, "owned-a", True, "42501"),
                ("wrong_slug", a, a, "wrong", True, "42501"),
                ("protected", protected, protected, "kamilya", True, "42501"),
                ("missing", a, uuid4(), "owned-a", True, "42501"),
                ("null", a, None, "owned-a", True, "42501"),
                ("claimed", claimed, claimed, "owned-claimed", True, "55000"),
            ):
                await context(connection, ctx, root)
                await expect_sqlstate_rejection(connection, call, {"tid": target, "slug": slug}, label, state)
                checks.append(label + "_rejected")
            await context(connection, a)
            for table in TABLES:
                await expect_sqlstate_rejection(connection, text(f"DELETE FROM {qualified}.{table} WHERE tenant_id=:tid"), {"tid": a}, table, "42501")
            checks.append("direct_delete_still_denied")
        # Real successful child/enrollment deletes are rolled back together.
        async with runtime.connect() as connection:
            transaction = await connection.begin()
            await context(connection, a)
            if await connection.scalar(call, {"tid": a, "slug": "owned-a"}) != 3:
                raise GateBlocked("wrong_purge_count")
            await connection.execute(text(f"DELETE FROM {qualified}.enrollments WHERE tenant_id=:tid"), {"tid": a})
            await transaction.rollback()
        async with runtime.begin() as connection:
            await context(connection, a)
            if await child_count(connection, qualified, a) != 3 or await connection.scalar(text(f"SELECT count(*) FROM {qualified}.enrollments WHERE tenant_id=:tid"), {"tid": a}) != 1:
                raise GateBlocked("rollback_not_atomic")
            checks.append("rollback_restores_children_and_enrollment")
            if await connection.scalar(call, {"tid": a, "slug": "owned-a"}) != 3:
                raise GateBlocked("committed_purge_count")
            await connection.execute(text(f"DELETE FROM {qualified}.enrollments WHERE tenant_id=:tid"), {"tid": a})
        async with runtime.begin() as connection:
            await context(connection, a)
            if await child_count(connection, qualified, a) != 0:
                raise GateBlocked("owned_child_absence_failed")
            await context(connection, b)
            if await child_count(connection, qualified, b) != 3:
                raise GateBlocked("sentinel_changed")
            checks.append("commit_owned_absence_foreign_preserved")
        async with owner.begin() as connection:
            await apply_migration(connection, schema, "downgrade")
            if await connection.scalar(text("SELECT to_regprocedure(:name)"), {"name": f"{function}(uuid,text)"}) is not None:
                raise GateBlocked("downgrade_helper_remaining")
            await apply_migration(connection, schema, "upgrade")
            await context(connection, b)
            if await child_count(connection, qualified, b) != 3:
                raise GateBlocked("migration_cycle_changed_rows")
            checks.append("downgrade_upgrade_preserves_rows")
    except Exception as exc:
        failure = str(exc) if isinstance(exc, GateBlocked) else type(exc).__name__
    finally:
        if owned:
            try:
                async with owner.begin() as connection:
                    await connection.execute(text(f"DROP SCHEMA IF EXISTS {qualified} CASCADE"))
                async with owner.begin() as connection:
                    cleanup = not await connection.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:name)"), {"name": schema})
                    neutral = before == await public_snapshot(connection) and acl_before == await public_acl(connection)
            except Exception:
                cleanup = neutral = False
        await runtime.dispose()
        await owner.dispose()
    return {"status": "PASS" if failure is None and cleanup and neutral else "BLOCKED",
            "target": "canonical_supabase_dev_owned_schema", "migration": "0173",
            "checks": checks, "reason": failure, "owned_schema_absent": cleanup,
            "public_revision_catalog_and_acl_unchanged": neutral,
            "public_business_mutations": False, "full_tenant_lifecycle": "NOT_VERIFIED",
            "checked_at": datetime.now(UTC).isoformat()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    values = dotenv_values(args.env_file)
    try:
        result = asyncio.run(run_gate(
            *(normalize_database_url(values.get(key) or "") for key in ("MIGRATION_DATABASE_URL", "DATABASE_URL")),
            values.get("SUPABASE_URL") or "",
        ))
    except Exception as exc:
        result = {"status": "BLOCKED", "reason": str(exc) if isinstance(exc, GateBlocked) else type(exc).__name__}
    assert_sanitized_evidence(result)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
