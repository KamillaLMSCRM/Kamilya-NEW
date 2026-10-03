#!/usr/bin/env python3
"""Source-bound0172 on synthetic owned Supabase DEV; never public business rows."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import sys
from types import SimpleNamespace
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values, load_dotenv
from kb_rag_isolated_dev_gate import (
    GateBlocked,
    assert_sanitized_evidence,
    normalize_database_url,
    same_supabase_project,
)
from source_actuality_dev_gate import public_snapshot, verify_runtime_role
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from workbench_assignment_dev_gate import safe_failure

ROOT = Path(__file__).resolve().parents[2]
TABLES = ("tenants", "users", "user_roles")


def safe_schema(schema):
    if not re.fullmatch(r"tenants_[0-9a-f]{12}", schema):
        raise GateBlocked("unsafe_tenants_schema")
    return f'"{schema}"'


async def apply_migration(db, schema, *, expand=False):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    safe_schema(schema)
    spec = importlib.util.spec_from_file_location(
        "tenant_migration0172",
        ROOT / "apps/api/alembic/versions/0172_tenants_scoped_bootstrap_rls.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def apply(sync):
        with Operations.context(
            MigrationContext.configure(sync, opts={"version_table_schema": schema})
        ):
            (module.install_bootstrap if expand else module.upgrade)()

    await db.run_sync(apply)


async def context(db, schema, tenant="", *, platform=False):
    await db.execute(
        text(f"SET LOCAL search_path TO {safe_schema(schema)}, pg_catalog")
    )
    await db.execute(
        text(
            "SELECT set_config('app.tenant_id',:tenant,true), "
            "set_config('app.is_superadmin',:platform,true), set_config('app.auth_lookup','false',true)"
        ),
        {"tenant": str(tenant), "platform": "true" if platform else "false"},
    )
    for name in TABLES:
        resolved = await db.scalar(
            text(
                "SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE c.oid=to_regclass(:name)"
            ),
            {"name": name},
        )
        if resolved != schema:
            raise GateBlocked("public_table_resolution")
    for signature in (
        "lookup_tenant_id_by_slug(text)",
        "tenant_login_eligible(uuid)",
        "set_current_tenant(text)",
    ):
        resolved = await db.scalar(
            text(
                "SELECT n.nspname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE p.oid=to_regprocedure(:signature)"
            ),
            {"signature": signature},
        )
        if resolved != schema:
            raise GateBlocked("public_function_resolution")


async def run_gate(owner_url, runtime_url, supabase_url):
    if not all(
        same_supabase_project(url, supabase_url) for url in (owner_url, runtime_url)
    ):
        raise GateBlocked("canonical_dev_identity_mismatch")
    if (make_url(runtime_url).username or "").split(".")[0] != "lms_app":
        raise GateBlocked("wrong_runtime_role")
    if any(make_url(url).database != "postgres" for url in (owner_url, runtime_url)):
        raise GateBlocked("unexpected_database")
    schema = f"tenants_{uuid4().hex[:12]}"
    qualified = safe_schema(schema)
    owner = create_async_engine(owner_url, poolclass=NullPool, hide_parameters=True)
    runtime = create_async_engine(runtime_url, poolclass=NullPool, hide_parameters=True)
    created = cleanup = neutral = False
    checks = []
    failure = before = None
    stage = "preflight"
    tenant_ids = [uuid4(), uuid4()]
    user_ids = [uuid4() for _ in range(4)]
    try:
        async with runtime.connect() as db:
            await verify_runtime_role(db)
        checks.append("runtime_non_super_non_bypass")
        stage = "owned_setup"
        async with owner.begin() as db:
            before = await public_snapshot(db)
            await db.execute(text(f"CREATE SCHEMA {qualified}"))
            created = True
            await db.execute(text(f"REVOKE ALL ON SCHEMA {qualified} FROM PUBLIC"))
            await db.execute(text(f"GRANT USAGE ON SCHEMA {qualified} TO lms_app"))
            for name in TABLES:
                await db.execute(
                    text(
                        f"CREATE TABLE {qualified}.{name} (LIKE public.{name} INCLUDING ALL)"
                    )
                )
                await db.execute(
                    text(
                        f"GRANT SELECT,INSERT,UPDATE,DELETE ON {qualified}.{name} TO lms_app"
                    )
                )
            await db.execute(
                text(f"""
                CREATE FUNCTION {qualified}.set_current_tenant(tenant_id text)
                RETURNS text LANGUAGE sql SET search_path = pg_catalog
                AS $$ SELECT set_config('app.tenant_id', tenant_id, true) $$
            """)
            )
            await db.execute(
                text(
                    f"REVOKE ALL ON FUNCTION {qualified}.set_current_tenant(text) FROM PUBLIC"
                )
            )
            await db.execute(
                text(
                    f"GRANT EXECUTE ON FUNCTION {qualified}.set_current_tenant(text) TO lms_app"
                )
            )
            await db.execute(
                text(f"""
                CREATE POLICY tenants_superadmin_session ON {qualified}.tenants FOR ALL TO lms_app
                USING (current_setting('app.is_superadmin',true)='true')
                WITH CHECK (current_setting('app.is_superadmin',true)='true')
            """)
            )
            await apply_migration(db, schema)
            if await db.scalar(text(f"SELECT count(*) FROM {qualified}.tenants")) != 0:
                raise GateBlocked("empty_upgrade_fixture_not_empty")
            checks.append("empty_upgrade0172")
            # Recreate ORIGINAL legacy fixture explicitly, not migration downgrade.
            await db.execute(
                text(f"ALTER TABLE {qualified}.tenants NO FORCE ROW LEVEL SECURITY")
            )
            await db.execute(
                text(f"DROP POLICY tenants_own_context ON {qualified}.tenants")
            )
            await db.execute(
                text(f"CREATE POLICY service_access ON {qualified}.tenants USING(true)")
            )
            for name in ("users", "user_roles"):
                await db.execute(
                    text(f"ALTER TABLE {qualified}.{name} ENABLE ROW LEVEL SECURITY")
                )
                await db.execute(
                    text(f"ALTER TABLE {qualified}.{name} FORCE ROW LEVEL SECURITY")
                )
                expression = (
                    "tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid"
                )
                await db.execute(
                    text(
                        f"CREATE POLICY tenant_isolation ON {qualified}.{name} USING({expression}) WITH CHECK({expression})"
                    )
                )
            await db.execute(
                text(f"""
                CREATE POLICY users_auth_email_lookup ON {qualified}.users FOR SELECT TO lms_app
                USING(current_setting('app.auth_lookup',true)='true')
            """)
            )
            from app.modules.auth import service as auth_service

            synthetic_hash = auth_service.ph.hash("synthetic-gate-password")
            for tid, slug in zip(
                tenant_ids, ("example.invalid", "legacy-synthetic"), strict=True
            ):
                await db.execute(
                    text(
                        f"INSERT INTO {qualified}.tenants(id,name,slug) VALUES(:id,'Synthetic',:slug)"
                    ),
                    {"id": tid, "slug": slug},
                )
            for index, uid in enumerate(user_ids):
                tid = tenant_ids[index % 2]
                email = (
                    "domain@example.invalid",
                    "legacy@other.invalid",
                    "duplicate@ambiguous.invalid",
                    "duplicate@ambiguous.invalid",
                )[index]
                await db.execute(
                    text(f"""
                    INSERT INTO {qualified}.users(id,tenant_id,email,password_hash,first_name,last_name,role,is_active,status)
                    VALUES(:id,:tenant,:email,:hash,'Synthetic','Only','methodologist',true,'active')
                """),
                    {"id": uid, "tenant": tid, "email": email, "hash": synthetic_hash},
                )
                await db.execute(
                    text(
                        f"INSERT INTO {qualified}.user_roles(id,tenant_id,user_id,role) VALUES(:id,:tenant,:user,'methodologist')"
                    ),
                    {"id": uuid4(), "tenant": tid, "user": uid},
                )

        async def ids(tenant="", *, platform=False):
            async with AsyncSession(runtime) as db:
                await context(db, schema, tenant, platform=platform)
                return set((await db.scalars(text("SELECT id FROM tenants"))).all())

        stage = "legacy_reproduction"
        if await ids(tenant_ids[0]) != set(tenant_ids) or await ids() != set(
            tenant_ids
        ):
            raise GateBlocked("legacy_foreign_and_empty_read_not_reproduced")
        async with AsyncSession(runtime) as db:
            await context(db, schema, tenant_ids[0])
            changed = await db.execute(
                text("UPDATE tenants SET name='Synthetic changed' WHERE id=:id"),
                {"id": tenant_ids[1]},
            )
            if changed.rowcount != 1:
                raise GateBlocked("legacy_foreign_update_not_reproduced")
            await db.rollback()
        checks.append("legacy_foreign_read_update_and_empty_read_reproduced")
        stage = "populated_upgrade"
        async with owner.begin() as db:
            rows_before = (
                await db.execute(text(f"SELECT * FROM {qualified}.tenants ORDER BY id"))
            ).all()
            await apply_migration(db, schema)
            rows_after = (
                await db.execute(text(f"SELECT * FROM {qualified}.tenants ORDER BY id"))
            ).all()
            if rows_before != rows_after:
                raise GateBlocked("migration_rewrote_business_rows")
            flags = (
                await db.execute(
                    text(
                        "SELECT relrowsecurity,relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname=:s AND c.relname='tenants'"
                    ),
                    {"s": schema},
                )
            ).one()
            if flags != (True, True):
                raise GateBlocked("force_rls_missing")
            policies = set(
                (
                    await db.scalars(
                        text(
                            "SELECT p.polname FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid "
                            "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:s AND c.relname='tenants'"
                        ),
                        {"s": schema},
                    )
                ).all()
            )
            if policies != {
                "tenants_own_context",
                "tenants_superadmin_session",
                "tenants_bootstrap_function_owner",
            }:
                raise GateBlocked("unexpected_tenants_policy_set")
            acl = (
                await db.execute(
                    text(
                        "SELECT has_function_privilege('lms_app',p.oid,'EXECUTE'), "
                        "EXISTS(SELECT 1 FROM aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) a "
                        "WHERE a.grantee=0 AND a.privilege_type='EXECUTE'), p.prosecdef, p.proconfig "
                        "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                        "WHERE n.nspname=:s AND p.proname IN ('lookup_tenant_id_by_slug','tenant_login_eligible')"
                    ),
                    {"s": schema},
                )
            ).all()
            if len(acl) != 2 or any(
                row != (True, False, True, ["search_path=pg_catalog"]) for row in acl
            ):
                raise GateBlocked("bootstrap_function_acl_invalid")
        checks += [
            "populated_upgrade_no_row_rewrite",
            "force_rls_exact_policy_set",
            "bounded_function_acl_fixed_search_path",
        ]

        stage = "isolation"
        if (
            await ids()
            or await ids(tenant_ids[0]) != {tenant_ids[0]}
            or await ids(tenant_ids[1]) != {tenant_ids[1]}
        ):
            raise GateBlocked("foreign_or_empty_context_rows_visible")
        if await ids(platform=True) != set(tenant_ids):
            raise GateBlocked("validated_platform_context_broken")
        checks += [
            "own_id_reads_only",
            "empty_context_read_denied",
            "validated_superadmin_preserved",
        ]
        for tenant in ("", tenant_ids[0]):
            async with AsyncSession(runtime) as db:
                await context(db, schema, tenant)
                for action in (
                    "UPDATE tenants SET name='Synthetic changed' WHERE id=:id",
                    "DELETE FROM tenants WHERE id=:id",
                ):
                    if (
                        await db.execute(text(action), {"id": tenant_ids[1]})
                    ).rowcount != 0:
                        raise GateBlocked("foreign_write_not_denied")
        checks.append("foreign_and_empty_update_delete_denied")
        for tenant, sql, params in (
            (
                "",
                "INSERT INTO tenants(id,name,slug) VALUES(:id,'Synthetic','new-synthetic')",
                {"id": uuid4()},
            ),
            (
                tenant_ids[0],
                "INSERT INTO tenants(id,name,slug) VALUES(:id,'Synthetic','foreign-synthetic')",
                {"id": tenant_ids[1]},
            ),
            (
                tenant_ids[0],
                "UPDATE tenants SET id=:new WHERE id=:old",
                {"new": uuid4(), "old": tenant_ids[0]},
            ),
        ):
            async with AsyncSession(runtime) as db:
                await context(db, schema, tenant)
                try:
                    await db.execute(text(sql), params)
                except DBAPIError as error:
                    if getattr(error.orig, "sqlstate", None) != "42501":
                        raise
                    await db.rollback()
                else:
                    raise GateBlocked("insert_or_id_move_not_denied")
        checks.append("empty_foreign_insert_and_own_id_move_denied")

        from app.modules.tenants.bootstrap import (
            bind_new_tenant,
            get_bootstrap_tenant,
            lookup_tenant_id_by_slug,
        )
        from app.models.tenants import Tenant
        from fastapi import HTTPException

        stage = "application_bootstrap"
        async with runtime.connect() as connection, AsyncSession(bind=connection) as db:
            await context(db, schema)
            backend_pid = await db.scalar(text("SELECT pg_backend_pid()"))
            for slug in (
                "missing",
                "' OR true --",
                "EXAMPLE.INVALID",
                " example.invalid ",
            ):
                if await lookup_tenant_id_by_slug(db, slug) is not None:
                    raise GateBlocked("non_exact_slug_resolved")
            if await lookup_tenant_id_by_slug(db, "example.invalid") != tenant_ids[0]:
                raise GateBlocked("exact_slug_not_resolved")
            tenant = await get_bootstrap_tenant(db, "example.invalid")
            if tenant is None or tenant.id != tenant_ids[0]:
                raise GateBlocked("real_bootstrap_helper_failed")
            if await lookup_tenant_id_by_slug(db, "legacy-synthetic") is not None:
                raise GateBlocked("authenticated_foreign_bootstrap_visible")
            if await db.scalar(
                text("SELECT tenant_login_eligible(:id)"), {"id": tenant_ids[1]}
            ):
                raise GateBlocked("authenticated_foreign_status_visible")
            await db.rollback()
            # Pin the physical connection and inspect scope BEFORE any reset helper.
            scope = (
                await db.execute(
                    text(
                        "SELECT pg_backend_pid(), current_setting('app.tenant_id',true), "
                        "current_setting('app.is_superadmin',true), "
                        "current_setting('app.auth_lookup',true)"
                    )
                )
            ).one()
            if (
                scope[0] != backend_pid
                or scope[1] not in (None, "")
                or any(value == "true" for value in scope[2:])
            ):
                raise GateBlocked("same_connection_rollback_scope_leaked")
            # Restore only table resolution; do not overwrite the tested GUCs.
            await db.execute(
                text(f"SET LOCAL search_path TO {safe_schema(schema)}, pg_catalog")
            )
            if await db.scalar(text("SELECT count(*) FROM tenants")) != 0:
                raise GateBlocked("rollback_scope_leaked")
        checks += [
            "exact_slug_only_no_sql_injection",
            "real_bootstrap_helper_context_order",
            "authenticated_bootstrap_denied",
            "same_physical_connection_rollback_scope_reset",
        ]
        async with AsyncSession(runtime) as db:
            await context(db, schema)
            tenant = Tenant(name="Synthetic creation", slug=uuid4().hex)
            await bind_new_tenant(db, tenant)
            db.add(tenant)
            await db.flush()
            if (await db.scalar(text("SELECT id FROM tenants"))) != tenant.id:
                raise GateBlocked("new_tenant_not_owned")
            if (
                await db.execute(
                    text("UPDATE tenants SET name='Synthetic updated' WHERE id=:id"),
                    {"id": tenant.id},
                )
            ).rowcount != 1:
                raise GateBlocked("own_update_broken")
            if (
                await db.execute(
                    text("DELETE FROM tenants WHERE id=:id"), {"id": tenant.id}
                )
            ).rowcount != 1:
                raise GateBlocked("own_delete_broken")
            await db.rollback()
        checks.append("real_server_id_creation_own_crud_rollback")

        # Exercise the real ORM/router update boundary without importing the
        # production response fan-out (stats, usage and latest-lead tables are
        # intentionally outside this isolated three-table schema).  The local
        # stubs are explicit: they prove ordering and tenant-field handling,
        # while the independent readback below proves the persisted RLS row.
        stage = "application_tenant_update_commit_boundary"
        async with owner.begin() as db:
            enabled = await db.execute(
                text(f"UPDATE {qualified}.tenants SET is_demo=true WHERE id=:id"),
                {"id": tenant_ids[0]},
            )
            if enabled.rowcount != 1:
                raise GateBlocked("demo_update_setup_missing")

        from app.modules.admin.superadmin import router as superadmin_router
        from app.modules.admin.superadmin.schemas import TenantUpdate
        from app.modules.admin.superadmin.service import SuperadminService

        async with runtime.connect() as connection, AsyncSession(bind=connection) as db:
            await context(db, schema, "", platform=True)
            update_backend_pid = await db.scalar(text("SELECT pg_backend_pid()"))
            svc = SuperadminService(db)
            original_response = superadmin_router._tenant_response
            original_log_action = superadmin_router.log_action

            async def response_stub(_svc, tenant):
                if tenant.is_demo is not False:
                    raise GateBlocked("orm_demo_update_not_visible_precommit")
                return {"id": str(tenant.id), "is_demo": bool(tenant.is_demo)}

            async def audit_stub(*_args, **_kwargs):
                return None

            superadmin_router._tenant_response = response_stub
            superadmin_router.log_action = audit_stub
            try:
                response = await superadmin_router.update_tenant(
                    tenant_ids[0],
                    TenantUpdate(is_demo=False),
                    SimpleNamespace(client=None),
                    user=SimpleNamespace(id=user_ids[0]),
                    svc=svc,
                )
            finally:
                superadmin_router._tenant_response = original_response
                superadmin_router.log_action = original_log_action
            if response != {"id": str(tenant_ids[0]), "is_demo": False}:
                raise GateBlocked("orm_demo_update_response_mismatch")
            commit_scope = (await db.execute(text(
                "SELECT pg_backend_pid(), current_setting('app.tenant_id',true), "
                "current_setting('app.is_superadmin',true)"
            ))).one()
            if commit_scope[0] != update_backend_pid:
                raise GateBlocked("commit_connection_not_pinned")
            if commit_scope[1] not in (None, "") or commit_scope[2] == "true":
                raise GateBlocked("tenant_context_leaked_after_commit")

        async with AsyncSession(runtime) as db:
            await context(db, schema, tenant_ids[0])
            persisted = await db.scalar(
                text("SELECT is_demo FROM tenants WHERE id=:id"),
                {"id": tenant_ids[0]},
            )
            if persisted is not False:
                raise GateBlocked("orm_demo_update_not_persisted_false")
            await db.rollback()
        async with AsyncSession(runtime) as db:
            await context(db, schema)
            if await db.scalar(text("SELECT count(*) FROM tenants")) != 0:
                raise GateBlocked("no_platform_read_not_denied_after_update")
            await db.rollback()
        checks += [
            "router_orm_demo_true_to_false_response_before_commit",
            "router_orm_demo_false_persisted_after_commit",
            "router_orm_commit_clears_local_tenant_context",
            "router_orm_no_platform_read_denied",
            "router_response_auxiliary_reads_explicitly_stubbed",
        ]

        stage = "application_credentials"
        for email, expected in (
            ("domain@example.invalid", user_ids[0]),
            ("legacy@other.invalid", user_ids[1]),
        ):
            async with AsyncSession(runtime) as db:
                await context(db, schema)
                user, _, _ = await auth_service.authenticate_user(
                    db, email, "synthetic-gate-password"
                )
                if user.id != expected:
                    raise GateBlocked("credential_identity_mismatch")
                if (
                    await db.scalar(
                        text("SELECT current_setting('app.auth_lookup',true)")
                    )
                    == "true"
                ):
                    raise GateBlocked("auth_lookup_scope_leaked")
                await db.rollback()
        checks += [
            "real_credential_domain_preserved",
            "real_credential_legacy_preserved",
        ]
        for email, password in (
            ("duplicate@ambiguous.invalid", "synthetic-gate-password"),
            ("domain@example.invalid", "wrong"),
        ):
            async with AsyncSession(runtime) as db:
                await context(db, schema)
                try:
                    await auth_service.authenticate_user(db, email, password)
                except HTTPException as error:
                    if error.status_code != 401:
                        raise
                    await db.rollback()
                else:
                    raise GateBlocked("ambiguous_or_wrong_credential_accepted")
        checks.append("ambiguous_and_wrong_credential_denied")
        async with owner.begin() as db:
            await db.execute(
                text(f"UPDATE {qualified}.tenants SET status='suspended' WHERE id=:id"),
                {"id": tenant_ids[1]},
            )
        async with AsyncSession(runtime) as db:
            await context(db, schema)
            try:
                await auth_service.authenticate_user(
                    db, "legacy@other.invalid", "synthetic-gate-password"
                )
            except HTTPException as error:
                if error.status_code != 401:
                    raise
                await db.rollback()
            else:
                raise GateBlocked("legacy_suspended_tenant_accepted")
        checks.append("legacy_suspended_tenant_denied")
    except Exception as error:
        failure = safe_failure(error)
    finally:
        if created:
            try:
                async with owner.begin() as db:
                    await db.execute(text(f"DROP SCHEMA {qualified} CASCADE"))
                async with owner.connect() as db:
                    cleanup = not await db.scalar(
                        text(
                            "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:s)"
                        ),
                        {"s": schema},
                    )
                    neutral = before == await public_snapshot(db)
            except Exception:
                cleanup = False
        await runtime.dispose()
        await owner.dispose()
    result = {
        "status": "PASS" if failure is None and cleanup and neutral else "BLOCKED",
        "scope": "owned_supabase_dev_tenants0172",
        "stage": stage,
        "failure": failure,
        "checks": checks,
        "cleanup": cleanup,
        "public_schema_neutral": neutral,
        "public_migration": "NOT_RUN",
        "full_neighbor_equivalence": "NOT_VERIFIED",
    }
    assert_sanitized_evidence(result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "BLOCKED", "reason": "execute_required"}))
        return 2
    config = dotenv_values(args.env_file)
    load_dotenv(args.env_file, override=True)
    sys.path.insert(0, str(ROOT / "apps/api"))
    urls = [
        normalize_database_url(config.get(key) or "")
        for key in ("MIGRATION_DATABASE_URL", "DATABASE_URL")
    ]
    try:
        result = asyncio.run(run_gate(*urls, config.get("SUPABASE_URL") or ""))
    except Exception as error:
        result = {
            "status": "BLOCKED",
            "reason": str(error)
            if isinstance(error, GateBlocked)
            else type(error).__name__,
        }
    assert_sanitized_evidence(result)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
