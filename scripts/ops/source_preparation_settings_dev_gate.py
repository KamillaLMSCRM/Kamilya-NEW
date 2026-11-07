#!/usr/bin/env python3
"""Isolated DEV proof for 0182 -> 0186. Never targets public migration state."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values, load_dotenv
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from kb_rag_isolated_dev_gate import GateBlocked, assert_sanitized_evidence, normalize_database_url, same_supabase_project
from runtime_settings_dev_gate import migration as migration_0182, safe_schema
from source_actuality_dev_gate import public_snapshot, verify_runtime_role

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/api"))
SOURCE = ROOT / "apps/api/alembic/versions/0186_source_preparation_settings.py"
BASE = ROOT / "apps/api/alembic/versions/0182_runtime_settings.py"


async def migration_0186(db, schema, *, downgrade=False):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    safe_schema(schema)
    spec = importlib.util.spec_from_file_location("owned_source_preparation_migration", SOURCE)
    if spec is None or spec.loader is None:
        raise GateBlocked("migration_source_unavailable")
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
    source_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (BASE, SOURCE)}
    actor = uuid4()
    created = cleanup = neutral = False
    before = failure = None
    checks = []
    stage = "preflight"

    async def context(db, platform=False):
        await db.execute(text(f"SET LOCAL search_path TO {qualified},pg_catalog"))
        await db.execute(text("SELECT set_config('app.is_superadmin',:v,true),set_config('app.tenant_id','',true)"),
                         {"v": str(platform).lower()})
        for table in ("runtime_settings", "runtime_settings_history", "users"):
            actual = await db.scalar(text("SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.oid=to_regclass(:t)"), {"t": table})
            if actual != schema:
                raise GateBlocked("unsafe_public_table_resolution")

    async def custody(db):
        row = await db.scalar(text(f"SELECT row_to_json(t)::text FROM (SELECT * FROM {qualified}.runtime_settings ORDER BY id) t"))
        history = (await db.execute(text(f"SELECT row_to_json(t)::text FROM (SELECT * FROM {qualified}.runtime_settings_history ORDER BY revision) t"))).scalars().all()
        return hashlib.sha256(json.dumps([row, history], separators=(",", ":")).encode()).hexdigest()

    try:
        async with runtime.connect() as db:
            await verify_runtime_role(db)
        stage = "owned_fresh_and_populated_upgrade"
        async with owner.begin() as db:
            before = await public_snapshot(db)
            await db.execute(text(f"CREATE SCHEMA {qualified}"))
            created = True
            await db.execute(text(f"REVOKE ALL ON SCHEMA {qualified} FROM PUBLIC"))
            await db.execute(text(f"GRANT USAGE ON SCHEMA {qualified} TO lms_app"))
            await db.execute(text(f"CREATE TABLE {qualified}.users(id uuid PRIMARY KEY)"))
            await db.execute(text(f"INSERT INTO {qualified}.users(id) VALUES(:id)"), {"id": actor})
            await migration_0182(db, schema)
            await migration_0186(db, schema)
            await migration_0186(db, schema, downgrade=True)
        checks.append("fresh_0182_0186_upgrade")
        from app.modules.admin.runtime_configuration.catalog import InvalidSettings
        from app.modules.admin.runtime_configuration.service import RuntimeSettingsService, SettingsConflict
        from app.models.registry import load_all_models
        load_all_models()
        async with AsyncSession(runtime, expire_on_commit=False) as db:
            await context(db, True)
            service = RuntimeSettingsService(db)
            result = await service.update(revision=1, changes={"assignment.deepseek_seconds": 20},
                                          reason="Synthetic old setting", actor_id=actor)
            if result["revision"] != 2:
                raise GateBlocked("old_setting_update_failed")
        async with owner.begin() as db:
            old_hash = await custody(db)
            await migration_0186(db, schema)
            if await custody(db) != old_hash:
                raise GateBlocked("upgrade_changed_existing_state_or_history")
            flags = (await db.execute(text("SELECT relrowsecurity,relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:s AND c.relname IN ('runtime_settings','runtime_settings_history')"), {"s": schema})).all()
            if len(flags) != 2 or any(tuple(row) != (True, True) for row in flags):
                raise GateBlocked("force_rls_missing")
        checks += ["populated_upgrade_state_history_hash_unchanged", "force_rls_both_tables"]
        stage = "runtime_authorization_and_validation"
        async with AsyncSession(runtime, expire_on_commit=False) as db:
            await context(db)
            result = await db.execute(text("UPDATE runtime_settings SET revision=3 WHERE id=1"))
            if result.rowcount != 0:
                raise GateBlocked("ordinary_runtime_write_permitted")
            await db.rollback()
            await context(db, True)
            service = RuntimeSettingsService(db)
            result = await service.update(revision=2, changes={"source_preparation.vision_batch_size": 3},
                                          reason="Synthetic source setting", actor_id=actor)
            if result["revision"] != 3:
                raise GateBlocked("new_setting_update_failed")
            await context(db, True)
            history = await service.history()
            if len(history) != 2 or history[0]["after"].get("source_preparation.vision_batch_size") != 3:
                raise GateBlocked("new_setting_audit_missing")
            for invalid in ({"source_preparation.unknown": 1}, {"source_preparation.vision_batch_size": True},
                            {"source_preparation.vision_batch_size": 1.5}, {"source_preparation.vision_batch_size": 5}):
                try:
                    async with db.begin_nested():
                        await db.execute(text("UPDATE runtime_settings SET overrides=CAST(:v AS jsonb) WHERE id=1"), {"v": json.dumps(invalid)})
                except DBAPIError as exc:
                    if getattr(exc.orig, "sqlstate", None) not in {"23514", "22P02"}:
                        raise
                else:
                    raise GateBlocked("raw_invalid_override_accepted")
                try:
                    await service.update(revision=3, changes=invalid, reason="Invalid source setting", actor_id=actor)
                except InvalidSettings:
                    await db.rollback()
                    await context(db, True)
                else:
                    raise GateBlocked("invalid_service_override_accepted")
            try:
                await service.update(revision=2, changes={"source_preparation.vision_batch_size": 2},
                                     reason="Stale source setting", actor_id=actor)
            except SettingsConflict:
                await db.rollback()
            else:
                raise GateBlocked("stale_revision_accepted")
        checks += ["ordinary_role_write_denied", "new_setting_audited", "unknown_bool_fraction_range_rejected", "stale_revision_conflict"]
        stage = "downgrade_guard_and_reupgrade"
        async with owner.begin() as db:
            before_downgrade = await custody(db)
            try:
                async with db.begin_nested():
                    await migration_0186(db, schema, downgrade=True)
            except DBAPIError as exc:
                if getattr(exc.orig, "sqlstate", None) != "23514":
                    raise
            else:
                raise GateBlocked("downgrade_with_override_accepted")
            if await custody(db) != before_downgrade:
                raise GateBlocked("failed_downgrade_changed_data")
        async with AsyncSession(runtime, expire_on_commit=False) as db:
            await context(db, True)
            result = await RuntimeSettingsService(db).revert(revision=3, target_revision=2,
                       reason="Revert synthetic source setting", actor_id=actor)
            if result["revision"] != 4:
                raise GateBlocked("audited_revert_failed")
        async with owner.begin() as db:
            audit_hash = await custody(db)
            await migration_0186(db, schema, downgrade=True)
            await migration_0186(db, schema)
            if await custody(db) != audit_hash:
                raise GateBlocked("downgrade_reupgrade_changed_audit")
        checks += ["downgrade_guard_preserves_rows", "audited_revert_downgrade_reupgrade_preserves_history"]
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
    if any(hashlib.sha256(p.read_bytes()).hexdigest() != source_hashes[p.name] for p in (BASE, SOURCE)):
        failure = "migration_source_changed_during_gate"
    return {"status": "PASS" if failure is None and cleanup and neutral else "BLOCKED", "stage": stage,
            "failure": failure, "checks": checks, "cleanup": cleanup, "public_schema_neutral": neutral,
            "scope": "owned_supabase_dev_runtime0182_0186", "public_business_row_equivalence": "NOT_VERIFIED_NOT_WRITTEN",
            "public_migration": "NOT_RUN", "production_actions": 0}


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
