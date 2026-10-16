#!/usr/bin/env python3
"""Actual owned Supabase DEV proof; fake provider only, never public writes."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from time import monotonic
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts/ops"
API = ROOT / "apps/api"
for path in (OPS, API):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import event, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from workbench_document_dev_gate import (  # noqa: E402
    GateBlocked, apply_0175, assert_sanitized_evidence, canonical_config, cleanup,
    clone_tables, public_snapshot, safe_schema, same_supabase_project, sanitize_failure,
    set_context, verify_runtime_role,
)

MIGRATION = API / "alembic/versions/0181_document_preparation_dialogue.py"
SOURCES = (
    Path(__file__).resolve(), OPS / "document_dialogue_dev_checks.py", OPS / "document_content_dev_checks.py", MIGRATION,
    OPS / "workbench_document_dev_gate.py", OPS / "source_actuality_dev_gate.py",
    API / "alembic/versions/0175_workbench_document_plans.py",
    *(API / f"app/modules/methodologist_workbench/{name}.py" for name in (
        "document_dialogue", "document_dialogue_models", "document_dialogue_schemas",
        "document_service", "document_models", "document_schemas", "document_intent", "document_router", "document_answers")),
    API / "app/modules/ai/ingestion.py", API / "app/modules/ai/lexical_retrieval.py", API / "app/modules/ai/llm_client.py",
    API / "app/modules/documents/router.py",
    API / "app/modules/admin/superadmin/service.py", API / "app/models/registry.py",
    API / "app/modules/ai/budget.py", API / "app/core/auth.py",
    API / "app/modules/ai/job_service.py", API / "app/modules/ai/router.py",
    *(API / f"app/models/{name}.py" for name in (
        "tenants", "users", "user_roles", "document", "ai_job", "tenant_settings", "tenant_llm_usage")),
    ROOT / "docs/product/contract-modules/methodologist-workbench/contracts/DOCUMENT_DIALOGUE_V1.md",
    ROOT / "docs/product/contract-modules/methodologist-workbench/contracts/DOCUMENT_CONTENT_DIALOGUE_V1.md",
    ROOT / "docs/product/contract-modules/methodologist-workbench/contracts/DOCUMENT_CONTENT_RETRIEVAL_ADDENDUM_V1.md",
    ROOT / "docs/product/contract-modules/methodologist-workbench/contracts/DOCUMENT_CONTENT_RETRIEVAL_ADDENDUM_V1_1.md",
    ROOT / "docs/product/contract-modules/methodologist-workbench/contracts/DOCUMENT_CONTENT_RETRIEVAL_ADDENDUM_V1_2.md",
    ROOT / "docs/product/contract-modules/methodologist-workbench/contracts/DOCUMENT_CONTENT_RETRIEVAL_ADDENDUM_V1_3.md",
    ROOT / "docs/product/contract-modules/methodologist-workbench/contracts/DOCUMENT_CONTENT_RETRIEVAL_ADDENDUM_V1_4.md",
    ROOT / "docs/product/contract-modules/methodologist-workbench/contracts/DOCUMENT_CONTENT_RETRIEVAL_ADDENDUM_V1_5.md",
    ROOT / "docs/product/contract-modules/methodologist-workbench/contracts/DOCUMENT_CONTENT_RETRIEVAL_ADDENDUM_V1_6.md",
    ROOT / "docs/product/contract-modules/methodologist-workbench/contracts/DOCUMENT_CONTENT_RETRIEVAL_ADDENDUM_V1_7.md",
    ROOT / "docs/product/contract-modules/methodologist-workbench/contracts/DOCUMENT_CONTENT_RETRIEVAL_ADDENDUM_V1_8.md",
    ROOT / "docs/product/contract-modules/methodologist-workbench/contracts/DOCUMENT_CONTENT_RETRIEVAL_ADDENDUM_V1_9.md",
    ROOT / "docs/product/contract-modules/methodologist-workbench/contracts/DOCUMENT_CONTENT_COMPLETENESS_ADDENDUM_V1_10.md",
    API / "tests/unit/test_document_completeness.py",
    API / "tests/unit/test_document_answers.py",
)
EVIDENCE_RUNS = ("DOCUMENT55-20261015", "DOCUMENT56-20261015", "DOCUMENT57-20261015", "DOCUMENT58-20261016")
REQUIRED_CHECKS = frozenset({
    "empty_upgrade_downgrade_reupgrade", "table_acl_force_rls", "owner_reload_no_inference",
    "foreign_tenant_denied", "sibling_actor_denied", "role_denied", "no_context_denied",
    "exact_create_replay", "concurrent_create_replay", "save_revision_stale_preview",
    "exact_message_replay_one_fake_call", "changed_request_conflict", "concurrent_pending_dedup",
    "provider_connection_released", "cancel_interrupted", "late_response_refused",
    "source_drift_stale", "source_move_delete_fail_closed", "preview_expiry_replacement",
    "submitted_unknown_plan_blocked", "terminal_rows_immutable", "tenant_actor_cascade",
    "purge_exchange_before_task", "populated_downgrade_refused", "bounded_connection_peak",
    "provider_failure_durable", "bounded_recall", "single_job_confirmation",
    "reservation_commit_cancellation",
    "budget_denial_no_inference",
    "cross_owner_writes_denied", "authorized_purge_exact_rows",
    "content_real_retrieval_persistence_replay", "content_provider_connection_released",
    "content_source_sql_types_quote_hash", "content_foreign_actor_tenant_denied",
    "content_stale_citation_denied", "content_recall_separate_from_draft",
    "content_real_budget_refund", "content_preserves_frozen_preview",
    "content_active_pointer_race_denied",
    "content_not_found_pointer_race_denied",
    "content_not_found_scope_quote_persistence",
    "content_invalid_response_private_refund",
    "content_incomplete_answer_private_refund_no_retry",
})
PUBLIC_GUARDED_TABLES = (
    "tenants", "users", "user_roles", "documents", "ai_jobs", "workbench_document_plans",
    "tenant_settings", "tenant_llm_usage", "workbench_document_dialogues", "workbench_document_dialogue_exchanges",
)


async def public_state_snapshot(connection):
    """SQL-side row hashes for affected neighbors plus public catalog definitions.

    No tenant row, credential or function body leaves PostgreSQL. The canonical
    revision/relation inventory alone is insufficient proof of data neutrality.
    """
    inventory = await public_snapshot(connection)
    data = {}
    for table in PUBLIC_GUARDED_TABLES:
        if not re.fullmatch(r"[a-z_]+", table):
            raise GateBlocked("unsafe_public_guard_table")
        exists = await connection.scalar(text("SELECT to_regclass(:table) IS NOT NULL"), {"table": f"public.{table}"})
        if not exists:
            data[table] = None
            continue
        row = (await connection.execute(text(f'''SELECT count(*),md5(COALESCE(
            string_agg(md5(row_to_json(t)::text),'' ORDER BY md5(row_to_json(t)::text)),''))
            FROM public."{table}" t'''))).one()
        data[table] = tuple(row)
    catalog = (await connection.execute(text("""SELECT kind,name,digest FROM (
        SELECT 'relation' kind,c.relname name,md5(ROW(c.relkind,c.relrowsecurity,c.relforcerowsecurity,c.relacl)::text) digest
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
        UNION ALL SELECT 'column',c.relname||'.'||a.attnum::text,
        md5(ROW(a.attname,a.atttypid,a.atttypmod,a.attnotnull,a.attidentity,a.attgenerated,a.attacl,pg_get_expr(d.adbin,d.adrelid))::text)
        FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum WHERE n.nspname='public' AND a.attnum>0 AND NOT a.attisdropped
        UNION ALL SELECT 'function',p.oid::text,md5(ROW(pg_get_functiondef(p.oid),p.proacl)::text)
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.prokind IN ('f','p')
        UNION ALL SELECT 'constraint',c.oid::text,md5(pg_get_constraintdef(c.oid)) FROM pg_constraint c
        JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='public'
        UNION ALL SELECT 'policy',p.oid::text,md5(ROW(p.polname,p.polcmd,p.polroles,pg_get_expr(p.polqual,p.polrelid),pg_get_expr(p.polwithcheck,p.polrelid))::text)
        FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
        UNION ALL SELECT 'trigger',t.oid::text,md5(pg_get_triggerdef(t.oid)) FROM pg_trigger t
        JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
        UNION ALL SELECT 'index',i.indexrelid::text,md5(pg_get_indexdef(i.indexrelid)) FROM pg_index i
        JOIN pg_class c ON c.oid=i.indrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
    ) objects ORDER BY kind,name,digest"""))).all()
    return {"inventory": inventory, "rows": data, "catalog": [tuple(row) for row in catalog]}


def validate_checks(checks, required=REQUIRED_CHECKS):
    if set(checks) != set(required) or len(checks) != len(set(checks)):
        raise GateBlocked("required_checks_missing")


def source_manifest():
    output = {}
    for path in SOURCES:
        resolved = path.resolve()
        if ROOT.resolve() not in resolved.parents or not resolved.is_file():
            raise GateBlocked("critical_source_missing")
        output[resolved.relative_to(ROOT).as_posix()] = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if len(output) != len(SOURCES):
        raise GateBlocked("duplicate_critical_source")
    return output


def new_schema():
    return f"workbench_{uuid4().hex[:12]}"


def validate_runtime_url(url):
    if (make_url(url).username or "").split(".", 1)[0] != "lms_app":
        raise GateBlocked("wrong_runtime_role")


def sanitized_result(status, checks=None, failure=None):
    return {"status": status, "checks": checks or [], **({"failure": failure} if failure else {})}


async def apply_0181(connection, schema, operation="upgrade"):
    safe_schema(schema)
    if operation not in {"upgrade", "downgrade"}:
        raise GateBlocked("invalid_migration_request")
    spec = importlib.util.spec_from_file_location("document_preparation_0181", MIGRATION)
    if spec is None or spec.loader is None:
        raise GateBlocked("migration_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.revision != "0181" or module.down_revision != "0180":
        raise GateBlocked("migration_identity_mismatch")

    def execute(sync):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        with Operations.context(MigrationContext.configure(sync, opts={"version_table_schema": schema})):
            getattr(module, operation)()

    await connection.run_sync(execute)


def failure_detail(exc):
    result = {}
    cause = exc
    for _ in range(4):
        state = getattr(getattr(cause, "orig", None), "sqlstate", None)
        if isinstance(state, str) and re.fullmatch(r"[A-Z0-9]{5}", state):
            result["state"] = state
            break
        cause = getattr(cause, "__cause__", None) or getattr(cause, "__context__", None)
        if cause is None:
            break
    frames = exc.__traceback__
    while frames:
        file = Path(frames.tb_frame.f_code.co_filename).resolve()
        if file in {path.resolve() for path in SOURCES}:
            result.update(file=file.relative_to(ROOT).as_posix(), line=frames.tb_lineno)
        frames = frames.tb_next
    return result


async def run_gate(owner_url, runtime_url, supabase_url, schema):
    safe_schema(schema)
    validate_runtime_url(runtime_url)
    if not all(same_supabase_project(url, supabase_url) for url in (owner_url, runtime_url)):
        raise GateBlocked("canonical_dev_identity_mismatch")
    frozen = source_manifest()
    started = monotonic()
    options = dict(poolclass=NullPool, hide_parameters=True, connect_args={"timeout": 15,
        "command_timeout": 45, "server_settings": {"statement_timeout": "45000", "lock_timeout": "5000"}})
    owner = create_async_engine(owner_url, **options)
    runtime = create_async_engine(runtime_url, **options)
    active = set()
    peak = 0

    def checkout(label, connection):
        nonlocal peak
        active.add((label, id(connection)))
        peak = max(peak, len(active))
        if peak > 3:
            raise GateBlocked("connection_cap_exceeded")

    for label, engine in (("owner", owner), ("runtime", runtime)):
        event.listen(engine.sync_engine, "checkout", lambda c, *_a, label=label: checkout(label, c))
        event.listen(engine.sync_engine, "checkin", lambda c, *_a, label=label: active.discard((label, id(c))))

    @event.listens_for(runtime.sync_engine, "begin")
    def isolated_transaction(connection):
        connection.exec_driver_sql(f"SET LOCAL search_path TO {safe_schema(schema)}, pg_catalog")

    owned = cleaned = neutral = unchanged = False
    before = after = None
    checks = []
    failure = readback_failure = None
    detail = {}
    stage = "identity"
    try:
        async with runtime.connect() as connection:
            await verify_runtime_role(connection)
        async with owner.connect() as connection:
            before = await public_state_snapshot(connection)
            if await connection.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:s)"), {"s": schema}):
                raise GateBlocked("schema_collision")
            owned = True
            stage = "clone_migration"
            await clone_tables(connection, schema)
            await set_context(connection, schema)
            for table in ("tenant_settings", "tenant_llm_usage"):
                # Synthetic neighbor policies, not a copy/claim of public policy.
                await connection.execute(text(f"CREATE TABLE {safe_schema(schema)}.{table} (LIKE public.{table} INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES)"))
                await connection.execute(text(f"REVOKE ALL ON {safe_schema(schema)}.{table} FROM PUBLIC,lms_app"))
                await connection.execute(text(f"GRANT SELECT,INSERT,UPDATE,DELETE ON {safe_schema(schema)}.{table} TO lms_app"))
                await connection.execute(text(f"ALTER TABLE {safe_schema(schema)}.{table} ENABLE ROW LEVEL SECURITY"))
                await connection.execute(text(f"ALTER TABLE {safe_schema(schema)}.{table} FORCE ROW LEVEL SECURITY"))
                predicate = "tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid"
                await connection.execute(text(f"CREATE POLICY gate_{table}_tenant ON {safe_schema(schema)}.{table} FOR ALL TO lms_app USING({predicate}) WITH CHECK({predicate})"))
            await apply_0175(connection, schema)
            await apply_0181(connection, schema)
            await apply_0181(connection, schema, "downgrade")
            await apply_0181(connection, schema)
            await connection.commit()
            checks.append("empty_upgrade_downgrade_reupgrade")
        stage = "document_dialogue_transactions"
        from document_dialogue_dev_checks import verify_dialogue

        async with asyncio.timeout(600):
            await verify_dialogue(owner, runtime, schema, checks,
                runtime_connections=lambda: sum(label == "runtime" for label, _identity in active),
                migration=apply_0181)
        checks.append("bounded_connection_peak")
        validate_checks(checks)
        unchanged = source_manifest() == frozen
        if not unchanged:
            raise GateBlocked("critical_source_changed")
    except Exception as exc:
        failure, detail = sanitize_failure(exc), failure_detail(exc)
    finally:
        try:
            pending = [task for task in asyncio.all_tasks() if task.get_name().startswith("document55-") and not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            if owned:
                cleaned = await cleanup(owner, schema)
            if before is not None:
                async with owner.connect() as connection:
                    after = await public_state_snapshot(connection)
                    neutral = before == after
            unchanged = source_manifest() == frozen
        except Exception as exc:
            readback_failure = sanitize_failure(exc)
        await runtime.dispose()
        await owner.dispose()
    passed = failure is None and readback_failure is None and cleaned and neutral and unchanged
    result = dict(status="PASS" if passed else "BLOCKED", scope="document_dialogue_isolated_dev", migration="0181",
        checks=checks, failure=failure, detail=detail, readback_failure=readback_failure,
        cleanup=cleaned, public_schema_neutral=neutral, source_unchanged=unchanged, source_hashes=frozen,
        connection_peak=peak, elapsed_seconds=round(monotonic() - started, 3), stage=stage,
        provider="FAKE_ONLY", email="NOT_USED", production="UNCHANGED",
        public_guarded_tables=list(PUBLIC_GUARDED_TABLES),
        public_before_sha256=hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest() if before else None,
        public_after_sha256=hashlib.sha256(json.dumps(after, sort_keys=True).encode()).hexdigest() if after else None,
        public_changed_tables=sorted(table for table in PUBLIC_GUARDED_TABLES
            if before and after and before["rows"].get(table) != after["rows"].get(table)),
        public_catalog_unchanged=bool(before and after and before["catalog"] == after["catalog"]),
        semantic_quality="NOT_VERIFIED", expired_pending_clock="DETERMINISTIC_APP_CLOCK_PLUS_3_MINUTES")
    assert_sanitized_evidence(result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    try:
        common = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True).stdout.strip()
        if args.env_file.resolve() != (Path(common).parent / ".env").resolve():
            raise GateBlocked("noncanonical_env_file")
        target = args.evidence.resolve()
        allowed_roots = {(ROOT / f".release-evidence/{name}").resolve() for name in EVIDENCE_RUNS}
        if target.parent not in allowed_roots or target.suffix != ".json" or target.exists():
            raise GateBlocked("invalid_evidence_target")
        config = canonical_config(args.env_file)
        load_dotenv(args.env_file, override=True)
        result = asyncio.run(run_gate(config["owner_url"], config["runtime_url"], config["supabase_url"], new_schema()))
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
        print(json.dumps(result))
        return 0 if result["status"] == "PASS" else 1
    except Exception as exc:
        print(json.dumps(sanitized_result("BLOCKED", failure=sanitize_failure(exc))))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
