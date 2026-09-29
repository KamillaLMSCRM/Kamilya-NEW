#!/usr/bin/env python3
"""Exercise migration 0167 in one disposable Supabase DEV schema."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from dotenv import dotenv_values
from kb_rag_isolated_dev_gate import normalize_database_url, same_supabase_project
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "apps" / "api" / "alembic" / "versions" / "0167_recurring_occurrence_deadline_history.py"
SCHEMA_RE = re.compile(r"^recurrence_completion_[0-9a-f]{12}$")


def _safe_schema(value: str) -> str:
    if not SCHEMA_RE.fullmatch(value):
        raise RuntimeError("unsafe_schema")
    return value


def _migration_module() -> Any:
    spec = importlib.util.spec_from_file_location("recurrence_completion_0167", MIGRATION)
    if spec is None or spec.loader is None:
        raise RuntimeError("migration_loader_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _run_migration(connection: AsyncConnection, schema: str, action: str) -> None:
    module = _migration_module()

    def run(sync_connection: Any) -> None:
        context = MigrationContext.configure(sync_connection, opts={"version_table_schema": schema})
        with Operations.context(context):
            getattr(module, action)()

    await connection.run_sync(run)


async def _public_revision(connection: AsyncConnection) -> str:
    if not await connection.scalar(text("SELECT to_regclass('public.alembic_version') IS NOT NULL")):
        return "absent"
    return str(await connection.scalar(text("SELECT version_num FROM public.alembic_version")) or "empty")


async def _expect_rejected(connection: AsyncConnection, statement: str, params: dict[str, Any]) -> None:
    savepoint = await connection.begin_nested()
    try:
        await connection.execute(text(statement), params)
    except Exception:
        await savepoint.rollback()
        return
    await savepoint.rollback()
    raise RuntimeError("expected_statement_to_be_rejected")


async def _expect_deferred_rejected(connection: AsyncConnection, statement: str, params: dict[str, Any]) -> None:
    savepoint = await connection.begin_nested()
    try:
        await connection.execute(text(statement), params)
        await connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    except Exception:
        await savepoint.rollback()
        return
    await savepoint.rollback()
    raise RuntimeError("expected_deferred_statement_to_be_rejected")


async def _execute_batch(
    connection: AsyncConnection,
    statements: str,
    params: dict[str, Any] | None = None,
) -> None:
    """Execute simple fixture DDL/DML one statement at a time for asyncpg."""
    for statement in statements.split(";"):
        if statement.strip():
            await connection.execute(text(statement), params or {})


async def _create_baseline(connection: AsyncConnection, schema: str) -> dict[str, uuid.UUID]:
    q = f'"{schema}"'
    ids = {name: uuid.uuid4() for name in (
        "tenant_a", "tenant_b", "methodologist_a", "methodologist_b", "learner_a",
        "course_a", "release_a", "rule_a", "occurrence_a", "enrollment_a", "reminder_a",
    )}
    now = datetime.now(UTC)
    await connection.execute(text(f"CREATE SCHEMA {q}"))
    await _execute_batch(connection, f"""
      CREATE TABLE {q}.tenants(id uuid PRIMARY KEY,name text NOT NULL,status text NOT NULL);
      CREATE TABLE {q}.users(
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL REFERENCES {q}.tenants(id),role text NOT NULL,
        is_active boolean NOT NULL,status text NOT NULL,email text,password_hash text,telegram_id bigint,
        email_verified_at timestamptz,first_name text,last_name text);
      CREATE TABLE {q}.courses(id uuid PRIMARY KEY,tenant_id uuid NOT NULL REFERENCES {q}.tenants(id),title text,status text);
      CREATE TABLE {q}.content_releases(id uuid PRIMARY KEY,tenant_id uuid NOT NULL,course_id uuid NOT NULL);
      CREATE TABLE {q}.learning_paths(id uuid PRIMARY KEY,tenant_id uuid NOT NULL REFERENCES {q}.tenants(id),title text,status text);
      CREATE TABLE {q}.recurring_learning_rules(
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL REFERENCES {q}.tenants(id),course_id uuid,
        learning_path_id uuid,user_id uuid NOT NULL,reminder_enabled boolean NOT NULL DEFAULT false,
        reminder_days_before_due integer NOT NULL DEFAULT 1,status text NOT NULL);
      CREATE TABLE {q}.recurring_learning_assignments(
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL REFERENCES {q}.tenants(id),rule_id uuid NOT NULL REFERENCES {q}.recurring_learning_rules(id),
        user_id uuid NOT NULL REFERENCES {q}.users(id),course_id uuid NOT NULL REFERENCES {q}.courses(id),enrollment_id uuid,
        scheduled_for timestamptz NOT NULL,due_at timestamptz NOT NULL,status text NOT NULL);
      CREATE TABLE {q}.learning_path_cycle_instances(
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL REFERENCES {q}.tenants(id),rule_id uuid NOT NULL REFERENCES {q}.recurring_learning_rules(id),
        path_id uuid NOT NULL REFERENCES {q}.learning_paths(id),user_id uuid NOT NULL REFERENCES {q}.users(id),sequence_no integer NOT NULL,
        scheduled_for timestamptz NOT NULL,starts_at timestamptz,due_at timestamptz,status text NOT NULL,created_at timestamptz DEFAULT now(),completed_at timestamptz);
      CREATE TABLE {q}.learning_path_assignments(
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,path_id uuid NOT NULL,user_id uuid NOT NULL,recurrence_instance_id uuid,
        source text,status text,completed_at timestamptz);
      CREATE TABLE {q}.enrollments(
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,user_id uuid NOT NULL,course_id uuid NOT NULL,
        recurring_assignment_id uuid,content_release_id uuid,status text,completed_at timestamptz);
      ALTER TABLE {q}.recurring_learning_assignments ADD CONSTRAINT fk_gate_enrollment FOREIGN KEY(enrollment_id) REFERENCES {q}.enrollments(id);
      CREATE TABLE {q}.learning_reminder_outbox(
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,rule_id uuid NOT NULL,course_occurrence_id uuid,path_cycle_instance_id uuid,
        policy_version integer NOT NULL DEFAULT 1,step text NOT NULL DEFAULT 'before_due',channel text NOT NULL DEFAULT 'email',
        scheduled_at timestamptz NOT NULL,due_at timestamptz NOT NULL,status text NOT NULL,attempt_count integer NOT NULL DEFAULT 0,
        first_attempt_at timestamptz,payload_hash text,delivery_transport text,next_attempt_at timestamptz NOT NULL,
        claim_token uuid,claimed_at timestamptz,send_reserved boolean NOT NULL DEFAULT false,delivered_at timestamptz,
        delivery_message_id text,last_error_category text,created_at timestamptz DEFAULT now(),updated_at timestamptz DEFAULT now());
      GRANT SELECT,INSERT,UPDATE,DELETE ON {q}.recurring_learning_assignments TO lms_app;
    """)
    await _execute_batch(connection, f"""
      INSERT INTO {q}.tenants VALUES (:ta,'A','active'),(:tb,'B','active');
      INSERT INTO {q}.users(id,tenant_id,role,is_active,status,email,password_hash,first_name,last_name) VALUES
        (:ma,:ta,'methodologist',true,'active','methodologist-a@example.invalid','x','M','A'),
        (:mb,:tb,'methodologist',true,'active','methodologist-b@example.invalid','x','M','B'),
        (:la,:ta,'student',true,'active','learner-a@example.invalid','x','L','A');
      INSERT INTO {q}.courses VALUES (:course,:ta,'Course A','published');
      INSERT INTO {q}.content_releases VALUES (:release,:ta,:course);
      INSERT INTO {q}.recurring_learning_rules VALUES (:rule,:ta,:course,NULL,:la,true,1,'active');
      INSERT INTO {q}.recurring_learning_assignments VALUES
        (:occ,:ta,:rule,:la,:course,NULL,:scheduled,:due,'assigned');
      INSERT INTO {q}.enrollments VALUES (:enrollment,:ta,:la,:course,:occ,:release,'enrolled',NULL);
      UPDATE {q}.recurring_learning_assignments SET enrollment_id=:enrollment WHERE id=:occ;
      INSERT INTO {q}.learning_reminder_outbox(
        id,tenant_id,rule_id,course_occurrence_id,scheduled_at,due_at,status,next_attempt_at)
      VALUES (:reminder,:ta,:rule,:occ,:reminder_at,:due,'queued',:reminder_at);
    """, {
        "ta": ids["tenant_a"], "tb": ids["tenant_b"], "ma": ids["methodologist_a"],
        "mb": ids["methodologist_b"], "la": ids["learner_a"], "course": ids["course_a"],
        "release": ids["release_a"], "rule": ids["rule_a"], "occ": ids["occurrence_a"],
        "enrollment": ids["enrollment_a"], "reminder": ids["reminder_a"],
        "scheduled": now, "due": now + timedelta(days=7), "reminder_at": now + timedelta(days=6),
    })
    await connection.commit()
    return ids


async def _cleanup(engine: Any, schema: str) -> bool:
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        async with engine.connect() as connection:
            return not bool(await connection.scalar(
                text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:schema)"), {"schema": schema}
            ))
    except Exception:
        return False


async def run(owner_url: str, runtime_url: str, supabase_url: str, schema: str) -> dict[str, Any]:
    _safe_schema(schema)
    if not same_supabase_project(owner_url, supabase_url) or not same_supabase_project(runtime_url, supabase_url):
        raise RuntimeError("database_project_mismatch")
    owner_engine = create_async_engine(owner_url, poolclass=NullPool)
    runtime_engine = create_async_engine(runtime_url, poolclass=NullPool)
    checks: list[str] = []
    cleanup_ok = False
    try:
        async with owner_engine.connect() as owner:
            public_before = await _public_revision(owner)
            ids = await _create_baseline(owner, schema)
            invalid_occurrence = uuid.uuid4()
            q = f'"{schema}"'
            await owner.execute(text(f"""
              INSERT INTO {q}.recurring_learning_assignments(
                id,tenant_id,rule_id,user_id,course_id,enrollment_id,scheduled_for,due_at,status)
              SELECT :id,tenant_id,rule_id,user_id,course_id,NULL,scheduled_for+interval '1 day',due_at+interval '1 day','assigned'
              FROM {q}.recurring_learning_assignments WHERE id=:source
            """), {"id": invalid_occurrence, "source": ids["occurrence_a"]})
            await owner.commit()
            savepoint = await owner.begin_nested()
            try:
                await _run_migration(owner, schema, "upgrade")
            except Exception:
                await savepoint.rollback()
            else:
                await savepoint.rollback()
                raise RuntimeError("malformed_legacy_occurrence_was_not_rejected")
            await owner.execute(text(f"DELETE FROM {q}.recurring_learning_assignments WHERE id=:id"), {"id": invalid_occurrence})
            await owner.commit()
            checks.append("malformed_legacy_anchor_rejected")
            await _run_migration(owner, schema, "upgrade")
            await owner.commit()
            columns = set((await owner.execute(text(
                "SELECT table_name,column_name FROM information_schema.columns WHERE table_schema=:schema "
                "AND ((table_name='recurring_learning_assignments' AND column_name IN ('sequence_no','content_release_id','effective_due_at')) "
                "OR (table_name='learning_path_cycle_instances' AND column_name='effective_due_at') "
                "OR table_name='learning_cycle_participant_events')"
            ), {"schema": schema})).all())
            if ("recurring_learning_assignments", "sequence_no") not in columns or (
                "learning_cycle_participant_events", "id"
            ) not in columns:
                raise RuntimeError("migration_columns_missing")
            checks.append("actual_0167_upgrade")

            q = f'"{schema}"'
            await owner.execute(text(f'GRANT USAGE ON SCHEMA {q} TO lms_app'))
            await owner.execute(text(
                f'GRANT SELECT ON {q}.recurring_learning_assignments,{q}.learning_path_cycle_instances,'
                f'{q}.users,{q}.enrollments,{q}.learning_reminder_outbox TO lms_app'
            ))
            await owner.execute(text(f'GRANT UPDATE(effective_due_at) ON {q}.recurring_learning_assignments TO lms_app'))
            await owner.commit()

        new_due = datetime.now(UTC) + timedelta(days=10)
        async with runtime_engine.connect() as runtime:
            identity = (await runtime.execute(text(
                "SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
            ))).one()
            if identity != ("lms_app", False, False):
                raise RuntimeError("runtime_role_not_lms_app_non_bypass")
            await runtime.execute(text("SELECT set_config('app.tenant_id',:tenant,true)"), {"tenant": str(ids["tenant_a"])})
            q = f'"{schema}"'
            previous = await runtime.scalar(text(f"SELECT effective_due_at FROM {q}.recurring_learning_assignments WHERE id=:id"), {"id": ids["occurrence_a"]})
            locked_id = await runtime.scalar(text(f"""
              SELECT a.id FROM {q}.recurring_learning_assignments a
              LEFT JOIN {q}.enrollments e ON e.id=a.enrollment_id
              WHERE a.id=:id FOR UPDATE OF a
            """), {"id": ids["occurrence_a"]})
            if locked_id != ids["occurrence_a"]:
                raise RuntimeError("course_occurrence_lock_failed")
            await runtime.execute(text(f"UPDATE {q}.recurring_learning_assignments SET effective_due_at=:due WHERE id=:id"), {"due": new_due, "id": ids["occurrence_a"]})
            await runtime.execute(text(f"""
              INSERT INTO {q}.learning_cycle_participant_events(
                tenant_id,course_occurrence_id,user_id,previous_effective_due_at,effective_due_at,reason,actor_id)
              VALUES (:tenant,:occ,:learner,:previous,:due,:reason,:actor)
            """), {
                "tenant": ids["tenant_a"], "occ": ids["occurrence_a"], "learner": ids["learner_a"],
                "previous": previous, "due": new_due,
                "reason": "Verified participant schedule requires a deadline extension",
                "actor": ids["methodologist_a"],
            })
            await runtime.execute(text(f"SELECT {q}.reschedule_learning_reminder(:tenant,:occ,NULL,:due)"), {
                "tenant": ids["tenant_a"], "occ": ids["occurrence_a"], "due": new_due,
            })
            reminder_due = await runtime.scalar(text(f"SELECT due_at FROM {q}.learning_reminder_outbox WHERE id=:id"), {"id": ids["reminder_a"]})
            if reminder_due != new_due:
                raise RuntimeError("queued_reminder_not_rescheduled")
            await _expect_rejected(runtime, f"UPDATE {q}.learning_cycle_participant_events SET reason=:reason", {"reason": "A forbidden event rewrite with enough characters"})
            await _expect_rejected(runtime, f"UPDATE {q}.recurring_learning_assignments SET due_at=:due WHERE id=:id", {"due": new_due, "id": ids["occurrence_a"]})
            await _expect_deferred_rejected(runtime, f"UPDATE {q}.recurring_learning_assignments SET enrollment_id=NULL WHERE id=:id", {"id": ids["occurrence_a"]})
            await _expect_rejected(runtime, f"DELETE FROM {q}.recurring_learning_assignments WHERE id=:id", {"id": ids["occurrence_a"]})
            await runtime.commit()
            checks.extend(("course_occurrence_lock", "runtime_append_only_event", "immutable_original_occurrence", "immutable_enrollment_anchor", "runtime_occurrence_delete_revoked", "queued_reminder_rescheduled"))

        attempted_due = new_due
        later_due = new_due + timedelta(days=2)
        async with owner_engine.connect() as owner:
            q = f'"{schema}"'
            await owner.execute(text(f"""
              UPDATE {q}.learning_reminder_outbox SET status='failed',attempt_count=1,
                first_attempt_at=clock_timestamp(),payload_hash=:payload_hash,delivery_transport='smtp',
                send_reserved=true,last_error_category='delivery_uncertain'
              WHERE id=:id
            """), {"id": ids["reminder_a"], "payload_hash": "f" * 64})
            await owner.execute(text(f"UPDATE {q}.recurring_learning_assignments SET effective_due_at=:due WHERE id=:id"), {"due": later_due, "id": ids["occurrence_a"]})
            await owner.commit()

        async with runtime_engine.connect() as runtime:
            await runtime.execute(text("SELECT set_config('app.tenant_id',:tenant,true)"), {"tenant": str(ids["tenant_a"])})
            q = f'"{schema}"'
            rescheduled = await runtime.scalar(text(f"SELECT {q}.reschedule_learning_reminder(:tenant,:occ,NULL,:due)"), {
                "tenant": ids["tenant_a"], "occ": ids["occurrence_a"], "due": later_due,
            })
            preserved = (await runtime.execute(text(f"""
              SELECT status,due_at,last_error_category,attempt_count FROM {q}.learning_reminder_outbox WHERE id=:id
            """), {"id": ids["reminder_a"]})).one()
            if rescheduled is not False or preserved != ("failed", attempted_due, "delivery_uncertain", 1):
                raise RuntimeError("attempted_or_uncertain_reminder_was_rewritten")
            await runtime.rollback()
            checks.append("attempted_reminder_preserved")

        async with runtime_engine.connect() as runtime:
            await runtime.execute(text("SELECT set_config('app.tenant_id',:tenant,true)"), {"tenant": str(ids["tenant_b"])})
            q = f'"{schema}"'
            visible = await runtime.scalar(text(f"SELECT count(*) FROM {q}.learning_cycle_participant_events"))
            if visible != 0:
                raise RuntimeError("cross_tenant_event_visible")
            await runtime.rollback()
            checks.append("cross_tenant_rls")

        async with owner_engine.connect() as owner:
            try:
                await _run_migration(owner, schema, "downgrade")
            except Exception:
                await owner.rollback()
            else:
                raise RuntimeError("lossy_downgrade_was_not_refused")
            q = f'"{schema}"'
            await owner.execute(text(f"DELETE FROM {q}.learning_cycle_participant_events"))
            await owner.commit()
            await _run_migration(owner, schema, "downgrade")
            await owner.commit()
            projected_due = await owner.scalar(text(
                f"SELECT due_at FROM {q}._learning_reminder_targets(:tenant,:occ,NULL)"
            ), {"tenant": ids["tenant_a"], "occ": ids["occurrence_a"]})
            original_due = await owner.scalar(text(
                f"SELECT due_at FROM {q}.recurring_learning_assignments WHERE id=:occ"
            ), {"occ": ids["occurrence_a"]})
            if projected_due != original_due:
                raise RuntimeError("downgrade_reminder_projection_not_restored")
            delete_restored = await owner.scalar(text(
                "SELECT has_table_privilege('lms_app',:table_name,'DELETE')"
            ), {"table_name": f"{schema}.recurring_learning_assignments"})
            if delete_restored is not True:
                raise RuntimeError("downgrade_delete_privilege_not_restored")
            checks.append("guarded_downgrade")
            checks.append("downgrade_reminder_projection_restored")
            if await _public_revision(owner) != public_before:
                raise RuntimeError("public_revision_changed")
            checks.append("public_schema_unchanged")
    finally:
        cleanup_ok = await _cleanup(owner_engine, schema)
        await runtime_engine.dispose()
        await owner_engine.dispose()
    if not cleanup_ok:
        raise RuntimeError("isolated_schema_cleanup_failed")
    checks.append("isolated_schema_removed")
    return {"status": "PASS", "target": "isolated_supabase_dev_schema", "schema": schema, "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("Use --execute for the owner-authorized isolated Supabase DEV gate")
    values = {key: value or "" for key, value in dotenv_values(args.env_file).items()}
    owner_url = normalize_database_url(values.get("MIGRATION_DATABASE_URL", ""))
    runtime_url = normalize_database_url(values.get("DATABASE_URL", ""))
    supabase_url = values.get("SUPABASE_URL", "")
    if not owner_url or not runtime_url or not supabase_url:
        raise SystemExit("MIGRATION_DATABASE_URL, DATABASE_URL and SUPABASE_URL are required")
    if make_url(owner_url).host in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit("Local PostgreSQL is forbidden")
    schema = f"recurrence_completion_{uuid.uuid4().hex[:12]}"
    print(json.dumps(asyncio.run(run(owner_url, runtime_url, supabase_url, schema)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
