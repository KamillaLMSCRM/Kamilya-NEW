#!/usr/bin/env python3
"""Exercise migration 0165 in a disposable isolated Supabase DEV schema."""

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

from dotenv import dotenv_values, load_dotenv
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

REPO_ROOT = API_ROOT.parent.parent
MIGRATION_PATH = API_ROOT / "alembic" / "versions" / "0165_source_actuality_and_change_reviews.py"
SCHEMA_RE = re.compile(r"^source_actuality_[0-9a-f]{12}$")
EXPECTED_TABLES = {"document_source_policies", "document_change_reviews"}


def safe_schema_name(value: str) -> str:
    if not SCHEMA_RE.fullmatch(value):
        raise GateBlocked("unsafe_schema_name")
    return value


def assert_migration_contract() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    required = (
        'revision = "0165"',
        'down_revision = "0164"',
        'op.get_context().opts.get("version_table_schema")',
        "document_source_policies",
        "document_change_reviews",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "document_source_policies_tenant",
        "document_change_reviews_tenant",
        "document_source_policies.owner_id",
        "u.role='methodologist'",
        "u.is_active IS TRUE",
        "u.status='active'",
        "old_d.source_family_id=document_change_reviews.source_family_id",
        "new_d.source_family_id=document_change_reviews.source_family_id",
        "DROP TABLE",
    )
    if any(token not in source for token in required):
        raise GateBlocked("migration_0165_contract_missing")
    if re.search(r"(?:CREATE|ALTER|DROP|GRANT|REVOKE)\s+[^\n;]*\bpublic\.", source, re.I):
        raise GateBlocked("migration_hard_codes_public")
    runtime_grants = [line for line in source.splitlines() if "GRANT " in line and "lms_app" in line]
    if not runtime_grants or any("DELETE" in line.upper() for line in runtime_grants):
        raise GateBlocked("migration_runtime_delete_grant")


