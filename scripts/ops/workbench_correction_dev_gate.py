#!/usr/bin/env python3
"""Disposable 0176 preview proof, real DEV runtime SQL, no live AI or public writes."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
API_ROOT = ROOT / "apps/api"
OPS_ROOT = ROOT / "scripts/ops"
MIGRATION = API_ROOT / "alembic/versions/0176_workbench_lesson_correction_previews.py"
CLONE_TABLES = (
    "tenants",
    "users",
    "user_roles",
    "documents",
    "courses",
    "modules",
    "lessons",
    "content_blocks",
    "quizzes",
    "questions",
    "quiz_choices",
    "scorm_packages",
    "course_approval_policies",
    "course_approval_revisions",
    "tenant_settings",
    "tenant_llm_usage",
)
REQUIRED_CHECKS = frozenset(
    {
        "synthetic_source_actual_converter",
        "cloned_neighbor_model_shape",
        "block_metadata_orm_response_roundtrip",
        "preview_ready_read",
        "same_key_replay_one_charge",
        "digest_collision_denied",
        "concurrent_same_key_one_claim_charge",
        "zero_budget_rolls_back_claim",
        "failure_closure_refund_once",
        "sibling_denied",
        "foreign_tenant_denied",
        "absent_context_denied",
        "column_acl_denied",
        "terminal_immutable",
        "revoked_role_failed_closure_read_denied",
        "revoked_role_ready_rls_denied",
        "changed_original_blob_refused",
        "immutable_time_trigger",
        "expired_pending_ready_trigger_denied",
        "post_refund_month_guard_preserves_pending",
        "freshness_lessons",
        "freshness_modules",
        "freshness_content_blocks",
        "freshness_quizzes",
        "freshness_questions",
        "freshness_quiz_choices",
        "freshness_documents",
        "freshness_course_approval_policies",
        "stale_ready_read_denied",
        "post_charge_month_guard_rollback",
        "populated_refusal_empty_downgrade_reupgrade",
    }
)


def validate_checks(checks):
    if not REQUIRED_CHECKS <= set(checks) or len(checks) != len(set(checks)):
        raise GateBlocked("required_checks_missing")


def failure_detail(exc):
    """Only source location and protocol code, never error message/SQL/values."""
    detail = {}
    original = getattr(exc, "orig", None)
    code = getattr(original, "sqlstate", None)
    if isinstance(code, str) and re.fullmatch(r"[A-Z0-9]{5}", code):
        detail["state"] = code
    frame = exc.__traceback__
    allowed = {
        OPS_ROOT / "workbench_correction_dev_checks.py",
        MIGRATION,
        Path(__file__),
    }
    while frame:
        source = Path(frame.tb_frame.f_code.co_filename).resolve()
        if source in allowed:
            detail["file"] = source.relative_to(ROOT).as_posix()
            detail["line"] = frame.tb_lineno
        frame = frame.tb_next
    return detail


for path in (API_ROOT, OPS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from workbench_document_dev_gate import (  # noqa: E402
    GateBlocked,
    assert_sanitized_evidence,
    canonical_config,
    cleanup,
    public_snapshot,
    safe_schema,
    same_supabase_project,
    sanitize_failure,
    set_context,
    verify_runtime_role,
)


async def clone_tables(connection, schema: str) -> None:
    """Synthetic neighbor policies, NOT a copy of public operational semantics."""
    qualified = safe_schema(schema)
    sequences = await connection.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_attrdef a JOIN pg_class t ON t.oid=a.adrelid "
            "JOIN pg_namespace n ON n.oid=t.relnamespace "
            "WHERE n.nspname='public' AND t.relname=ANY(:tables) "
            "AND pg_get_expr(a.adbin,a.adrelid) ILIKE '%nextval(%')"
        ),
        {"tables": list(CLONE_TABLES)},
    )
    if sequences:
        raise GateBlocked("sequence_dependent_clone_default")
    await connection.execute(text(f"REVOKE ALL ON SCHEMA {qualified} FROM PUBLIC"))
    await connection.execute(text(f"GRANT USAGE ON SCHEMA {qualified} TO lms_app"))
    for table in CLONE_TABLES:
        await connection.execute(
            text(
                f"CREATE TABLE {qualified}.{table} (LIKE public.{table} INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES)"
            )
        )
        await connection.execute(
            text(f"REVOKE ALL ON {qualified}.{table} FROM PUBLIC,lms_app")
        )
        await connection.execute(
            text(f"GRANT SELECT,INSERT,UPDATE,DELETE ON {qualified}.{table} TO lms_app")
        )
    tenant = "nullif(current_setting('app.tenant_id',true),'')::uuid"
    children = {
        "content_blocks": f"EXISTS (SELECT 1 FROM {qualified}.lessons l WHERE l.id=content_blocks.lesson_id AND l.tenant_id={tenant})",
        "questions": f"EXISTS (SELECT 1 FROM {qualified}.quizzes q WHERE q.id=questions.quiz_id AND q.tenant_id={tenant})",
        "quiz_choices": f"EXISTS (SELECT 1 FROM {qualified}.questions q JOIN {qualified}.quizzes z ON z.id=q.quiz_id WHERE q.id=quiz_choices.question_id AND z.tenant_id={tenant})",
    }
    for table in CLONE_TABLES:
        predicate = (
            children.get(table)
            or f"{'id' if table == 'tenants' else 'tenant_id'}={tenant}"
        )
        await connection.execute(
            text(f"ALTER TABLE {qualified}.{table} ENABLE ROW LEVEL SECURITY")
        )
        await connection.execute(
            text(f"ALTER TABLE {qualified}.{table} FORCE ROW LEVEL SECURITY")
        )
        await connection.execute(
            text(
                f"CREATE POLICY gate_{table}_tenant ON {qualified}.{table} FOR ALL TO lms_app USING ({predicate}) WITH CHECK ({predicate})"
            )
        )
    await connection.execute(
        text(f"""CREATE FUNCTION {qualified}.set_current_tenant(tenant_uuid uuid)
        RETURNS void LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$ BEGIN
        PERFORM set_config('app.tenant_id',tenant_uuid::text,true); END $$""")
    )
    await connection.execute(
        text(f"REVOKE ALL ON FUNCTION {qualified}.set_current_tenant(uuid) FROM PUBLIC")
    )
    await connection.execute(
        text(
            f"GRANT EXECUTE ON FUNCTION {qualified}.set_current_tenant(uuid) TO lms_app"
        )
    )


async def apply_migration(connection, schema: str, operation: str = "upgrade") -> None:
    safe_schema(schema)
    if operation not in {"upgrade", "downgrade"}:
        raise GateBlocked("invalid_migration_request")
    spec = importlib.util.spec_from_file_location("correction_0176", MIGRATION)
    if spec is None or spec.loader is None:
        raise GateBlocked("migration_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.revision != "0176" or module.down_revision != "0175":
        raise GateBlocked("migration_identity_mismatch")

    def apply(sync):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        with Operations.context(
            MigrationContext.configure(sync, opts={"version_table_schema": schema})
        ):
            getattr(module, operation)()

    await connection.run_sync(apply)


async def run_gate(
    owner_url: str, runtime_url: str, supabase_url: str, schema: str
) -> dict[str, Any]:
    safe_schema(schema)
    if not all(
        same_supabase_project(url, supabase_url) for url in (owner_url, runtime_url)
    ):
        raise GateBlocked("canonical_dev_identity_mismatch")
    if (make_url(runtime_url).username or "").split(".", 1)[0] != "lms_app":
        raise GateBlocked("wrong_runtime_role")
    options = {
        "poolclass": NullPool,
        "hide_parameters": True,
        "connect_args": {
            "timeout": 15,
            "command_timeout": 30,
            "server_settings": {"statement_timeout": "30000", "lock_timeout": "5000"},
        },
    }
    owner_engine = create_async_engine(owner_url, **options)
    runtime_engine = create_async_engine(runtime_url, **options)

    @event.listens_for(runtime_engine.sync_engine, "begin")
    def owned_transaction(connection):
        connection.exec_driver_sql(
            f"SET LOCAL search_path TO {safe_schema(schema)}, pg_catalog"
        )

    owned, cleanup_ok, neutral = False, False, False
    before, failure, readback_failure, checks = None, None, None, []
    stage = "identity"
    detail = {}
    try:
        async with runtime_engine.connect() as connection:
            await verify_runtime_role(connection)
        async with owner_engine.connect() as connection:
            before = await public_snapshot(connection)
            if await connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:schema)"
                ),
                {"schema": schema},
            ):
                raise GateBlocked("schema_collision")
            # Commit only owned creation first. Later cloning/migration failures
            # cannot leave an untracked committed schema; collision is never owned.
            await connection.execute(text(f"CREATE SCHEMA {safe_schema(schema)}"))
            owned = True
            await connection.execute(
                text(f"REVOKE ALL ON SCHEMA {safe_schema(schema)} FROM PUBLIC")
            )
            await connection.commit()
            stage = "migration"
            await set_context(connection, schema)
            await clone_tables(connection, schema)
            await apply_migration(connection, schema)
            await connection.commit()
        stage = "service_transactions"
        from workbench_correction_dev_checks import verify_service

        async with asyncio.timeout(600):
            await verify_service(
                owner_engine,
                runtime_engine,
                schema,
                set_context,
                apply_migration,
                checks=checks,
            )
            validate_checks(checks)
    except Exception as exc:
        failure = sanitize_failure(exc)
        detail = failure_detail(exc)
    finally:
        try:
            if owned:
                cleanup_ok = await cleanup(owner_engine, schema)
            if before is not None:
                async with owner_engine.connect() as connection:
                    neutral = before == await public_snapshot(connection)
        except Exception as exc:
            readback_failure = sanitize_failure(exc)
        finally:
            await runtime_engine.dispose()
            await owner_engine.dispose()
    evidence = {
        "status": "PASS"
        if failure is None
        and readback_failure is None
        and cleanup_ok
        and neutral
        and checks
        else "BLOCKED",
        "scope": "workbench_correction_isolated_dev",
        "migration": "0176",
        "checks": checks,
        "cleanup": cleanup_ok,
        "public_schema_neutral": neutral,
        "failure": failure,
        "detail": detail,
        "readback_failure": readback_failure,
        "stage": stage,
        "model": "BOUNDARY_FAKE",
        "source_bytes": "SYNTHETIC",
        "neighbor_policies": "SYNTHETIC",
        "semantic_quality": "NOT_VERIFIED",
        "production": "UNCHANGED",
    }
    assert_sanitized_evidence(evidence)
    return evidence


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        output = args.evidence.resolve()
        target = (ROOT / ".release-evidence/WB-CORRECTION-PREVIEW-20261005").resolve()
        if output.parent != target or output.suffix != ".json" or output.exists():
            raise GateBlocked("invalid_evidence_target")
        if not args.execute:
            raise GateBlocked("execute_flag_required")
        config = canonical_config(args.env_file)
        load_dotenv(args.env_file, override=True)
        evidence = asyncio.run(
            run_gate(
                config["owner_url"],
                config["runtime_url"],
                config["supabase_url"],
                f"workbench_{uuid4().hex[:12]}",
            )
        )
        assert_sanitized_evidence(evidence)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(evidence, stream, ensure_ascii=True, sort_keys=True, indent=2)
        print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
        return 0 if evidence["status"] == "PASS" else 1
    except Exception as exc:
        print(
            json.dumps(
                {"status": "BLOCKED", "failure": sanitize_failure(exc)}, sort_keys=True
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
