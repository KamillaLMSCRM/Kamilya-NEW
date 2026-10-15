#!/usr/bin/env python3
"""Offline-safe bounded verifier for source migrations 0156 and 0180."""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from dotenv import dotenv_values, load_dotenv
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

OPS = Path(__file__).resolve().parent
ROOT = OPS.parents[1]
API_ROOT = ROOT / "apps" / "api"
M0156 = API_ROOT / "alembic/versions/0156_generation_model_routing.py"
M0180 = API_ROOT / "alembic/versions/0180_optional_chatgpt_reserve.py"
SCHEMA_RE = re.compile(r"^reserve_[0-9a-f]{12}$")
OFF = ["deepseek", "qwen38_flash_next", "glm53_flash"]
RESERVE = OFF + ["chatgpt_reserve"]

class GateBlocked(RuntimeError):
    pass

def safe_schema_name(value: str) -> str:
    if not SCHEMA_RE.fullmatch(value):
        raise GateBlocked("unsafe_schema_name")
    return value

def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()

def source_provenance(expected_sha: str, supabase_url: str) -> dict[str, Any]:
    """Bind only the executed gate/migrations to an immutable local Git object."""
    if not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
        raise GateBlocked("invalid_expected_release_sha")
    hashes: dict[str, str] = {}
    for path in (M0156, M0180, Path(__file__).resolve()):
        relative = path.relative_to(ROOT).as_posix()
        try:
            committed = subprocess.check_output(
                ["git", "show", f"{expected_sha}:{relative}"], cwd=ROOT,
                stderr=subprocess.DEVNULL, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            raise GateBlocked("release_source_unavailable") from None
        # Git stores LF while Windows may check out CRLF; Python executes equivalent text.
        actual = path.read_bytes().replace(b"\r\n", b"\n")
        if actual != committed.replace(b"\r\n", b"\n"):
            raise GateBlocked("release_source_bytes_mismatch")
        hashes[relative] = hashlib.sha256(actual).hexdigest()
    return {
        "release_sha": expected_sha, "source_sha256_lf": hashes,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "canonical_project_sha256": hashlib.sha256(supabase_url.rstrip("/").encode()).hexdigest(),
    }

def _module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise GateBlocked("migration_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

async def apply_source_migration(connection: Any, schema: str, path: Path, action: str) -> None:
    safe_schema_name(schema)
    migration = _module(path, f"reserve_{path.stem}_{action}")
    if action not in {"upgrade", "downgrade"}:
        raise GateBlocked("unsupported_migration_action")
    def run(sync: Any) -> None:
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        context = MigrationContext.configure(sync, opts={"version_table_schema": schema})
        with Operations.context(context):
            getattr(migration, action)()
    await connection.run_sync(run)

async def cleanup(engine: Any, schema: str) -> bool:
    safe_schema_name(schema)
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await connection.commit()
            exists = await connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:schema)"), {"schema": schema})
            return not bool(exists)
    except Exception:
        return False

async def public_snapshot(connection: Any) -> tuple[str, tuple[str, ...], str]:
    revision = str(await connection.scalar(text("SELECT version_num FROM public.alembic_version")))
    result = await connection.execute(text("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f') ORDER BY c.relname"))
    tables = tuple(result.scalars().all())
    singleton = str(await connection.scalar(text("SELECT md5(COALESCE(string_agg(id::text||':'||ordered_model_ids::text||':'||revision::text||':'||COALESCE(updated_by::text,'')||':'||updated_at::text,'|'),'') ) FROM public.generation_model_routing WHERE id=1")))
    return revision, tables, singleton

async def run_gate(owner_url: str, runtime_url: str, supabase_url: str) -> dict[str, Any]:
    from kb_rag_isolated_dev_gate import normalize_database_url, same_supabase_project
    from source_actuality_dev_gate import verify_runtime_role
    owner_url, runtime_url = map(normalize_database_url, (owner_url, runtime_url))
    if not all(same_supabase_project(url, supabase_url) for url in (owner_url, runtime_url)):
        raise GateBlocked("canonical_dev_identity_mismatch")
    if (make_url(runtime_url).username or "").split(".")[0] != "lms_app":
        raise GateBlocked("wrong_runtime_role")
    if any(make_url(url).database != "postgres" for url in (owner_url, runtime_url)):
        raise GateBlocked("unexpected_database")
    schema = f"reserve_{uuid.uuid4().hex[:12]}"
    owner = create_async_engine(owner_url, poolclass=NullPool, hide_parameters=True)
    runtime = create_async_engine(runtime_url, poolclass=NullPool, hide_parameters=True)
    before = None
    after_cleanup = None
    failure: Exception | None = None
    checks: dict[str, Any] = {}
    created = False
    try:
        async with runtime.connect() as connection:
            await verify_runtime_role(connection)
        async with owner.begin() as connection:
            before = await public_snapshot(connection)
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
            await connection.execute(text(f'REVOKE ALL ON SCHEMA "{schema}" FROM PUBLIC'))
            await connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO lms_app'))
            await connection.execute(text(f'CREATE TABLE "{schema}".users (id uuid PRIMARY KEY)'))
            await connection.execute(text(f'CREATE TABLE "{schema}".alembic_version (version_num varchar(32) PRIMARY KEY)'))
            await apply_source_migration(connection, schema, M0156, "upgrade")
            await connection.execute(text(f'INSERT INTO "{schema}".alembic_version VALUES (\'0179\')'))
            row_before_0180 = tuple((await connection.execute(text(f'SELECT id, ordered_model_ids, revision, updated_by, updated_at FROM "{schema}".generation_model_routing WHERE id=1'))).one())
            policies_before = tuple((await connection.execute(text("SELECT polname, polcmd, pg_get_expr(polqual, polrelid), pg_get_expr(polwithcheck, polrelid) FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:schema AND c.relname='generation_model_routing' ORDER BY polname"), {"schema": schema})).all())
            await apply_source_migration(connection, schema, M0180, "upgrade")
            route = await connection.scalar(text(f'SELECT ordered_model_ids FROM "{schema}".generation_model_routing WHERE id=1'))
            if route != OFF:
                raise GateBlocked("default_route_not_off")
            checks["off_default"] = True
            checks["source_bound_0156_0180"] = True
            if row_before_0180 != tuple((await connection.execute(text(f'SELECT id, ordered_model_ids, revision, updated_by, updated_at FROM "{schema}".generation_model_routing WHERE id=1'))).one()):
                raise GateBlocked("full_row_changed_on_upgrade")
            checks["full_row_stable_on_upgrade"] = True
            await connection.execute(text(f'UPDATE "{schema}".generation_model_routing SET ordered_model_ids=CAST(:route AS jsonb), revision=2 WHERE id=1'), {"route": json.dumps(RESERVE)})
            if await connection.scalar(text(f'SELECT ordered_model_ids FROM "{schema}".generation_model_routing WHERE id=1')) != RESERVE:
                raise GateBlocked("reserve_upgrade_failed")
            checks["owner_constraint_accepts_reserve"] = True
            try:
                async with connection.begin_nested():
                    await apply_source_migration(connection, schema, M0180, "downgrade")
            except Exception as exc:
                if getattr(getattr(exc, "orig", None), "sqlstate", None) != "23514":
                    raise GateBlocked("downgrade_reserve_wrong_sqlstate") from None
                checks["downgrade_reserve_refused_transactionally"] = True
            else:
                raise GateBlocked("downgrade_reserve_silently_accepted")
            await connection.execute(text(f'UPDATE "{schema}".generation_model_routing SET ordered_model_ids=CAST(:route AS jsonb), revision=3 WHERE id=1'), {"route": json.dumps(OFF)})
            disabled_row = tuple((await connection.execute(text(f'SELECT id, ordered_model_ids, revision, updated_by, updated_at FROM "{schema}".generation_model_routing WHERE id=1'))).one())
            await apply_source_migration(connection, schema, M0180, "downgrade")
            if disabled_row != tuple((await connection.execute(text(f'SELECT id, ordered_model_ids, revision, updated_by, updated_at FROM "{schema}".generation_model_routing WHERE id=1'))).one()):
                raise GateBlocked("downgrade_rewrote_row")
            try:
                async with connection.begin_nested():
                    await connection.execute(text(f'UPDATE "{schema}".generation_model_routing SET ordered_model_ids=CAST(:route AS jsonb) WHERE id=1'), {"route": json.dumps(RESERVE)})
            except Exception as exc:
                if getattr(getattr(exc, "orig", None), "sqlstate", None) != "23514":
                    raise GateBlocked("old_constraint_wrong_sqlstate") from None
            else:
                raise GateBlocked("old_constraint_allowed_reserve")
            await apply_source_migration(connection, schema, M0180, "upgrade")
            if disabled_row != tuple((await connection.execute(text(f'SELECT id, ordered_model_ids, revision, updated_by, updated_at FROM "{schema}".generation_model_routing WHERE id=1'))).one()):
                raise GateBlocked("reupgrade_rewrote_row")
            if await connection.scalar(text(f'SELECT ordered_model_ids FROM "{schema}".generation_model_routing WHERE id=1')) != OFF:
                raise GateBlocked("reupgrade_route_not_off")
            checks["explicit_disable_downgrade_reupgrade_off"] = True
            rls = await connection.execute(text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:s AND c.relname='generation_model_routing'"), {"s": schema})
            if rls.one() != (True, True):
                raise GateBlocked("force_rls_missing")
            checks["force_rls"] = True
            policies_after = tuple((await connection.execute(text("SELECT polname, polcmd, pg_get_expr(polqual, polrelid), pg_get_expr(polwithcheck, polrelid) FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:schema AND c.relname='generation_model_routing' ORDER BY polname"), {"schema": schema})).all())
            if policies_after != policies_before:
                raise GateBlocked("policy_snapshot_changed")
            checks["policy_snapshot_stable"] = True
            invalid_routes = ((["deepseek", "unknown_provider"], "closed_catalog"), (["qwen38_flash_next", "deepseek"], "deepseek_not_first"), (OFF + ["chatgpt_reserve", "glm53_flash"], "max_four"), (["deepseek", "glm53_flash", "glm53_flash"], "duplicate"), ([], "empty_route"))
            for invalid, code in invalid_routes:
                try:
                    async with connection.begin_nested():
                        await connection.execute(text(f'UPDATE "{schema}".generation_model_routing SET ordered_model_ids=CAST(:route AS jsonb) WHERE id=1'), {"route": json.dumps(invalid)})
                except Exception as exc:
                    if getattr(getattr(exc, "orig", None), "sqlstate", None) != "23514":
                        raise GateBlocked(f"{code}_wrong_sqlstate") from None
                else:
                    raise GateBlocked(f"{code}_accepted")
            checks["constraint_negatives"] = True
        async with runtime.connect() as connection:
            await verify_runtime_role(connection)
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}", pg_catalog'))
            for tenant in (uuid.uuid4(), uuid.uuid4()):
                await connection.execute(text("SELECT set_config('app.tenant_id', :tenant, true), set_config('app.is_superadmin', 'false', true)"), {"tenant": str(tenant)})
                if await connection.scalar(text(f'SELECT ordered_model_ids FROM "{schema}".generation_model_routing WHERE id=1')) != OFF:
                    raise GateBlocked("runtime_global_route_read_failed")
                if (await connection.execute(text(f'UPDATE "{schema}".generation_model_routing SET revision=revision+1 WHERE id=1'))).rowcount != 0:
                    raise GateBlocked("ordinary_runtime_update_allowed")
            await connection.execute(text("SELECT set_config('app.is_superadmin', 'true', true)"))
            if (await connection.execute(text(f'UPDATE "{schema}".generation_model_routing SET ordered_model_ids=CAST(:route AS jsonb), revision=revision+1 WHERE id=1'), {"route": json.dumps(RESERVE)})).rowcount != 1:
                raise GateBlocked("runtime_superadmin_update_denied")
            if await connection.scalar(text(f'SELECT ordered_model_ids FROM "{schema}".generation_model_routing WHERE id=1')) != RESERVE:
                raise GateBlocked("runtime_superadmin_wrong_route")
            await connection.rollback()
            checks["runtime_non_bypass"] = True
            checks["two_ordinary_contexts_read_global_write_denied"] = True
            checks["superadmin_runtime_write_rolled_back"] = True
        async with owner.connect() as connection:
            if before != await public_snapshot(connection):
                raise GateBlocked("public_snapshot_changed")
        checks["public_snapshot_neutral"] = True
    except Exception as exc:
        failure = exc
    finally:
        cleanup_ok = await cleanup(owner, schema) if created else True
        try:
            async with owner.connect() as connection:
                after_cleanup = await public_snapshot(connection)
        except Exception:
            after_cleanup = None
        await owner.dispose()
        await runtime.dispose()
    neutral = before is not None and after_cleanup == before
    checks["owned_schema_absent"] = cleanup_ok
    return {
        "status": "PASS" if failure is None and cleanup_ok and neutral else "BLOCKED",
        "scope": "supabase_dev_owned_reserve_schema", "owned_schema": schema,
        "checks": checks, "cleanup": cleanup_ok, "public_schema_neutral": neutral,
        "failure": (str(failure) if isinstance(failure, GateBlocked) else type(failure).__name__) if failure else None,
        "public_migration": "NOT_RUN",
    }

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--evidence-file", type=Path)
    parser.add_argument("--expected-release-sha", default="")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "BLOCKED", "error_class": "execute_flag_required"}))
        return 2
    from dev_public_schema_gate import resolve_env_file
    canonical = resolve_env_file(None)
    if args.env_file.resolve() != canonical.resolve():
        print(json.dumps({"status": "BLOCKED", "error_class": "noncanonical_env_path"}))
        return 2
    config = dotenv_values(canonical)
    load_dotenv(canonical, override=True)
    sys.path.insert(0, str(API_ROOT))
    owner = config.get("MIGRATION_DATABASE_URL") or ""
    runtime = config.get("DATABASE_URL") or ""
    supabase = config.get("SUPABASE_URL") or ""
    if not owner or not runtime or not supabase:
        print(json.dumps({"status": "BLOCKED", "error_class": "required_env_missing"}))
        return 2
    try:
        provenance = source_provenance(args.expected_release_sha, supabase)
        evidence = asyncio.run(run_gate(owner, runtime, supabase))
        evidence["provenance"] = provenance
        evidence["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    except GateBlocked as exc:
        print(json.dumps({"status": "BLOCKED", "error_class": str(exc).split(";", 1)[0], "cleanup_status": "reported"}))
        return 1
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error_class": type(exc).__name__, "cleanup_status": "unknown"}))
        return 1
    if args.evidence_file:
        path = args.evidence_file.resolve()
        if ROOT.resolve() not in path.parents:
            print(json.dumps({"status": "BLOCKED", "error_class": "unsafe_evidence_path"}))
            return 2
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