def _migration_module() -> Any:
    spec = importlib.util.spec_from_file_location("source_actuality_0165", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise GateBlocked("migration_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def run_migration(connection: AsyncConnection, schema: str, action: str) -> None:
    safe_schema_name(schema)
    if action not in {"upgrade", "downgrade"}:
        raise GateBlocked("unsupported_migration_action")
    migration = _migration_module()

    def run(sync_connection: Any) -> None:
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        context = MigrationContext.configure(
            sync_connection,
            opts={"version_table_schema": schema},
        )
        with Operations.context(context):
            getattr(migration, action)()

    await connection.run_sync(run)


async def set_tenant_context(connection: AsyncConnection, tenant_id: uuid.UUID | None) -> None:
    await connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": "" if tenant_id is None else str(tenant_id)},
    )


async def verify_runtime_role(connection: AsyncConnection) -> None:
    identity = (
        await connection.execute(
            text("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")
        )
    ).one_or_none()
    if identity != ("lms_app", False, False):
        raise GateBlocked("lms_app_not_non_bypass_runtime_role")


async def public_snapshot(connection: AsyncConnection) -> tuple[str, tuple[str, ...]]:
    revision = await public_revision(connection)
    tables = await connection.execute(
        text(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f') ORDER BY c.relname"
        )
    )
    return revision, tuple(row[0] for row in tables)


async def cleanup_isolated_schema(engine: Any, schema: str) -> bool:
    """Drop and independently read back only this validated schema."""
    safe_schema_name(schema)
    try:
        async with engine.connect() as connection:
            dropped = False
            try:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
                await connection.commit()
                dropped = True
            except Exception:
                try:
                    await connection.rollback()
                except Exception:
                    pass
            try:
                exists = await scalar(
                    connection,
                    "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:schema)",
                    schema=schema,
                )
            except Exception:
                return False
            return dropped and not bool(exists)
    except Exception:
        return False


def _sqlstate(exc: Exception) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


async def expect_rls_rejection(connection: AsyncConnection, statement: Any, parameters: dict[str, Any], code: str) -> None:
    await expect_sqlstate_rejection(connection, statement, parameters, code, "42501")


async def expect_sqlstate_rejection(
    connection: AsyncConnection,
    statement: Any,
    parameters: dict[str, Any],
    code: str,
    expected_sqlstate: str,
) -> None:
    rejected = False
    try:
        async with connection.begin_nested():
            await connection.execute(statement, parameters)
    except Exception as exc:
        if _sqlstate(exc) != expected_sqlstate:
            raise GateBlocked(code + "_unexpected_sqlstate") from None
        rejected = True
    if not rejected:
        raise GateBlocked(code + "_accepted")


async def run_gate(owner_url: str, runtime_url: str, supabase_url: str, schema: str) -> dict[str, Any]:
    safe_schema_name(schema)
    assert_migration_contract()
    if not all(same_supabase_project(url, supabase_url) for url in (owner_url, runtime_url)):
        raise GateBlocked("database_and_supabase_project_mismatch")
    if (make_url(runtime_url).username or "").split(".")[0] != "lms_app":
        raise GateBlocked("wrong_runtime_role")
    if any(make_url(url).database != "postgres" for url in (owner_url, runtime_url)):
        raise GateBlocked("unexpected_database")

    options = {"poolclass": NullPool, "pool_pre_ping": True, "hide_parameters": True}
    owner_engine = create_async_engine(owner_url, **options)
    runtime_engine = create_async_engine(runtime_url, **options)
    stage = "preflight"
    schema_owned = False
    cleanup_ok = False
    public_after_cleanup_ok = False
    failure: Exception | None = None
    public_before: tuple[str, tuple[str, ...]] | None = None
    started_at = datetime.now(UTC)
    checks: dict[str, bool] = {}
    try:
        async with runtime_engine.connect() as connection:
            stage = "verify_runtime_role"
            await verify_runtime_role(connection)

        async with owner_engine.connect() as connection:
            public_before = await public_snapshot(connection)
            if await scalar(
                connection,
                "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:schema)",
                schema=schema,
            ):
                raise GateBlocked("disposable_schema_already_exists")

            stage = "create_isolated_schema_and_baseline"
            # Mark ownership immediately after CREATE SCHEMA so any later failure
            # still enters the cleanup and schema-existence readback path.
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            schema_owned = True
            await connection.execute(text(f'REVOKE ALL ON SCHEMA "{schema}" FROM PUBLIC'))
            await connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO lms_app'))
            q = f'"{schema}"'
            await connection.execute(text(f"CREATE TABLE {q}.tenants (id uuid PRIMARY KEY)"))
            await connection.execute(text(
                f"CREATE TABLE {q}.users (id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES {q}.tenants(id), "
                "role text NOT NULL, is_active boolean NOT NULL, status text NOT NULL)"
            ))
            await connection.execute(text(
                f"CREATE TABLE {q}.documents (id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES {q}.tenants(id), "
                "source_family_id uuid NOT NULL)"
            ))
            await connection.execute(text(f"GRANT SELECT ON {q}.tenants,{q}.users,{q}.documents TO lms_app"))
            await connection.execute(text(f"CREATE TABLE {q}.alembic_version (version_num varchar(32) PRIMARY KEY)"))
            await connection.execute(text(f"INSERT INTO {q}.alembic_version VALUES ('0164')"))
            await connection.commit()

            stage = "upgrade_actual_0165_with_version_table_schema"
            await run_migration(connection, schema, "upgrade")
            await connection.commit()
            actual_tables = await connection.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema=:schema"),
                {"schema": schema},
            )
            if not EXPECTED_TABLES.issubset({row[0] for row in actual_tables}):
                raise GateBlocked("upgrade_tables_missing")
            force_rls = await connection.execute(
                text(
                    "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:schema "
                    "AND c.relname IN ('document_source_policies','document_change_reviews') ORDER BY c.relname"
                ),
                {"schema": schema},
            )
            if tuple(force_rls) != (
                ("document_change_reviews", True, True),
                ("document_source_policies", True, True),
            ):
                raise GateBlocked("force_rls_missing")

            tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
            family, other_family = uuid.uuid4(), uuid.uuid4()
            owner_a, owner_b, inactive_owner, student_owner = (uuid.uuid4() for _ in range(4))
            old_doc, new_doc, other_family_doc, foreign_doc = (uuid.uuid4() for _ in range(4))
            policy_id, review_id = uuid.uuid4(), uuid.uuid4()
            await connection.execute(
                text(f"INSERT INTO {q}.tenants(id) VALUES (:a),(:b)"), {"a": tenant_a, "b": tenant_b}
            )
            await connection.execute(
                text(f"INSERT INTO {q}.users(id,tenant_id,role,is_active,status) VALUES "
                     "(:oa,:a,'methodologist',true,'active'),(:ob,:b,'methodologist',true,'active'),"
                     "(:inactive,:a,'methodologist',false,'active'),(:student,:a,'student',true,'active')"),
                {"oa": owner_a, "ob": owner_b, "inactive": inactive_owner, "student": student_owner,
                 "a": tenant_a, "b": tenant_b},
            )
            await connection.execute(
                text(f"INSERT INTO {q}.documents(id,tenant_id,source_family_id) VALUES "
                     "(:old,:a,:family),(:new,:a,:family),(:other,:a,:other_family),(:foreign,:b,:family)"),
                {"old": old_doc, "new": new_doc, "other": other_family_doc, "foreign": foreign_doc,
                 "a": tenant_a, "b": tenant_b, "family": family, "other_family": other_family},
            )
            await connection.commit()

        policies = f'"{schema}".document_source_policies'
        reviews = f'"{schema}".document_change_reviews'
        async with runtime_engine.connect() as connection:
            stage = "runtime_tenant_a_visibility_and_owner_checks"
            await set_tenant_context(connection, tenant_a)
            await connection.execute(
                text(f"INSERT INTO {policies}(id,tenant_id,source_family_id,owner_id) VALUES (:id,:tenant,:family,:owner)"),
                {"id": policy_id, "tenant": tenant_a, "family": family, "owner": owner_a},
            )
            await connection.execute(
                text(f"INSERT INTO {reviews}(id,tenant_id,source_family_id,previous_document_id,new_document_id) "
                     "VALUES (:id,:tenant,:family,:old,:new)"),
                {"id": review_id, "tenant": tenant_a, "family": family, "old": old_doc, "new": new_doc},
            )
            if await scalar(connection, f"SELECT count(*) FROM {policies}") != 1:
                raise GateBlocked("tenant_a_policy_visibility_failed")
            if await scalar(connection, f"SELECT count(*) FROM {reviews}") != 1:
                raise GateBlocked("tenant_a_review_visibility_failed")

            await expect_rls_rejection(
                connection,
                text(f"INSERT INTO {policies}(tenant_id,source_family_id,owner_id) VALUES (:tenant,:family,:owner)"),
                {"tenant": tenant_a, "family": family, "owner": owner_b}, "cross_tenant_owner",
            )
            await expect_rls_rejection(
                connection,
                text(f"INSERT INTO {policies}(tenant_id,source_family_id,owner_id) VALUES (:tenant,:family,:owner)"),
                {"tenant": tenant_a, "family": family, "owner": inactive_owner}, "inactive_owner",
            )
            await expect_rls_rejection(
                connection,
                text(f"INSERT INTO {policies}(tenant_id,source_family_id,owner_id) VALUES (:tenant,:family,:owner)"),
                {"tenant": tenant_a, "family": family, "owner": student_owner}, "non_methodologist_owner",
            )
            await expect_rls_rejection(
                connection,
                text(f"INSERT INTO {reviews}(tenant_id,source_family_id,previous_document_id,new_document_id) "
                     "VALUES (:tenant,:family,:old,:new)"),
                {"tenant": tenant_a, "family": family, "old": old_doc, "new": other_family_doc},
                "review_revision_family_mismatch",
            )
            await connection.execute(
                text(f"UPDATE {reviews} SET status='ready' WHERE id=:id"),
                {"id": review_id},
            )
            await expect_rls_rejection(
                connection,
                text(
                    f"UPDATE {reviews} SET status='resolved',decision='no_learning_impact',"
                    "decision_reason=:reason,decision_snapshot='{}'::jsonb,decided_by=:actor,decided_at=now() "
                    "WHERE id=:id"
                ),
                {
                    "id": review_id,
                    "actor": student_owner,
                    "reason": "A non-methodologist must not resolve a source review.",
                },
                "non_methodologist_decision",
            )
            await connection.execute(
                text(
                    f"UPDATE {reviews} SET status='resolved',decision='no_learning_impact',"
                    "decision_reason=:reason,decision_snapshot='{}'::jsonb,decided_by=:actor,decided_at=now() "
                    "WHERE id=:id"
                ),
                {
                    "id": review_id,
                    "actor": owner_a,
                    "reason": "The verified changes do not affect the learning material.",
                },
            )
            await expect_sqlstate_rejection(
                connection,
                text(f"UPDATE {reviews} SET decision_reason=:reason WHERE id=:id"),
                {"id": review_id, "reason": "This resolved decision must remain immutable forever."},
                "resolved_review_mutation",
                "23514",
            )
            await connection.commit()

            stage = "runtime_tenant_b_visibility_negative"
            await set_tenant_context(connection, tenant_b)
            if await scalar(connection, f"SELECT count(*) FROM {policies}") != 0:
                raise GateBlocked("tenant_b_policy_visibility_failed")
            if await scalar(connection, f"SELECT count(*) FROM {reviews}") != 0:
                raise GateBlocked("tenant_b_review_visibility_failed")

            stage = "runtime_delete_denied"
            if await scalar(
                connection,
                "SELECT has_table_privilege('lms_app', :table, 'DELETE')",
                table=f"{schema}.document_source_policies",
            ):
                raise GateBlocked("runtime_delete_privilege_present")
            await set_tenant_context(connection, tenant_a)
            await expect_rls_rejection(
                connection,
                text(f"DELETE FROM {policies} WHERE id=:id"),
                {"id": policy_id}, "runtime_delete_denial",
            )
            await connection.rollback()

        async with owner_engine.connect() as connection:
            stage = "downgrade_actual_0165_with_version_table_schema"
            await run_migration(connection, schema, "downgrade")
            await connection.commit()
            remaining = await connection.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema=:schema"),
                {"schema": schema},
            )
            if EXPECTED_TABLES & {row[0] for row in remaining}:
                raise GateBlocked("downgrade_left_migration_tables")
            if await public_snapshot(connection) != public_before:
                raise GateBlocked("public_schema_changed_during_migration")
            checks = {
                "migration_0165_contract": True,
                "actual_upgrade_with_version_table_schema": True,
                "lms_app_non_bypass_rls": True,
                "tenant_a_visibility": True,
                "tenant_b_invisibility": True,
                "valid_active_methodologist_owner": True,
                "cross_tenant_owner_rejected": True,
                "inactive_owner_rejected": True,
                "non_methodologist_owner_rejected": True,
                "non_methodologist_decision_rejected": True,
                "resolved_review_immutable": True,
                "old_new_review_same_family_enforced": True,
                "runtime_delete_denied": True,
                "actual_downgrade_with_version_table_schema": True,
                "public_revision_and_table_neutrality": True,
            }
    except Exception as exc:
        failure = exc
    finally:
        if schema_owned:
            cleanup_ok = await cleanup_isolated_schema(owner_engine, schema)
            if cleanup_ok and public_before is not None:
                try:
                    async with owner_engine.connect() as connection:
                        public_after_cleanup_ok = await public_snapshot(connection) == public_before
                except Exception:
                    public_after_cleanup_ok = False
        await runtime_engine.dispose()
        await owner_engine.dispose()

    if failure is not None:
        cause = str(failure) if isinstance(failure, GateBlocked) else type(failure).__name__
        cleanup_state = "passed" if cleanup_ok else ("failed" if schema_owned else "not_owned")
        public_state = "passed" if public_after_cleanup_ok else "failed"
        raise GateBlocked(
            f"stage={stage};cause={cause};cleanup={cleanup_state};public_readback={public_state}"
        ) from None
    if not cleanup_ok or not public_after_cleanup_ok:
        raise GateBlocked(f"stage={stage};cause=cleanup_or_public_readback_failed")

    evidence = {
        "status": "PASSED",
        "evidence_labels": ["RUNTIME-DERIVED"],
        "scope": "isolated_supabase_dev_source_actuality",
        "executed_at": started_at.isoformat().replace("+00:00", "Z"),
        "project_ref_sha256": hashlib.sha256(supabase_project_ref(supabase_url).encode("ascii")).hexdigest(),
        "migration_sha256": file_sha256(MIGRATION_PATH),
        "disposable_schema_digest": hashlib.sha256(schema.encode("ascii")).hexdigest(),
        "checks": checks,
        "cleanup_readback": "passed",
    }
    assert_sanitized_evidence(evidence)
    return evidence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.execute:
        print(json.dumps({"status": "BLOCKED", "error_class": "execute_flag_required"}, sort_keys=True))
        return 2
    # Keep connection preflight and any application configuration on the same
    # canonical, explicitly selected environment file. Values are never logged.
    load_dotenv(args.env_file, override=True)
    config = dotenv_values(args.env_file)
    owner_url = normalize_database_url(config.get("MIGRATION_DATABASE_URL") or "")
    runtime_url = normalize_database_url(config.get("DATABASE_URL") or "")
    supabase_url = config.get("SUPABASE_URL") or ""
    if not owner_url or not runtime_url or not supabase_url:
        print(json.dumps({"status": "BLOCKED", "error_class": "required_env_missing"}, sort_keys=True))
        return 2
    schema = f"source_actuality_{uuid.uuid4().hex[:12]}"
    try:
        evidence = asyncio.run(run_gate(owner_url, runtime_url, supabase_url, schema))
        print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
        return 0
    except Exception as exc:
        reason = str(exc) if isinstance(exc, GateBlocked) else "sanitized_unexpected_error"
        print(json.dumps({"status": "BLOCKED", "error_class": type(exc).__name__, "reason": reason}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
