#!/usr/bin/env python3
"""Owned DEV application proof with catalog-bound immediate FKs, never public writes."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "apps/api", ROOT / "scripts/ops"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import event, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from workbench_correction_dev_gate import (  # noqa: E402
    CLONE_TABLES,
    apply_migration,
    clone_tables,
)
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

EXTRA_TABLES = (
    "course_approval_requests",
    "workflow_work_items",
    "workflow_access_credentials",
    "audit_logs",
    "content_releases",
)
TABLES = CLONE_TABLES + EXTRA_TABLES
HISTORY_TABLES = ("enrollments", "quiz_attempts", "certificates")
HISTORY_FKS = frozenset({
    ("courses", "content_releases"), ("enrollments", "content_releases"),
    ("enrollments", "enrollments"), ("enrollments", "users"),
    ("quiz_attempts", "quizzes"), ("quiz_attempts", "enrollments"),
    ("quiz_attempts", "content_releases"), ("certificates", "courses"),
    ("certificates", "enrollments"),
})
MIGRATION = (
    ROOT / "apps/api/alembic/versions/0177_workbench_lesson_correction_applications.py"
)
REQUIRED_FKS = frozenset(
    {
        ("modules", "courses"),
        ("lessons", "modules"),
        ("content_blocks", "lessons"),
        ("quizzes", "lessons"),
        ("questions", "quizzes"),
        ("quiz_choices", "questions"),
        ("scorm_packages", "courses"),
        ("course_approval_policies", "courses"),
        ("course_approval_revisions", "courses"),
        ("course_approval_requests", "course_approval_revisions"),
        ("workflow_work_items", "course_approval_revisions"),
        ("workflow_access_credentials", "workflow_work_items"),
    }
)

REQUIRED_CHECKS = frozenset(
    {
        "bounded_connection_peak",
        "catalog_fk_exact_immediate",
        "apply_read_review_invalidation",
        "same_plan_concurrent_once",
        "busy_plan_rollback",
        "replay_after_later_edit",
        "wrong_seal_refused",
        "stale_refused",
        "published_refused",
        "sibling_refused",
        "foreign_refused",
        "revoked_refused",
        "absent_context_refused",
        "receipt_sql_guard",
        "receipt_acl_immutable",
        "audit_fault_atomic_rollback",
        "receipt_fault_atomic_rollback",
        "lost_commit_ack_recovery",
        "direct_writer_contention",
        "approval_cancel_contention",
        "populated_downgrade_refused",
        "empty_downgrade_reupgrade",
        "fk_insert_move_contention",
        "fk_probe_fixture_preflight",
    }
)


def validate_checks(checks):
    if set(checks) != REQUIRED_CHECKS or len(checks) != len(set(checks)):
        raise GateBlocked("required_checks_missing")


def rebind_fk(definition: str, target: str, schema: str) -> str:
    qualified = safe_schema(schema)
    if not re.fullmatch(r"[a-z_]+", target) or any(
        token in definition for token in (";", "--", "/*", "\n")
    ):
        raise GateBlocked("unsafe_foreign_key_definition")
    pattern = rf"\bREFERENCES (?:public\.)?{re.escape(target)}(?=\()"
    matches = list(re.finditer(pattern, definition))
    if len(matches) != 1 or not definition.startswith("FOREIGN KEY ("):
        raise GateBlocked("foreign_key_target_mismatch")
    return re.sub(pattern, f"REFERENCES {qualified}.{target}", definition, count=1)


def failure_detail(exc):
    detail = {}
    cause = exc
    for _ in range(3):
        code = getattr(getattr(cause, "orig", None), "sqlstate", None)
        if isinstance(code, str) and re.fullmatch(r"[A-Z0-9]{5}", code):
            detail["state"] = code
            break
        cause = getattr(cause, "__cause__", None) or getattr(cause, "__context__", None)
        if cause is None:
            break
    allowed = {
        Path(__file__).resolve(),
        ROOT / "scripts/ops/workbench_correction_application_dev_checks.py",
        ROOT / "scripts/ops/workbench_correction_lifecycle_dev_checks.py",
        ROOT / "scripts/ops/workbench_correction_lifecycle_dev_gate.py",
        ROOT / "scripts/ops/workbench_correction_history_dev_checks.py",
        ROOT / "scripts/ops/workbench_correction_history_dev_gate.py",
        ROOT / "apps/api/alembic/versions/0178_workbench_lesson_correction_lifecycle.py",
        MIGRATION,
        ROOT / "apps/api/app/modules/methodologist_workbench/correction_application.py",
        ROOT / "apps/api/app/modules/methodologist_workbench/correction_service.py",
    }
    frame = exc.__traceback__
    while frame:
        path = Path(frame.tb_frame.f_code.co_filename).resolve()
        if path in allowed:
            detail.update(file=path.relative_to(ROOT).as_posix(), line=frame.tb_lineno)
        frame = frame.tb_next
    outcomes = getattr(exc, "gate_outcomes", None)
    if isinstance(outcomes, list) and len(outcomes) == 2:
        safe = []
        for outcome in outcomes:
            if not isinstance(outcome, dict) or outcome.get("status") not in {
                "COMPLETED",
                "FAILED",
            }:
                break
            item = {"status": outcome["status"]}
            for key, pattern in (("class", r"[A-Za-z]+"), ("state", r"[A-Z0-9]{5}")):
                value = outcome.get(key)
                if isinstance(value, str) and re.fullmatch(pattern, value):
                    item[key] = value
            safe.append(item)
        if len(safe) == 2:
            detail["concurrent"] = safe
    return detail


async def clone_application_tables(connection, schema, *, learner_history=False):
    if type(learner_history) is not bool:
        raise GateBlocked("learner_history_scope_invalid")
    extra_tables = EXTRA_TABLES + (HISTORY_TABLES if learner_history else ())
    tables = CLONE_TABLES + extra_tables
    qualified = safe_schema(schema)
    if await connection.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_attrdef a JOIN pg_class t ON t.oid=a.adrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='public' AND t.relname=ANY(:tables) AND pg_get_expr(a.adbin,a.adrelid) ILIKE '%nextval(%')"
        ),
        {"tables": list(extra_tables)},
    ):
        raise GateBlocked("sequence_dependent_clone_default")
    await clone_tables(connection, schema)
    for table in extra_tables:
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
        await connection.execute(
            text(f"ALTER TABLE {qualified}.{table} ENABLE ROW LEVEL SECURITY")
        )
        await connection.execute(
            text(f"ALTER TABLE {qualified}.{table} FORCE ROW LEVEL SECURITY")
        )
        tenant = "tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid"
        await connection.execute(
            text(
                f"CREATE POLICY gate_{table}_tenant ON {qualified}.{table} FOR ALL TO lms_app USING ({tenant}) WITH CHECK ({tenant})"
            )
        )
    rows = (
        await connection.execute(
            text("""SELECT src.relname, dst.relname, c.conname,
        pg_get_constraintdef(c.oid,false), c.condeferrable, c.convalidated
        FROM pg_constraint c JOIN pg_class src ON src.oid=c.conrelid
        JOIN pg_namespace ns ON ns.oid=src.relnamespace
        JOIN pg_class dst ON dst.oid=c.confrelid JOIN pg_namespace nd ON nd.oid=dst.relnamespace
        WHERE c.contype='f' AND ns.nspname='public' AND nd.nspname='public'
        AND src.relname=ANY(:tables) AND dst.relname=ANY(:tables)
        ORDER BY src.relname,c.conname"""),
            {"tables": list(tables)},
        )
    ).all()
    found = set()
    for source, target, name, definition, deferred, validated in rows:
        if (
            source not in tables
            or target not in tables
            or not re.fullmatch(r"[a-z_][a-z0-9_]*", name)
        ):
            raise GateBlocked("unsafe_catalog_foreign_key")
        if deferred or not validated:
            raise GateBlocked("non_immediate_foreign_key")
        rewritten = rebind_fk(definition, target, schema)
        await connection.execute(
            text(
                f'ALTER TABLE {qualified}.{source} ADD CONSTRAINT "{name}" {rewritten}'
            )
        )
        actual = await connection.scalar(
            text("""SELECT pg_get_constraintdef(c.oid,false)
            FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid
            JOIN pg_namespace n ON n.oid=t.relnamespace
            WHERE n.nspname=:s AND t.relname=:t AND c.conname=:c"""),
            {"s": schema, "t": source, "c": name},
        )
        # Owned schema is first in search_path, so PostgreSQL omits its qualifier.
        if actual != rewritten.replace(f"{qualified}.", ""):
            raise GateBlocked("foreign_key_definition_drift")
        found.add((source, target))
    required_fks = REQUIRED_FKS | (HISTORY_FKS if learner_history else frozenset())
    if not required_fks <= found:
        raise GateBlocked("required_foreign_key_missing")


async def apply_0177(connection, schema, operation="upgrade"):
    safe_schema(schema)
    if operation not in {"upgrade", "downgrade"}:
        raise GateBlocked("invalid_migration_request")
    spec = importlib.util.spec_from_file_location(
        "correction_application_0177", MIGRATION
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.revision != "0177" or module.down_revision != "0176":
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
    owner_url, runtime_url, supabase_url, schema, *,
    extra_migration=None, verifier=None, required_checks=REQUIRED_CHECKS,
    scope="workbench_correction_application_isolated_dev", migration="0177",
    learner_history=False,
):
    started = monotonic()
    safe_schema(schema)
    history_checks = {"learner_history_fixture", "learner_history_apply", "learner_history_replay", "learner_history_refusal"}
    if type(learner_history) is not bool or (
        learner_history and not history_checks <= required_checks
    ):
        raise GateBlocked("learner_history_scope_invalid")
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
    owner_engine, runtime_engine = (
        create_async_engine(url, **options) for url in (owner_url, runtime_url)
    )
    active_connections = set()
    connection_peak = 0

    def checked_out(connection, *_):
        nonlocal connection_peak
        active_connections.add(id(connection))
        connection_peak = max(connection_peak, len(active_connections))
        if connection_peak > 3:
            raise GateBlocked("connection_cap_exceeded")

    def checked_in(connection, *_):
        active_connections.discard(id(connection))

    for engine in (owner_engine, runtime_engine):
        event.listen(engine.sync_engine, "checkout", checked_out)
        event.listen(engine.sync_engine, "checkin", checked_in)

    @event.listens_for(runtime_engine.sync_engine, "begin")
    def owned_transaction(connection):
        connection.exec_driver_sql(
            f"SET LOCAL search_path TO {safe_schema(schema)}, pg_catalog"
        )

    owned, cleaned, neutral = False, False, False
    before, failure, readback_failure, checks, stage = None, None, None, [], "identity"
    detail = {}
    try:
        async with runtime_engine.connect() as connection:
            await verify_runtime_role(connection)
        async with owner_engine.connect() as connection:
            before = await public_snapshot(connection)
            if await connection.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:s)"),
                {"s": schema},
            ):
                raise GateBlocked("schema_collision")
            await connection.execute(text(f"CREATE SCHEMA {safe_schema(schema)}"))
            owned = True
            await connection.execute(
                text(f"REVOKE ALL ON SCHEMA {safe_schema(schema)} FROM PUBLIC")
            )
            await connection.commit()
            stage = "catalog_migration"
            await set_context(connection, schema)
            if learner_history:
                await clone_application_tables(connection, schema, learner_history=True)
            else:
                await clone_application_tables(connection, schema)
            checks.append("catalog_fk_exact_immediate")
            await apply_migration(connection, schema)
            await apply_0177(connection, schema)
            if extra_migration is not None:
                await extra_migration(connection, schema)
            await connection.commit()
        stage = "application_transactions"
        from workbench_correction_application_dev_checks import verify_application

        async with asyncio.timeout(600):
            await (verifier or verify_application)(owner_engine, runtime_engine, schema, checks)
        if connection_peak > 3:
            raise GateBlocked("connection_cap_exceeded")
        checks.append("bounded_connection_peak")
        if set(checks) != required_checks or len(checks) != len(set(checks)):
            raise GateBlocked("required_checks_missing")
    except Exception as exc:
        failure = sanitize_failure(exc)
        detail = failure_detail(exc)
    finally:
        try:
            if owned:
                cleaned = await cleanup(owner_engine, schema)
            if before is not None:
                async with owner_engine.connect() as connection:
                    neutral = before == await public_snapshot(connection)
        except Exception as exc:
            readback_failure = sanitize_failure(exc)
        finally:
            await runtime_engine.dispose()
            await owner_engine.dispose()
    result = {
        "status": "PASS"
        if failure is None
        and readback_failure is None
        and cleaned
        and neutral
        and set(checks) == required_checks
        else "BLOCKED",
        "scope": scope,
        "migration": migration,
        "checks": checks,
        "cleanup": cleaned,
        "public_schema_neutral": neutral,
        "failure": failure,
        "detail": detail,
        "readback_failure": readback_failure,
        "stage": stage,
        "connection_peak": connection_peak,
        "elapsed_seconds": round(monotonic() - started, 3),
        "source_bytes": "SYNTHETIC",
        "model": "BOUNDARY_FAKE",
        "neighbor_policies": "SYNTHETIC",
        "learner_history": "VERIFIED" if learner_history and failure is None
        and readback_failure is None and cleaned and neutral
        and set(checks) == required_checks else "NOT_VERIFIED",
        "semantic_quality": "NOT_VERIFIED",
        "production": "UNCHANGED",
    }
    assert_sanitized_evidence(result)
    return result


def main():
    from uuid import uuid4

    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    try:
        common = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if args.env_file.resolve() != (Path(common).parent / ".env").resolve():
            raise GateBlocked("noncanonical_env_file")
        target = (ROOT / ".release-evidence/WB-CORRECTION-APPLY-20261005").resolve()
        output = args.evidence.resolve()
        if output.parent != target or output.suffix != ".json" or output.exists():
            raise GateBlocked("invalid_evidence_target")
        config = canonical_config(args.env_file)
        load_dotenv(args.env_file, override=True)
        result = asyncio.run(
            run_gate(
                config["owner_url"],
                config["runtime_url"],
                config["supabase_url"],
                f"workbench_{uuid4().hex[:12]}",
            )
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    except Exception as exc:
        print(
            json.dumps(
                {"status": "BLOCKED", "failure": sanitize_failure(exc)}, sort_keys=True
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
