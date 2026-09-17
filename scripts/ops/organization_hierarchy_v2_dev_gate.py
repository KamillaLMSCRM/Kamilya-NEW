"""Exercise migration 0161 and hierarchy RLS in a disposable Supabase DEV schema.

This gate never changes the shared ``public`` schema.  It creates one random
schema with the minimum 0160-compatible fixtures, applies the real 0161
migration through Alembic Operations, verifies the restricted ``lms_app``
runtime path, performs downgrade/re-upgrade, and removes the exact schema.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from kb_rag_isolated_dev_gate import normalize_database_url, same_supabase_project

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "apps" / "api"
SCHEMA_PATTERN = re.compile(r"^ohv2_dev_[0-9a-f]{12}$")


def _validated_schema(schema: str) -> str:
    if not SCHEMA_PATTERN.fullmatch(schema):
        raise ValueError("unsafe_schema")
    return schema


def _load_migration():
    path = API / "alembic" / "versions" / "0161_organization_hierarchy_v2.py"
    spec = importlib.util.spec_from_file_location("organization_hierarchy_v2_0161", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("migration_loader_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _upgrade(sync_connection, schema: str) -> None:
    context = MigrationContext.configure(sync_connection, opts={"version_table_schema": schema})
    with Operations.context(context):
        _load_migration().upgrade()


def _downgrade(sync_connection, schema: str) -> None:
    context = MigrationContext.configure(sync_connection, opts={"version_table_schema": schema})
    with Operations.context(context):
        _load_migration().downgrade()


async def _public_revision(connection: AsyncConnection) -> str:
    exists = await connection.scalar(text("SELECT to_regclass('public.alembic_version') IS NOT NULL"))
    if not exists:
        return "absent"
    return str(await connection.scalar(text("SELECT version_num FROM public.alembic_version")) or "empty")


async def _create_baseline(owner, schema: str) -> dict[str, UUID]:
    ids = {
        "tenant_a": uuid4(),
        "tenant_b": uuid4(),
        "branch_a": uuid4(),
        "department_a": uuid4(),
        "branch_b": uuid4(),
        "position_a": uuid4(),
        "user_a": uuid4(),
        "user_unassigned": uuid4(),
        "user_b": uuid4(),
    }
    q = f'"{schema}"'
    async with owner.begin() as connection:
        await connection.execute(text(f"CREATE SCHEMA {q}"))
        await connection.execute(text(f"REVOKE ALL ON SCHEMA {q} FROM PUBLIC"))
        await connection.execute(text(f"GRANT USAGE ON SCHEMA {q} TO lms_app"))
        await connection.execute(text(f"CREATE TABLE {q}.tenants (id uuid PRIMARY KEY, name text NOT NULL)"))
        await connection.execute(
            text(
                f"CREATE TABLE {q}.departments ("
                "id uuid PRIMARY KEY, tenant_id uuid NOT NULL, name text NOT NULL, slug text NOT NULL, "
                "unit_type text NOT NULL, normalized_name text NOT NULL, external_key text NULL, "
                f"parent_id uuid NULL REFERENCES {q}.departments(id), is_active boolean NOT NULL DEFAULT true, "
                "archived_at timestamptz NULL, source_metadata jsonb NOT NULL DEFAULT '{}'::jsonb, "
                "legacy_root boolean NOT NULL DEFAULT false, head_user_id uuid NULL, description text NOT NULL DEFAULT '', "
                "code text NULL, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), "
                "CONSTRAINT ck_departments_unit_type CHECK (unit_type IN ('branch','department')), "
                "CONSTRAINT ck_departments_branch_root CHECK (unit_type <> 'branch' OR parent_id IS NULL), "
                "CONSTRAINT ck_departments_department_parent CHECK "
                "(unit_type <> 'department' OR parent_id IS NOT NULL OR legacy_root))"
            )
        )
        await connection.execute(
            text(
                f"CREATE TABLE {q}.positions ("
                "id uuid PRIMARY KEY, tenant_id uuid NOT NULL, name text NOT NULL, department text NULL, "
                f"department_id uuid NULL REFERENCES {q}.departments(id), is_active boolean NOT NULL DEFAULT true)"
            )
        )
        await connection.execute(
            text(
                f"CREATE TABLE {q}.users ("
                "id uuid PRIMARY KEY, tenant_id uuid NULL, first_name text NOT NULL, last_name text NOT NULL, "
                f"position_id uuid NULL REFERENCES {q}.positions(id), is_active boolean NOT NULL DEFAULT true)"
            )
        )
        await connection.execute(
            text(f"INSERT INTO {q}.tenants (id,name) VALUES (:a,'A'),(:b,'B')"),
            {"a": ids["tenant_a"], "b": ids["tenant_b"]},
        )
        await connection.execute(
            text(
                f"INSERT INTO {q}.departments "
                "(id,tenant_id,name,slug,unit_type,normalized_name,parent_id,legacy_root) VALUES "
                "(:ba,:ta,'Branch A','branch-a','branch','branch a',NULL,false),"
                "(:da,:ta,'Department A','department-a','department','department a',:ba,false),"
                "(:bb,:tb,'Branch B','branch-b','branch','branch b',NULL,false)"
            ),
            {
                "ba": ids["branch_a"],
                "da": ids["department_a"],
                "bb": ids["branch_b"],
                "ta": ids["tenant_a"],
                "tb": ids["tenant_b"],
            },
        )
        await connection.execute(
            text(
                f"INSERT INTO {q}.positions (id,tenant_id,name,department,department_id) "
                "VALUES (:id,:tenant,'Shared specialist','Department A',:department)"
            ),
            {"id": ids["position_a"], "tenant": ids["tenant_a"], "department": ids["department_a"]},
        )
        await connection.execute(
            text(
                f"INSERT INTO {q}.users (id,tenant_id,first_name,last_name,position_id) VALUES "
                "(:ua,:ta,'Assigned','A',:position),(:un,:ta,'No unit','A',NULL),(:ub,:tb,'User','B',NULL)"
            ),
            {
                "ua": ids["user_a"],
                "un": ids["user_unassigned"],
                "ub": ids["user_b"],
                "ta": ids["tenant_a"],
                "tb": ids["tenant_b"],
                "position": ids["position_a"],
            },
        )
        for table in ("tenants", "departments", "positions", "users"):
            tenant_column = "id" if table == "tenants" else "tenant_id"
            await connection.execute(text(f"ALTER TABLE {q}.{table} ENABLE ROW LEVEL SECURITY"))
            await connection.execute(text(f"ALTER TABLE {q}.{table} FORCE ROW LEVEL SECURITY"))
            await connection.execute(
                text(
                    f"CREATE POLICY tenant_isolation ON {q}.{table} FOR ALL TO lms_app "
                    f"USING ({tenant_column}=nullif(current_setting('app.tenant_id',true),'')::uuid) "
                    f"WITH CHECK ({tenant_column}=nullif(current_setting('app.tenant_id',true),'')::uuid)"
                )
            )
            await connection.execute(text(f"REVOKE ALL ON TABLE {q}.{table} FROM PUBLIC, lms_app"))
            await connection.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {q}.{table} TO lms_app"))
        await connection.run_sync(_upgrade, schema)
    return ids


async def _expect_rejected(connection: AsyncConnection, statement, params: dict) -> None:
    savepoint = await connection.begin_nested()
    try:
        await connection.execute(statement, params)
    except Exception:
        await savepoint.rollback()
        return
    await savepoint.rollback()
    raise AssertionError("expected_statement_to_be_rejected")


async def _exercise_runtime(runtime, schema: str, ids: dict[str, UUID]) -> list[str]:
    q = f'"{schema}"'
    checks: list[str] = []
    async with runtime.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(text(f"SET LOCAL search_path TO {q}, public"))
            role = await connection.execute(
                text("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")
            )
            assert tuple(role.one()) == ("lms_app", False, False), "runtime_role_not_restricted"
            checks.append("runtime_role_non_superuser_nobypassrls")

            await connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"),
                {"tenant": str(ids["tenant_a"])},
            )
            assert await connection.scalar(text("SELECT count(*) FROM departments")) == 2
            assert await connection.scalar(
                text("SELECT organization_unit_id FROM users WHERE id=:id"),
                {"id": ids["user_a"]},
            ) == ids["department_a"]
            assert await connection.scalar(
                text("SELECT organization_unit_id FROM users WHERE id=:id"),
                {"id": ids["user_unassigned"]},
            ) is None
            checks.extend(("tenant_read_isolation", "exact_fk_backfill", "nullable_employee_unit"))

            hierarchy = [uuid4() for _ in range(9)]
            for depth, unit_id in enumerate(hierarchy):
                await connection.execute(
                    text(
                        "INSERT INTO departments "
                        "(id,tenant_id,name,slug,unit_type,normalized_name,parent_id,legacy_root,is_head_office) "
                        "VALUES (:id,:tenant,:name,:slug,:kind,:normalized,:parent,false,:head)"
                    ),
                    {
                        "id": unit_id,
                        "tenant": ids["tenant_a"],
                        "name": f"Level {depth}",
                        "slug": f"level-{depth}",
                        "kind": "organization" if depth == 0 else "other",
                        "normalized": f"level {depth}",
                        "parent": hierarchy[depth - 1] if depth else None,
                        "head": depth == 0,
                    },
                )
            checks.append("depth_zero_through_eight_accepted")

            await _expect_rejected(
                connection,
                text(
                    "INSERT INTO departments "
                    "(id,tenant_id,name,slug,unit_type,normalized_name,parent_id,legacy_root) "
                    "VALUES (:id,:tenant,'Too deep','too-deep','team','too deep',:parent,false)"
                ),
                {"id": uuid4(), "tenant": ids["tenant_a"], "parent": hierarchy[-1]},
            )
            checks.append("depth_nine_rejected")

            mover, mover_child = uuid4(), uuid4()
            for unit_id, parent_id, name in (
                (mover, None, "Mover"),
                (mover_child, mover, "Mover child"),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO departments "
                        "(id,tenant_id,name,slug,unit_type,normalized_name,parent_id,legacy_root) "
                        "VALUES (:id,:tenant,:name,:slug,'team',:normalized,:parent,false)"
                    ),
                    {
                        "id": unit_id,
                        "tenant": ids["tenant_a"],
                        "name": name,
                        "slug": name.casefold().replace(" ", "-"),
                        "normalized": name.casefold(),
                        "parent": parent_id,
                    },
                )
            await _expect_rejected(
                connection,
                text("UPDATE departments SET parent_id=:parent WHERE id=:id"),
                {"parent": hierarchy[7], "id": mover},
            )
            checks.append("subtree_move_depth_overflow_rejected_by_database")

            await _expect_rejected(
                connection,
                text("UPDATE departments SET parent_id=:child WHERE id=:root"),
                {"child": hierarchy[2], "root": hierarchy[0]},
            )
            checks.append("cycle_rejected")

            await _expect_rejected(
                connection,
                text(
                    "INSERT INTO departments "
                    "(id,tenant_id,name,slug,unit_type,normalized_name,parent_id,legacy_root,is_head_office) "
                    "VALUES (:id,:tenant,'Second head','second-head','organization','second head',NULL,false,true)"
                ),
                {"id": uuid4(), "tenant": ids["tenant_a"]},
            )
            checks.append("second_head_office_rejected")

            await _expect_rejected(
                connection,
                text(
                    "INSERT INTO departments "
                    "(id,tenant_id,name,slug,unit_type,normalized_name,parent_id,legacy_root) "
                    "VALUES (:id,:tenant,'Cross tenant','cross-tenant','team','cross tenant',:parent,false)"
                ),
                {"id": uuid4(), "tenant": ids["tenant_a"], "parent": ids["branch_b"]},
            )
            checks.append("cross_tenant_parent_rejected")

            await _expect_rejected(
                connection,
                text("UPDATE users SET organization_unit_id=:unit WHERE id=:user"),
                {"unit": ids["branch_b"], "user": ids["user_a"]},
            )
            checks.append("cross_tenant_employee_placement_rejected")

            await connection.execute(text("SELECT set_config('app.tenant_id', '', true)"))
            assert await connection.scalar(text("SELECT count(*) FROM departments")) == 0
            checks.append("missing_tenant_context_returns_zero_rows")
        finally:
            if transaction.is_active:
                await transaction.rollback()
    return checks


async def _exercise_downgrade_reupgrade(owner, schema: str, ids: dict[str, UUID]) -> list[str]:
    q = f'"{schema}"'
    checks: list[str] = []
    async with owner.begin() as connection:
        await connection.execute(text(f"UPDATE {q}.users SET organization_unit_id=NULL"))
        await connection.run_sync(_downgrade, schema)
        columns_after_down = int(
            await connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema=:schema AND column_name IN ('organization_unit_id','is_head_office')"
                ),
                {"schema": schema},
            )
            or 0
        )
        assert columns_after_down == 0, "downgrade_did_not_remove_v2_columns"
        checks.append("downgrade_clean_legacy_shape")
        await connection.run_sync(_upgrade, schema)
        columns_after_up = int(
            await connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema=:schema AND column_name IN ('organization_unit_id','is_head_office')"
                ),
                {"schema": schema},
            )
            or 0
        )
        assert columns_after_up == 2, "reupgrade_missing_v2_columns"
        assert await connection.scalar(
            text(f"SELECT organization_unit_id FROM {q}.users WHERE id=:id"),
            {"id": ids["user_a"]},
        ) == ids["department_a"]
        checks.extend(("reupgrade_restores_v2_shape", "reupgrade_backfill_repeatable"))

        flags = await connection.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=:schema AND relname IN ('departments','users') ORDER BY relname"
            ),
            {"schema": schema},
        )
        assert all(row.relrowsecurity and row.relforcerowsecurity for row in flags), "force_rls_missing"
        checks.append("rls_and_force_rls_enabled")
    return checks


async def main() -> int:
    env_path = Path(os.environ.get("KAMILYA_DEV_ENV_FILE", ROOT / ".env"))
    values = dotenv_values(env_path)
    owner_url = normalize_database_url(values.get("MIGRATION_DATABASE_URL") or "")
    runtime_url = normalize_database_url(values.get("DATABASE_URL") or "")
    if not same_supabase_project(owner_url, values.get("SUPABASE_URL") or ""):
        print(json.dumps({"status": "BLOCKED", "reason": "canonical_dev_identity_mismatch"}))
        return 2
    if not same_supabase_project(runtime_url, values.get("SUPABASE_URL") or ""):
        print(json.dumps({"status": "BLOCKED", "reason": "runtime_dev_identity_mismatch"}))
        return 2
    if (make_url(runtime_url).username or "").split(".")[0] != "lms_app":
        print(json.dumps({"status": "BLOCKED", "reason": "runtime_role_not_lms_app"}))
        return 2

    schema = _validated_schema(f"ohv2_dev_{uuid4().hex[:12]}")
    owner = create_async_engine(owner_url, poolclass=NullPool, hide_parameters=True)
    runtime = create_async_engine(runtime_url, poolclass=NullPool, hide_parameters=True)
    public_before = "not_read"
    public_after = "not_read"
    cleanup = "NOT_VERIFIED"
    stage = "read_public_revision_before"
    try:
        async with owner.connect() as connection:
            public_before = await _public_revision(connection)
        stage = "create_baseline_and_upgrade"
        fixture = await _create_baseline(owner, schema)
        stage = "exercise_runtime"
        checks = await _exercise_runtime(runtime, schema, fixture)
        stage = "downgrade_reupgrade"
        checks.extend(await _exercise_downgrade_reupgrade(owner, schema, fixture))
        stage = "read_public_revision_after"
        async with owner.connect() as connection:
            public_after = await _public_revision(connection)
        assert public_after == public_before, "shared_public_revision_changed"
        checks.append("shared_public_revision_unchanged")
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "target": "isolated_supabase_dev_schema",
                    "migration": "0161",
                    "checks": checks,
                }
            )
        )
        return 0
    except Exception as exc:
        origin = getattr(exc, "orig", None)
        detail_source = getattr(origin, "__cause__", None) or origin
        detail = str(detail_source).splitlines()[0][:240] if detail_source is not None else ""
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "stage": stage,
                    "reason": type(exc).__name__,
                    "sqlstate": getattr(origin, "sqlstate", None),
                    "detail": detail,
                }
            )
        )
        return 1
    finally:
        try:
            async with owner.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            async with owner.connect() as connection:
                residue = int(
                    await connection.scalar(
                        text("SELECT count(*) FROM pg_namespace WHERE nspname=:schema"),
                        {"schema": schema},
                    )
                    or 0
                )
            cleanup = "PASS" if residue == 0 else "BLOCKED"
        except Exception:
            cleanup = "BLOCKED"
        print(
            json.dumps(
                {
                    "cleanup": cleanup,
                    "schema": "disposable",
                    "public_revision_unchanged": (
                        public_after != "not_read" and public_before == public_after
                    ),
                }
            )
        )
        await runtime.dispose()
        await owner.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
