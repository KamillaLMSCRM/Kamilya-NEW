#!/usr/bin/env python3
"""0182 on one owned Supabase DEV schema; no public rows or migrations."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from dotenv import dotenv_values, load_dotenv
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from kb_rag_isolated_dev_gate import GateBlocked, assert_sanitized_evidence, normalize_database_url, same_supabase_project
from source_actuality_dev_gate import public_snapshot, verify_runtime_role

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/api"))
SOURCE = ROOT / "apps/api/alembic/versions/0182_runtime_settings.py"


def safe_schema(value):
    if not re.fullmatch(r"runtime_cfg_[0-9a-f]{12}", value):
        raise GateBlocked("unsafe_owned_schema")
    return f'"{value}"'


async def migration(db, schema, *, downgrade=False):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    safe_schema(schema)
    spec = importlib.util.spec_from_file_location("owned_runtime_migration", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def apply(sync):
        with Operations.context(MigrationContext.configure(sync, opts={"version_table_schema": schema})):
            (module.downgrade if downgrade else module.upgrade)()
    await db.run_sync(apply)


async def run(owner_url, runtime_url, supabase_url):
    if not all(same_supabase_project(url, supabase_url) for url in (owner_url, runtime_url)):
        raise GateBlocked("canonical_supabase_dev_identity_mismatch")
    if (make_url(runtime_url).username or "").split(".")[0] != "lms_app":
        raise GateBlocked("runtime_role_mismatch")
    schema = f"runtime_cfg_{uuid4().hex[:12]}"
    qualified = safe_schema(schema)
    owner = create_async_engine(owner_url, poolclass=NullPool, hide_parameters=True)
    runtime = create_async_engine(runtime_url, poolclass=NullPool, hide_parameters=True)
    created = cleanup = neutral = False
    before = failure = None
    checks = []
    actor = uuid4()
    stage = "preflight"
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()

    async def context(db, *, platform=False):
        await db.execute(text(f"SET LOCAL search_path TO {qualified},pg_catalog"))
        await db.execute(text("SELECT set_config('app.is_superadmin',:v,true),set_config('app.tenant_id','',true)"), {"v": str(platform).lower()})
        for table in ("runtime_settings", "runtime_settings_history", "users"):
            actual = await db.scalar(text("SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.oid=to_regclass(:t)"), {"t": table})
            if actual != schema:
                raise GateBlocked("unsafe_public_table_resolution")

    @asynccontextmanager
    async def reader():
        async with AsyncSession(runtime, expire_on_commit=False) as db:
            await context(db)
            yield db

    try:
        async with runtime.connect() as db:
            await verify_runtime_role(db)
        checks.append("non_super_non_bypass_runtime")
        stage = "owned_expand"
        async with owner.begin() as db:
            before = await public_snapshot(db)
            await db.execute(text(f"CREATE SCHEMA {qualified}"))
            created = True
            await db.execute(text(f"REVOKE ALL ON SCHEMA {qualified} FROM PUBLIC"))
            await db.execute(text(f"GRANT USAGE ON SCHEMA {qualified} TO lms_app"))
            await db.execute(text(f"CREATE TABLE {qualified}.users(id uuid PRIMARY KEY)"))
            await db.execute(text(f"INSERT INTO {qualified}.users(id) VALUES(:id)"), {"id": actor})
            await migration(db, schema)
            flags = (await db.execute(text("SELECT relrowsecurity,relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:s AND c.relname IN ('runtime_settings','runtime_settings_history')"), {"s": schema})).all()
            if len(flags) != 2 or any(tuple(row) != (True, True) for row in flags):
                raise GateBlocked("force_rls_missing")
        checks += ["additive0182_owned_schema", "force_rls_both_tables"]
        from app.modules.admin.runtime_configuration.runtime import resolve_runtime_settings
        from app.modules.admin.runtime_configuration.service import RuntimeSettingsService, SettingsConflict, SettingsMissing
        from app.modules.admin.runtime_configuration.catalog import InvalidSettings
        stage = "ordinary_runtime_denials"
        async with reader() as db:
            if (await RuntimeSettingsService(db).get())["revision"] != 1:
                raise GateBlocked("default_revision_wrong")
            if await RuntimeSettingsService(db).history():
                raise GateBlocked("history_visible_without_platform")
            result = await db.execute(text("UPDATE runtime_settings SET revision=2 WHERE id=1"))
            if result.rowcount != 0:
                raise GateBlocked("ordinary_runtime_mutated_global_settings")
            try:
                async with db.begin_nested():
                    await db.execute(text("INSERT INTO runtime_settings_history(revision,before,after,reason) VALUES(2,'{}','{}','synthetic')"))
            except DBAPIError as exc:
                if getattr(exc.orig, "sqlstate", None) != "42501":
                    raise
            else:
                raise GateBlocked("ordinary_runtime_inserted_history")
        checks += ["runtime_reads_operational_snapshot", "ordinary_write_denied", "ordinary_history_hidden_and_insert_denied"]
        from app.models.registry import load_all_models
        load_all_models()
        stage = "atomic_service_and_runtime_contract"
        with patch("app.core.db.async_session_factory", reader):
            initial = await resolve_runtime_settings()
            async with AsyncSession(runtime, expire_on_commit=False) as db:
                await context(db, platform=True)
                service = RuntimeSettingsService(db)
                updated = await service.update(revision=1, changes={"assignment.deepseek_seconds": 20}, reason="Synthetic isolated DEV check", actor_id=actor)
                if updated["revision"] != 2:
                    raise GateBlocked("atomic_revision_wrong")
                await context(db, platform=True)
                history = await service.history()
                same_session = await resolve_runtime_settings(db)
                if same_session.revision != 2 or not db.in_transaction():
                    raise GateBlocked("existing_session_snapshot_lost_caller_transaction")
                if len(history) != 1 or history[0]["before"] != {} or history[0]["after"] != {"assignment.deepseek_seconds": 20}:
                    raise GateBlocked("atomic_audit_wrong")
                for invalid in ({"unknown.option": 5}, {"assignment.deepseek_seconds": True},
                                {"assignment.deepseek_seconds": 1.5}, {"assignment.total_seconds": 45},
                                {"provider.chatgpt.model": "not-supported"}):
                    try:
                        async with db.begin_nested():
                            await db.execute(text("UPDATE runtime_settings SET overrides=CAST(:v AS jsonb) WHERE id=1"), {"v": json.dumps(invalid)})
                    except DBAPIError as exc:
                        if getattr(exc.orig, "sqlstate", None) not in {"23514", "22P02"}:
                            raise
                    else:
                        raise GateBlocked("raw_invalid_sql_override_accepted")
                try:
                    async with db.begin_nested():
                        await db.execute(text("UPDATE runtime_settings SET revision=3,overrides='{}' WHERE id=1"))
                        await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
                except DBAPIError as exc:
                    if getattr(exc.orig, "sqlstate", None) != "23514":
                        raise
                else:
                    raise GateBlocked("raw_sql_edit_without_audit_accepted")
                try:
                    await service.update(revision=1, changes={"assignment.deepseek_seconds": 15}, reason="Stale revision", actor_id=actor)
                except SettingsConflict:
                    await db.rollback()
                else:
                    raise GateBlocked("stale_write_accepted")
                current = await resolve_runtime_settings()
                if current.revision != 2 or current.integer("assignment.deepseek_seconds") != 20 or initial.integer("assignment.deepseek_seconds") != 30:
                    raise GateBlocked("cross_session_snapshot_not_fresh_or_mutated")
                await context(db, platform=True)
                try:
                    await service.update(revision=2, changes={"assignment.total_seconds": 45}, reason="Invalid combined budget", actor_id=actor)
                except InvalidSettings:
                    await db.rollback()
                else:
                    raise GateBlocked("invalid_bundle_accepted")
                await context(db, platform=True)
                result = await service.revert(revision=2, target_revision=1, reason="Return declared defaults", actor_id=actor)
                if result["revision"] != 3 or (await resolve_runtime_settings()).integer("assignment.deepseek_seconds") != 30:
                    raise GateBlocked("audited_revert_failed")
                await context(db, platform=True)
                history = await service.history()
                if len(history) != 2 or history[0]["after"] != {}:
                    raise GateBlocked("revert_not_new_audit")
                try:
                    async with db.begin_nested():
                        await db.execute(text("DELETE FROM runtime_settings_history"))
                except DBAPIError as exc:
                    if getattr(exc.orig, "sqlstate", None) != "42501":
                        raise
                else:
                    raise GateBlocked("runtime_history_delete_permitted")
        checks += ["atomic_state_and_audit", "existing_session_snapshot_preserves_transaction", "raw_invalid_sql_overrides_denied", "raw_sql_edit_requires_matching_audit", "stale_revision_conflict", "fresh_cross_session_runtime_snapshot", "inflight_snapshot_unchanged", "invalid_bundle_no_write", "audited_revert_new_revision", "history_delete_denied_even_platform"]
        stage = "owned_downgrade_reexpand"
        async with owner.begin() as db:
            await migration(db, schema, downgrade=True)
            await migration(db, schema)
        checks.append("owned_only_downgrade_reexpand")
    except Exception as exc:
        failure = str(exc) if isinstance(exc, GateBlocked) else type(exc).__name__
    finally:
        if created:
            try:
                async with owner.begin() as db:
                    await db.execute(text(f"DROP SCHEMA {qualified} CASCADE"))
                async with owner.connect() as db:
                    cleanup = not await db.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:s)"), {"s": schema})
                    neutral = await public_snapshot(db) == before
            except Exception:
                cleanup = False
        await runtime.dispose()
        await owner.dispose()
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != source_hash:
        failure = "migration_source_changed_during_gate"
    return {"status": "PASS" if failure is None and cleanup and neutral else "BLOCKED",
            "scope": "owned_supabase_dev_runtime0182", "stage": stage, "failure": failure,
            "checks": checks, "cleanup": cleanup, "public_schema_neutral": neutral,
            "public_business_row_equivalence": "NOT_VERIFIED_NOT_WRITTEN", "public_migration": "NOT_RUN", "production_actions": 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "BLOCKED", "reason": "execute_required"}))
        return 2
    config = dotenv_values(args.env_file)
    load_dotenv(args.env_file, override=True)
    try:
        result = asyncio.run(run(*(normalize_database_url(config.get(key) or "") for key in ("MIGRATION_DATABASE_URL", "DATABASE_URL")), config.get("SUPABASE_URL") or ""))
    except Exception as exc:
        result = {"status": "BLOCKED", "failure": str(exc) if isinstance(exc, GateBlocked) else type(exc).__name__}
    assert_sanitized_evidence(result)
    payload = json.dumps(result, sort_keys=True)
    if args.evidence:
        args.evidence.write_text(payload, encoding="utf8")
    print(payload)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
