#!/usr/bin/env python3
"""Exercise migration 0164 and reporting-owner RLS in disposable Supabase DEV."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import re
import sys
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
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import NullPool

MIGRATION_PATH = API_ROOT / "alembic" / "versions" / "0164_training_reporting_responsibility.py"
SCHEMA_RE = re.compile(r"^training_scope_[0-9a-f]{12}$")


def safe_schema_name(value: str) -> str:
    if not SCHEMA_RE.fullmatch(value):
        raise GateBlocked("unsafe_schema_name")
    return value


def _migration_module():
    spec = importlib.util.spec_from_file_location("training_responsibility_0164", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise GateBlocked("migration_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_migration_contract() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    required = (
        'revision = "0164"',
        'down_revision = "0163"',
        'op.get_context().opts.get("version_table_schema")',
        "validate_cohort_responsible_user",
        "cohort responsible user tenant mismatch",
        "cohort responsible user must be active methodologist",
    )
    if any(token not in source for token in required):
        raise GateBlocked("migration_contract_missing")
    if re.search(r"(?:CREATE|ALTER|DROP|GRANT|REVOKE)\s+[^\n;]*\bpublic\.", source, re.I):
        raise GateBlocked("migration_hard_codes_public")


async def _run_migration(connection: AsyncConnection, schema: str, action: str) -> None:
    safe_schema_name(schema)
    migration = _migration_module()

    def run(sync_connection) -> None:
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        context = MigrationContext.configure(sync_connection, opts={"version_table_schema": schema})
        with Operations.context(context):
            getattr(migration, action)()

    await connection.run_sync(run)


async def _set_tenant_context(connection: AsyncConnection, tenant_id: uuid.UUID | None) -> None:
    await connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": "" if tenant_id is None else str(tenant_id)},
    )


async def _verify_runtime_role(connection: AsyncConnection) -> None:
    row = (
        await connection.execute(
            text("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")
        )
    ).one_or_none()
    if row != ("lms_app", False, False):
        raise GateBlocked("lms_app_not_non_bypass_runtime_role")


async def _cleanup(engine: Any, schema: str) -> bool:
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


async def _create_baseline(connection: AsyncConnection, schema: str) -> None:
    q = f'"{schema}"'
    await connection.execute(text(f"CREATE SCHEMA {q}"))
    await connection.execute(text(f"REVOKE ALL ON SCHEMA {q} FROM PUBLIC"))
    await connection.execute(text(f"GRANT USAGE ON SCHEMA {q} TO lms_app"))
    await connection.execute(text(f"CREATE TABLE {q}.tenants (id uuid PRIMARY KEY)"))
    await connection.execute(
        text(
            f"CREATE TABLE {q}.users (id uuid PRIMARY KEY, tenant_id uuid NOT NULL "
            f"REFERENCES {q}.tenants(id) ON DELETE CASCADE, role text NOT NULL, "
            "is_active boolean NOT NULL DEFAULT true, status text NOT NULL DEFAULT 'active')"
        )
    )
    await connection.execute(
        text(
            f"CREATE TABLE {q}.departments (id uuid PRIMARY KEY, tenant_id uuid NOT NULL "
            f"REFERENCES {q}.tenants(id) ON DELETE CASCADE, name text NOT NULL, slug text NOT NULL, "
            "unit_type text NOT NULL DEFAULT 'department', normalized_name text NOT NULL DEFAULT '', "
            "external_key text NULL, is_active boolean NOT NULL DEFAULT true, archived_at timestamptz NULL, "
            "source_metadata jsonb NOT NULL DEFAULT '{}'::jsonb, legacy_root boolean NOT NULL DEFAULT false, "
            "is_head_office boolean NOT NULL DEFAULT false, description text NOT NULL DEFAULT '', code text NULL, "
            f"head_user_id uuid NULL REFERENCES {q}.users(id) ON DELETE SET NULL, "
            f"parent_id uuid NULL REFERENCES {q}.departments(id) ON DELETE SET NULL, "
            "created_at timestamptz NOT NULL DEFAULT now())"
        )
    )
    await connection.execute(
        text(
            f"CREATE TABLE {q}.positions (id uuid PRIMARY KEY, tenant_id uuid NOT NULL "
            f"REFERENCES {q}.tenants(id) ON DELETE CASCADE, department_id uuid NULL "
            f"REFERENCES {q}.departments(id) ON DELETE SET NULL)"
        )
    )
    await connection.execute(
        text(
            f"ALTER TABLE {q}.users ADD COLUMN organization_unit_id uuid NULL "
            f"REFERENCES {q}.departments(id) ON DELETE SET NULL, ADD COLUMN position_id uuid NULL "
            f"REFERENCES {q}.positions(id) ON DELETE SET NULL"
        )
    )
    await connection.execute(
        text(
            f"CREATE TABLE {q}.cohorts (id uuid PRIMARY KEY, tenant_id uuid NOT NULL "
            f"REFERENCES {q}.tenants(id) ON DELETE CASCADE, name text NOT NULL, "
            "description text NOT NULL DEFAULT '', is_active boolean NOT NULL DEFAULT true, "
            f"created_by uuid REFERENCES {q}.users(id) ON DELETE SET NULL, "
            "created_at timestamptz NOT NULL DEFAULT now())"
        )
    )
    await connection.execute(text(f"ALTER TABLE {q}.cohorts ENABLE ROW LEVEL SECURITY"))
    await connection.execute(text(f"ALTER TABLE {q}.cohorts FORCE ROW LEVEL SECURITY"))
    await connection.execute(
        text(
            f"CREATE TABLE {q}.cohort_members (id uuid PRIMARY KEY, tenant_id uuid NOT NULL "
            f"REFERENCES {q}.tenants(id) ON DELETE CASCADE, cohort_id uuid NOT NULL "
            f"REFERENCES {q}.cohorts(id) ON DELETE CASCADE, user_id uuid NOT NULL "
            f"REFERENCES {q}.users(id) ON DELETE CASCADE)"
        )
    )
    tenant = "tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid"
    for table in ("departments", "cohorts", "cohort_members"):
        if table != "cohorts":
            await connection.execute(text(f"ALTER TABLE {q}.{table} ENABLE ROW LEVEL SECURITY"))
            await connection.execute(text(f"ALTER TABLE {q}.{table} FORCE ROW LEVEL SECURITY"))
        await connection.execute(
            text(
                f"CREATE POLICY tenant_isolation ON {q}.{table} "
                f"USING ({tenant}) WITH CHECK ({tenant})"
            )
        )
    await connection.execute(text(f"GRANT SELECT,INSERT,UPDATE,DELETE ON {q}.cohorts TO lms_app"))
    await connection.execute(text(f"GRANT SELECT ON {q}.departments,{q}.cohort_members TO lms_app"))
    await connection.execute(text(f"GRANT SELECT ON {q}.positions TO lms_app"))
    await connection.execute(text(f"GRANT SELECT ON {q}.users,{q}.tenants TO lms_app"))
    await connection.execute(text(f"CREATE TABLE {q}.alembic_version (version_num varchar(32) PRIMARY KEY)"))
    await connection.execute(text(f"INSERT INTO {q}.alembic_version VALUES ('0163')"))
    await connection.commit()


async def run_gate(owner_url: str, runtime_url: str, supabase_url: str, schema: str) -> dict[str, Any]:
    safe_schema_name(schema)
    assert_migration_contract()
    if not all(same_supabase_project(url, supabase_url) for url in (owner_url, runtime_url)):
        raise GateBlocked("database_and_supabase_project_mismatch")
    if make_url(runtime_url).username.split(".")[0] != "lms_app":
        raise GateBlocked("wrong_runtime_role")
    if any(make_url(url).database != "postgres" for url in (owner_url, runtime_url)):
        raise GateBlocked("unexpected_database")

    options = {"poolclass": NullPool, "pool_pre_ping": True, "hide_parameters": True}
    owner_engine = create_async_engine(owner_url, **options)
    runtime_engine = create_async_engine(runtime_url, **options)
    stage = "preflight"
    created_owned = False
    cleanup_ok = False
    failure: Exception | None = None
    started_at = datetime.now(UTC)
    checks: dict[str, bool] = {}
    try:
        async with runtime_engine.connect() as connection:
            stage = "verify_runtime_role"
            await _verify_runtime_role(connection)
        async with owner_engine.connect() as connection:
            public_before = await public_revision(connection)
            if await scalar(
                connection,
                "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:schema)",
                schema=schema,
            ):
                raise GateBlocked("disposable_schema_already_exists")
            stage = "create_baseline"
            await _create_baseline(connection, schema)
            created_owned = True

            stage = "upgrade_actual_0164"
            await _run_migration(connection, schema, "upgrade")
            await connection.commit()
            if not await scalar(
                connection,
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_schema=:schema AND table_name='cohorts' "
                "AND column_name='responsible_user_id')",
                schema=schema,
            ):
                raise GateBlocked("responsible_column_missing")

            tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
            owner_a, owner_b, owner_unscoped = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            learner_a, learner_org, learner_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            root_a, child_a, root_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            cohort_a, cohort_b = uuid.uuid4(), uuid.uuid4()
            q = f'"{schema}"'
            await connection.execute(
                text(f"INSERT INTO {q}.tenants(id) VALUES (:a),(:b)"),
                {"a": tenant_a, "b": tenant_b},
            )
            await connection.execute(
                text(
                    f"INSERT INTO {q}.users(id,tenant_id,role) VALUES "
                    "(:oa,:a,'methodologist'),(:ou,:a,'methodologist'),"
                    "(:ob,:b,'methodologist'),(:la,:a,'student'),"
                    "(:lo,:a,'student'),(:lb,:b,'student')"
                ),
                {
                    "oa": owner_a,
                    "ou": owner_unscoped,
                    "a": tenant_a,
                    "ob": owner_b,
                    "b": tenant_b,
                    "la": learner_a,
                    "lo": learner_org,
                    "lb": learner_b,
                },
            )
            await connection.execute(
                text(
                    f"INSERT INTO {q}.departments(id,tenant_id,name,slug,normalized_name,head_user_id,parent_id) VALUES "
                    "(:ra,:a,'Root A','root-a','root a',:oa,NULL),"
                    "(:ca,:a,'Child A','child-a','child a',NULL,:ra),"
                    "(:rb,:b,'Root B','root-b','root b',:ob,NULL)"
                ),
                {
                    "ra": root_a,
                    "a": tenant_a,
                    "oa": owner_a,
                    "ca": child_a,
                    "rb": root_b,
                    "b": tenant_b,
                    "ob": owner_b,
                },
            )
            await connection.execute(
                text(
                    f"UPDATE {q}.users SET organization_unit_id=:ca WHERE id=:lo"
                ),
                {"ca": child_a, "lo": learner_org},
            )
            await connection.execute(
                text(f"UPDATE {q}.users SET organization_unit_id=:rb WHERE id=:lb"),
                {"rb": root_b, "lb": learner_b},
            )
            await connection.execute(
                text(
                    f"INSERT INTO {q}.cohorts(id,tenant_id,name,responsible_user_id) VALUES "
                    "(:ca,:a,'A',:oa),(:cb,:b,'B',:ob)"
                ),
                {"ca": cohort_a, "a": tenant_a, "oa": owner_a, "cb": cohort_b, "b": tenant_b, "ob": owner_b},
            )
            await connection.execute(
                text(
                    f"INSERT INTO {q}.cohort_members(id,tenant_id,cohort_id,user_id) VALUES "
                    "(:ma,:a,:ca,:la),(:mb,:b,:cb,:lb)"
                ),
                {
                    "ma": uuid.uuid4(),
                    "a": tenant_a,
                    "ca": cohort_a,
                    "la": learner_a,
                    "mb": uuid.uuid4(),
                    "b": tenant_b,
                    "cb": cohort_b,
                    "lb": learner_b,
                },
            )
            await connection.commit()

            stage = "cross_tenant_trigger_negative"
            rejected = False
            try:
                async with connection.begin_nested():
                    await connection.execute(
                        text(f"UPDATE {q}.cohorts SET responsible_user_id=:ob WHERE id=:ca"),
                        {"ob": owner_b, "ca": cohort_a},
                    )
            except Exception as exc:
                state = getattr(getattr(exc, "orig", None), "sqlstate", None)
                if state != "23503":
                    raise GateBlocked("cross_tenant_trigger_unexpected_failure") from None
                rejected = True
            if not rejected:
                raise GateBlocked("cross_tenant_responsible_user_accepted")

            stage = "same_tenant_role_trigger_negative"
            rejected = False
            try:
                async with connection.begin_nested():
                    await connection.execute(
                        text(f"UPDATE {q}.cohorts SET responsible_user_id=:la WHERE id=:ca"),
                        {"la": learner_a, "ca": cohort_a},
                    )
            except Exception as exc:
                state = getattr(getattr(exc, "orig", None), "sqlstate", None)
                if state != "23503":
                    raise GateBlocked("same_tenant_role_trigger_unexpected_failure") from None
                rejected = True
            if not rejected:
                raise GateBlocked("same_tenant_student_responsible_user_accepted")

        table = f'"{schema}".cohorts'
        async with runtime_engine.connect() as connection:
            stage = "runtime_missing_context_negative"
            await _set_tenant_context(connection, None)
            if await scalar(connection, f"SELECT count(*) FROM {table}") != 0:
                raise GateBlocked("missing_context_visible")
            stage = "runtime_tenant_isolation"
            await _set_tenant_context(connection, tenant_a)
            if await scalar(connection, f"SELECT count(*) FROM {table}") != 1:
                raise GateBlocked("tenant_a_visibility_failed")
            await _set_tenant_context(connection, tenant_b)
            if await scalar(connection, f"SELECT count(*) FROM {table}") != 1:
                raise GateBlocked("tenant_b_visibility_failed")

        stage = "runtime_resolver_scope"
        if str(API_ROOT) not in sys.path:
            sys.path.insert(0, str(API_ROOT))
        from app.modules.training_responsibility import resolve_reporting_scope
        from app.modules.training_responsibility.policy import ReportingScopeMode

        async with runtime_engine.connect() as connection:
            await connection.execute(text(f'SET search_path TO "{schema}", public'))
            await _set_tenant_context(connection, tenant_a)
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                restricted = await resolve_reporting_scope(
                    session,
                    tenant_a,
                    user_id=owner_a,
                    role="methodologist",
                )
                if restricted.mode is not ReportingScopeMode.RESTRICTED:
                    raise GateBlocked("responsible_methodologist_not_restricted")
                if restricted.user_ids != frozenset({learner_a, learner_org}):
                    raise GateBlocked("responsible_group_audience_mismatch")
                if restricted.organization_unit_ids != (root_a,):
                    raise GateBlocked("responsible_organization_root_mismatch")
                unscoped = await resolve_reporting_scope(
                    session,
                    tenant_a,
                    user_id=owner_unscoped,
                    role="methodologist",
                )
                if unscoped.mode is not ReportingScopeMode.TENANT:
                    raise GateBlocked("unscoped_methodologist_not_tenant_wide")

        async with owner_engine.connect() as connection:
            stage = "downgrade_actual_0164"
            await _run_migration(connection, schema, "downgrade")
            await connection.commit()
            if await scalar(
                connection,
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_schema=:schema AND table_name='cohorts' "
                "AND column_name='responsible_user_id')",
                schema=schema,
            ):
                raise GateBlocked("downgrade_left_responsible_column")
            if await public_revision(connection) != public_before:
                raise GateBlocked("public_revision_changed")
            checks = {
                "actual_upgrade": True,
                "actual_downgrade": True,
                "cross_tenant_trigger_denied": True,
                "same_tenant_non_methodologist_trigger_denied": True,
                "runtime_missing_context_denied": True,
                "runtime_tenant_isolation": True,
                "runtime_resolver_org_and_group_scope": True,
                "runtime_unscoped_backward_compatibility": True,
                "public_revision_unchanged": True,
            }
    except Exception as exc:
        failure = exc
    finally:
        if created_owned:
            cleanup_ok = await _cleanup(owner_engine, schema)
        await runtime_engine.dispose()
        await owner_engine.dispose()

    if failure is not None:
        detail = str(failure) if isinstance(failure, GateBlocked) else type(failure).__name__
        raise GateBlocked(
            f"stage={stage};cause={detail};cleanup={'passed' if cleanup_ok else 'failed'}"
        ) from None
    if not cleanup_ok:
        raise GateBlocked(f"cleanup_failed_at:{stage}")
    evidence = {
        "status": "PASSED",
        "evidence_labels": ["RUNTIME-DERIVED"],
        "scope": "isolated_supabase_dev_training_responsibility",
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
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
    schema = f"training_scope_{uuid.uuid4().hex[:12]}"
    try:
        evidence = asyncio.run(run_gate(owner_url, runtime_url, supabase_url, schema))
        print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({
            "status": "BLOCKED",
            "error_class": type(exc).__name__,
            "reason": str(exc) if isinstance(exc, GateBlocked) else "sanitized_unexpected_error",
        }, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
