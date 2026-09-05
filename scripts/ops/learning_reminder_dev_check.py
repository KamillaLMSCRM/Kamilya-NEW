"""R2a isolated-schema SQL contracts on canonical Supabase DEV; no email sends.

This runs the actual migration SQL against minimal dependency fixtures, not a
shared-public migration or a full application/database-clone acceptance.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import sys
import traceback
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values
from kb_rag_isolated_dev_gate import normalize_database_url, same_supabase_project
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parents[2]
TABLES = {
    "tenants": "id uuid PRIMARY KEY,name text,slug text,status text",
    "users": "id uuid PRIMARY KEY,tenant_id uuid,email text,first_name text,last_name text,role text,is_active boolean,status text,password_hash text,telegram_id bigint,email_verified_at timestamptz",
    "courses": "id uuid PRIMARY KEY,tenant_id uuid,title text,status text",
    "recurring_learning_rules": "id uuid PRIMARY KEY,tenant_id uuid,course_id uuid,learning_path_id uuid,user_id uuid,status text",
    "enrollments": "id uuid PRIMARY KEY,tenant_id uuid,course_id uuid,user_id uuid,recurring_assignment_id uuid,status text,completed_at timestamptz",
    "recurring_learning_assignments": "id uuid PRIMARY KEY,tenant_id uuid,rule_id uuid,user_id uuid,course_id uuid,enrollment_id uuid,due_at timestamptz,status text",
    "learning_paths": "id uuid PRIMARY KEY,tenant_id uuid,title text,status text",
    "learning_path_cycle_instances": "id uuid PRIMARY KEY,tenant_id uuid,rule_id uuid,path_id uuid,user_id uuid,due_at timestamptz,status text,completed_at timestamptz",
    "learning_path_assignments": "id uuid PRIMARY KEY,tenant_id uuid,path_id uuid,user_id uuid,recurrence_instance_id uuid,status text,completed_at timestamptz,source text",
}


class SqlCollector:
    def __init__(self, schema: str):
        self.opts = {"version_table_schema": schema}
        self.statements: list[str] = []

    def get_context(self):
        return self

    def execute(self, statement):
        self.statements.append(str(statement))


async def run() -> int:
    if "--execute" not in sys.argv:
        print(
            "R2a DEV gate: --execute creates one isolated synthetic schema, tests actual SQL functions, then drops only that schema. No provider activity."
        )
        return 0
    values = dotenv_values(ROOT / ".env")
    urls = {name: normalize_database_url(values.get(name) or "") for name in ("MIGRATION_DATABASE_URL", "DATABASE_URL")}
    if not all(
        same_supabase_project(url, values.get("SUPABASE_URL") or "") and make_url(url).database == "postgres"
        for url in urls.values()
    ):
        print('{"status":"BLOCKED","reason":"canonical_dev_identity"}')
        return 2
    if (make_url(urls["DATABASE_URL"]).username or "").split(".")[0] != "lms_app":
        print('{"status":"BLOCKED","reason":"runtime_role_identity"}')
        return 2
    schema = "r2_reminder_" + uuid4().hex
    application = "--application" in sys.argv
    assert re.fullmatch(r"r2_reminder_[0-9a-f]{32}", schema)
    engines = {
        k: create_async_engine(
            v, pool_size=2, max_overflow=0, hide_parameters=True, connect_args={"timeout": 12, "command_timeout": 20}
        )
        for k, v in urls.items()
    }
    admin = engines["MIGRATION_DATABASE_URL"]
    app = engines["DATABASE_URL"]
    made = False
    checks: list[str] = []
    stage = "preflight"
    code = 1

    async def execute(sql: str, params=None):
        async with admin.begin() as db:
            return await db.execute(text(sql), params or {})

    async def runtime(tenant, sql: str, params=None, *, superadmin=False):
        async with app.begin() as db:
            await db.execute(text("SELECT set_config('app.tenant_id',:tid,true)"), {"tid": str(tenant)})
            await db.execute(
                text("SELECT set_config('app.is_superadmin',:flag,true)"), {"flag": "true" if superadmin else "false"}
            )
            return await db.execute(text(sql), params or {})

    async def call(tenant, name, args, *, superadmin=False):
        placeholders = ",".join(f":p{i}" for i in range(len(args)))
        return await runtime(
            tenant,
            f'SELECT * FROM "{schema}".{name}({placeholders})',
            {f"p{i}": arg for i, arg in enumerate(args)},
            superadmin=superadmin,
        )

    async def denied(operation):
        try:
            await operation
        except Exception as exc:
            # Do not accept a broken query or transport as an authorization result.
            original = getattr(exc, "orig", exc)
            sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
            assert sqlstate in {"42501", "P0001"}, type(exc).__name__
        else:
            raise AssertionError("authorization_should_deny")

    try:
        actual = (
            await runtime(uuid4(), "SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
        ).one()
        assert tuple(actual) == ("lms_app", False, False)
        assert (await execute("SELECT version_num FROM public.alembic_version")).scalars().all() == ["0151"]
        assert (await execute("SELECT count(*) FROM pg_roles WHERE rolname='lms_recovery'")).scalar() == 1
        stage = "isolated_migration"
        print(json.dumps({"stage": stage, "mode": "application" if application else "SQL_contracts"}), flush=True)
        await execute(f'CREATE SCHEMA "{schema}"')
        made = True
        if application:
            # Schema only: never copy tenant data or shared sequence defaults.
            for table in (*TABLES, "content_releases"):
                sequence_defaults = await execute(
                    "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' "
                    "AND table_name=:table AND column_default LIKE '%nextval(%'",
                    {"table": table},
                )
                assert sequence_defaults.scalar() == 0, "shared_sequence_default_forbidden"
                await execute(f'CREATE TABLE "{schema}".{table} (LIKE public.{table} INCLUDING ALL)')
        else:
            for table, columns in TABLES.items():
                await execute(f'CREATE TABLE "{schema}".{table} ({columns})')
        spec = importlib.util.spec_from_file_location(
            "reminder_migration", ROOT / "apps/api/alembic/versions/0152_learning_reminders.py"
        )
        assert spec and spec.loader
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        def downgrade_sync(connection):
            migration.op = Operations(MigrationContext.configure(connection, opts={"version_table_schema": schema}))
            migration.downgrade()

        collector = SqlCollector(schema)
        migration.op = collector
        migration.upgrade()
        async with admin.begin() as db:
            for statement in collector.statements:
                assert "public." not in statement and "__KML_SCHEMA__" not in statement
                await db.execute(text(statement))
        await execute(f'GRANT USAGE ON SCHEMA "{schema}" TO lms_app')
        checks.append("actual_migration_sql_in_isolated_schema")
        if application:
            from learning_reminder_application_check import check_application

            stage = "assembled_application"
            print(json.dumps({"stage": stage}), flush=True)
            checks.extend(await check_application(admin, app, schema))
            print(
                json.dumps(
                    {
                        "status": "PASS",
                        "scope": "schema_only_clone_application_seams",
                        "checks": checks,
                        "provider_calls": 0,
                        "shared_public_writes": 0,
                    }
                )
            )
            code = 0
            return code
        tenant, other, learner, course, rule, occurrence, enrollment = [uuid4() for _ in range(7)]
        ids = {"t": tenant, "u": learner, "c": course, "r": rule, "o": occurrence, "e": enrollment}
        for tid, slug in ((tenant, "r2-synthetic"), (other, "r2-other")):
            await execute(
                f"INSERT INTO \"{schema}\".tenants VALUES (:t,'Synthetic tenant',:slug,'active')",
                {"t": tid, "slug": slug},
            )
        await execute(
            f"INSERT INTO \"{schema}\".users VALUES (:u,:t,'learner@example.com','Synthetic','Learner','student',true,'active',NULL,NULL,now())",
            ids,
        )
        await execute(f"INSERT INTO \"{schema}\".courses VALUES (:c,:t,'Synthetic training','published')", ids)
        await execute(
            f"INSERT INTO \"{schema}\".recurring_learning_rules (id,tenant_id,course_id,user_id,status) VALUES (:r,:t,:c,:u,'active')",
            ids,
        )
        await execute(f"INSERT INTO \"{schema}\".enrollments VALUES (:e,:t,:c,:u,:o,'enrolled',NULL)", ids)
        await execute(
            f"INSERT INTO \"{schema}\".recurring_learning_assignments VALUES (:o,:t,:r,:u,:c,:e,now()+interval '12 hours','assigned')",
            ids,
        )
        stage = "default_disabled_and_dedup"
        assert (await call(tenant, "enqueue_learning_reminder", [tenant, occurrence, None])).scalar() is None
        await execute(f'UPDATE "{schema}".recurring_learning_rules SET reminder_enabled=true WHERE id=:r', ids)
        reminder = (await call(tenant, "enqueue_learning_reminder", [tenant, occurrence, None])).scalar()
        assert reminder
        assert (await call(tenant, "enqueue_learning_reminder", [tenant, occurrence, None])).scalar() == reminder
        await execute(f'UPDATE "{schema}".recurring_learning_rules SET reminder_days_before_due=5 WHERE id=:r', ids)
        assert (await call(tenant, "enqueue_learning_reminder", [tenant, occurrence, None])).scalar() == reminder
        assert (
            await execute(
                f'SELECT due_at-scheduled_at FROM "{schema}".learning_reminder_outbox WHERE id=:id', {"id": reminder}
            )
        ).scalar().days == 1
        checks.extend(["default_disabled", "dedup_and_frozen_schedule"])
        stage = "claim_concurrency"
        claims = await asyncio.gather(*[call(tenant, "claim_learning_reminder", [tenant, reminder]) for _ in range(2)])
        rows = [row for result in claims for row in result.mappings().all()]
        assert len(rows) == 1
        token = rows[0]["claim_token"]
        assert (await call(tenant, "learning_reminder_payload", [tenant, reminder, token])).mappings().one()[
            "target_type"
        ] == "course"
        checks.append("concurrent_claim_single_winner")
        stage = "tenant_role_guards"
        await denied(call(other, "claim_learning_reminder", [tenant, reminder]))
        await denied(call(other, "enqueue_learning_reminder", [tenant, occurrence, None]))
        assert (await call(other, "enqueue_learning_reminder", [other, occurrence, None])).scalar() is None
        assert (await call(other, "learning_reminder_payload", [other, reminder, token])).all() == []
        assert (await call(other, "learning_reminder_statuses", [other, rule])).all() == []
        assert (
            await call(other, "finalize_learning_reminder", [other, reminder, token, "success", "synthetic", None])
        ).scalar() is False
        await denied(runtime(tenant, f'SELECT * FROM "{schema}".learning_reminder_outbox'))
        await denied(call(tenant, "due_learning_reminders", [20]))
        assert (
            await execute(
                "SELECT has_function_privilege('lms_recovery',:signature,'EXECUTE')",
                {"signature": f'"{schema}".due_learning_reminders(integer)'},
            )
        ).scalar()
        assert not (
            await execute(
                "SELECT has_function_privilege('lms_recovery',:signature,'EXECUTE')",
                {"signature": f'"{schema}".claim_learning_reminder(uuid,uuid)'},
            )
        ).scalar()
        checks.append("actual_lms_app_no_bypass_tenant_and_direct_acl_denial")
        stage = "defer_and_retry"
        assert (
            await call(
                tenant, "finalize_learning_reminder", [tenant, reminder, token, "defer", None, "configuration_missing"]
            )
        ).scalar()
        assert (await call(tenant, "learning_reminder_statuses", [tenant, rule])).mappings().one()["attempt_count"] == 0

        async def reclaim():
            await execute(
                f"UPDATE \"{schema}\".learning_reminder_outbox SET next_attempt_at=now()-interval '1 second' WHERE id=:id",
                {"id": reminder},
            )
            return (await call(tenant, "claim_learning_reminder", [tenant, reminder])).mappings().one()["claim_token"]

        token = await reclaim()
        assert (await call(tenant, "begin_learning_reminder_send", [tenant, reminder, token, "a" * 64])).scalar()
        assert not (await call(tenant, "begin_learning_reminder_send", [tenant, reminder, token, "a" * 64])).scalar()
        assert (
            await call(
                tenant, "finalize_learning_reminder", [tenant, reminder, token, "transient", None, "provider_timeout"]
            )
        ).scalar()
        token = await reclaim()
        assert not (await call(tenant, "begin_learning_reminder_send", [tenant, reminder, token, "b" * 64])).scalar()
        assert (await call(tenant, "learning_reminder_statuses", [tenant, rule])).mappings().one()[
            "last_error_category"
        ] == "payload_changed"
        checks.extend(
            ["configuration_defer_without_attempt", "one_send_reservation_per_claim", "retry_payload_change_terminal"]
        )
        stage = "completion_and_skip_suppression"
        await execute(
            f"UPDATE \"{schema}\".learning_reminder_outbox SET status='queued',next_attempt_at=now() WHERE id=:id",
            {"id": reminder},
        )
        token = await reclaim()
        await execute(f"UPDATE \"{schema}\".enrollments SET status='completed' WHERE id=:e", ids)
        assert (await call(tenant, "learning_reminder_payload", [tenant, reminder, token])).all() == []
        assert not (await call(tenant, "begin_learning_reminder_send", [tenant, reminder, token, "a" * 64])).scalar()
        assert (await call(tenant, "learning_reminder_statuses", [tenant, rule])).mappings().one()[
            "status"
        ] == "skipped"
        checks.append("completion_without_timestamp_suppresses_send")
        stage = "retry_horizon_and_recovery"

        async def new_course_reminder():
            oid, eid = uuid4(), uuid4()
            params = dict(ids, o=oid, e=eid)
            await execute(f"INSERT INTO \"{schema}\".enrollments VALUES (:e,:t,:c,:u,:o,'enrolled',NULL)", params)
            await execute(
                f"INSERT INTO \"{schema}\".recurring_learning_assignments VALUES (:o,:t,:r,:u,:c,:e,now()+interval '12 hours','assigned')",
                params,
            )
            return (await call(tenant, "enqueue_learning_reminder", [tenant, oid, None])).scalar()

        stale_id = await new_course_reminder()
        stale_token = (
            (await call(tenant, "claim_learning_reminder", [tenant, stale_id])).mappings().one()["claim_token"]
        )
        assert not (
            await call(
                tenant, "finalize_learning_reminder", [tenant, stale_id, stale_token, "success", "synthetic", None]
            )
        ).scalar()
        assert (await call(tenant, "begin_learning_reminder_send", [tenant, stale_id, stale_token, "a" * 64])).scalar()
        assert not (
            await call(tenant, "finalize_learning_reminder", [tenant, stale_id, stale_token, "success", "", None])
        ).scalar()
        await execute(
            f"UPDATE \"{schema}\".learning_reminder_outbox SET claimed_at=now()-interval '11 minutes',first_attempt_at=now()-interval '24 hours' WHERE id=:id",
            {"id": stale_id},
        )
        reclaimed_token = (
            (await call(tenant, "claim_learning_reminder", [tenant, stale_id])).mappings().one()["claim_token"]
        )
        assert reclaimed_token != stale_token
        assert not (
            await call(
                tenant, "finalize_learning_reminder", [tenant, stale_id, stale_token, "success", "synthetic", None]
            )
        ).scalar()
        assert not (
            await call(tenant, "begin_learning_reminder_send", [tenant, stale_id, reclaimed_token, "a" * 64])
        ).scalar()
        assert (
            await execute(
                f'SELECT last_error_category FROM "{schema}".learning_reminder_outbox WHERE id=:id', {"id": stale_id}
            )
        ).scalar() == "retry_window_expired"
        checks.append("stale_claim_recovery_rejects_old_token_and_expired_retry_window")
        limit_id = await new_course_reminder()
        for _attempt in range(3):
            await execute(
                f'UPDATE "{schema}".learning_reminder_outbox SET next_attempt_at=now() WHERE id=:id', {"id": limit_id}
            )
            limit_token = (
                (await call(tenant, "claim_learning_reminder", [tenant, limit_id])).mappings().one()["claim_token"]
            )
            assert (
                await call(tenant, "begin_learning_reminder_send", [tenant, limit_id, limit_token, "a" * 64])
            ).scalar()
            assert (
                await call(
                    tenant,
                    "finalize_learning_reminder",
                    [tenant, limit_id, limit_token, "transient", None, "provider_timeout"],
                )
            ).scalar()
        assert (
            await execute(
                f'SELECT status,attempt_count FROM "{schema}".learning_reminder_outbox WHERE id=:id', {"id": limit_id}
            )
        ).one() == ("failed", 3)
        assert (await call(tenant, "claim_learning_reminder", [tenant, limit_id])).all() == []
        checks.append("three_attempt_budget_terminal")
        stage = "smtp_crash_and_transport_lock"
        for next_transport, expected_reason in (("smtp", "delivery_uncertain"), ("resend", "transport_changed")):
            smtp_id = await new_course_reminder()
            smtp_token = (await call(tenant, "claim_learning_reminder", [tenant, smtp_id])).mappings().one()["claim_token"]
            assert (await call(tenant, "begin_learning_reminder_send", [tenant, smtp_id, smtp_token, "c" * 64, "smtp"])).scalar()
            assert not (await call(tenant, "begin_learning_reminder_send", [tenant, smtp_id, smtp_token, "c" * 64, "smtp"])).scalar()
            await execute(
                f"UPDATE \"{schema}\".learning_reminder_outbox SET claimed_at=now()-interval '11 minutes' WHERE id=:id",
                {"id": smtp_id},
            )
            recovered = (await call(tenant, "claim_learning_reminder", [tenant, smtp_id])).mappings().one()["claim_token"]
            assert recovered != smtp_token
            assert not (await call(tenant, "begin_learning_reminder_send", [tenant, smtp_id, recovered, "c" * 64, next_transport])).scalar()
            row = (await execute(
                f'SELECT status,last_error_category,attempt_count,delivery_transport FROM "{schema}".learning_reminder_outbox WHERE id=:id',
                {"id": smtp_id},
            )).one()
            assert row == ("failed", expected_reason, 1, "smtp")
            assert (await call(tenant, "claim_learning_reminder", [tenant, smtp_id])).all() == []
            checks.append("smtp_" + expected_reason + "_never_resends")
        expired_id = await new_course_reminder()
        await execute(
            f"UPDATE \"{schema}\".learning_reminder_outbox SET due_at=now()-interval '1 second' WHERE id=:id",
            {"id": expired_id},
        )
        expired_token = (
            (await call(tenant, "claim_learning_reminder", [tenant, expired_id])).mappings().one()["claim_token"]
        )
        assert (await call(tenant, "learning_reminder_payload", [tenant, expired_id, expired_token])).all() == []
        assert not (
            await call(tenant, "begin_learning_reminder_send", [tenant, expired_id, expired_token, "a" * 64])
        ).scalar()
        checks.append("expired_predeadline_notification_suppressed")
        stage = "path_occurrence_and_cancellation"
        path, path_rule, cycle, assignment = [uuid4() for _ in range(4)]
        params = dict(ids, p=path, r=path_rule, cy=cycle, a=assignment)
        await execute(f"INSERT INTO \"{schema}\".learning_paths VALUES (:p,:t,'Synthetic program','published')", params)
        await execute(
            f"INSERT INTO \"{schema}\".recurring_learning_rules (id,tenant_id,learning_path_id,user_id,status,reminder_enabled) VALUES (:r,:t,:p,:u,'active',true)",
            params,
        )
        await execute(
            f"INSERT INTO \"{schema}\".learning_path_cycle_instances VALUES (:cy,:t,:r,:p,:u,now()+interval '12 hours','active',NULL)",
            params,
        )
        await execute(
            f"INSERT INTO \"{schema}\".learning_path_assignments VALUES (:a,:t,:p,:u,:cy,'active',NULL,'recurring')",
            params,
        )
        path_reminder = (await call(tenant, "enqueue_learning_reminder", [tenant, None, cycle])).scalar()
        assert (await call(tenant, "enqueue_learning_reminder", [tenant, None, cycle])).scalar() == path_reminder
        path_token = (
            (await call(tenant, "claim_learning_reminder", [tenant, path_reminder])).mappings().one()["claim_token"]
        )
        assert (await call(tenant, "learning_reminder_payload", [tenant, path_reminder, path_token])).mappings().one()[
            "target_type"
        ] == "learning_path"
        await execute(
            f"UPDATE \"{schema}\".learning_path_cycle_instances SET due_at=due_at+interval '1 hour' WHERE id=:cy",
            params,
        )
        assert (await call(tenant, "learning_reminder_payload", [tenant, path_reminder, path_token])).all() == []
        await execute(
            f'UPDATE "{schema}".learning_path_cycle_instances SET due_at=(SELECT due_at FROM "{schema}".learning_reminder_outbox WHERE id=:id) WHERE id=:cy',
            {"id": path_reminder, "cy": cycle},
        )
        checks.append("changed_occurrence_deadline_suppressed")
        await denied(
            call(tenant, "superadmin_purge_tenant_learning_reminders", [tenant, "r2-synthetic"], superadmin=True)
        )
        await execute(f"UPDATE \"{schema}\".learning_path_assignments SET status='cancelled' WHERE id=:a", params)
        assert (await call(tenant, "learning_reminder_payload", [tenant, path_reminder, path_token])).all() == []
        assert not (
            await call(tenant, "begin_learning_reminder_send", [tenant, path_reminder, path_token, "a" * 64])
        ).scalar()
        checks.extend(
            ["one_reminder_per_program_cycle", "cancelled_assignment_suppression", "active_delivery_blocks_purge"]
        )
        stage = "nonempty_downgrade_guard"
        try:
            async with admin.begin() as db:
                await db.run_sync(downgrade_sync)
        except RuntimeError as exc:
            assert str(exc) == "0152 downgrade blocked: reminder delivery history exists"
            checks.append("nonempty_ledger_blocks_downgrade")
        else:
            raise AssertionError("nonempty_downgrade_must_refuse")
        stage = "purge_guard"
        await denied(call(tenant, "superadmin_purge_tenant_learning_reminders", [tenant, "r2-synthetic"]))
        await denied(call(tenant, "superadmin_purge_tenant_learning_reminders", [tenant, "wrong"], superadmin=True))
        assert (
            await call(tenant, "superadmin_purge_tenant_learning_reminders", [tenant, "r2-synthetic"], superadmin=True)
        ).scalar() == 7
        checks.append("bounded_purge_superadmin_and_slug")
        stage = "downgrade"
        async with admin.begin() as db:
            await db.run_sync(downgrade_sync)
        checks.append("empty_ledger_downgrade")
        code = 0
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "scope": "isolated_SQL_contracts_not_full_app",
                    "checks": checks,
                    "provider_calls": 0,
                    "shared_public_writes": 0,
                }
            )
        )
    except Exception as exc:
        # Only synthetic gate labels and exception classes: never connection values.
        original = getattr(exc, "orig", exc)
        sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
        diagnostic = ""
        if sqlstate in {"42501", "42703", "42702", "42601", "42883", "23514", "P0001"}:
            diagnostic = str(original).splitlines()[0][:240]
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "stage": stage,
                    "error_type": type(exc).__name__,
                    "sqlstate": sqlstate,
                    "diagnostic": diagnostic,
                    "passed_checks": checks,
                    "gate_locations": [
                        f"{Path(frame.filename).name}:{frame.lineno}"
                        for frame in traceback.extract_tb(exc.__traceback__)
                        if Path(frame.filename).name
                        in {"learning_reminder_dev_check.py", "learning_reminder_application_check.py"}
                    ],
                }
            )
        )
    finally:
        if made:
            assert re.fullmatch(r"r2_reminder_[0-9a-f]{32}", schema)
            try:
                await execute(f'DROP SCHEMA "{schema}" CASCADE')
                remains = (await execute("SELECT count(*) FROM pg_namespace WHERE nspname=:s", {"s": schema})).scalar()
                print(json.dumps({"cleanup": "PASS" if remains == 0 else "BLOCKED", "remaining_schemas": remains}))
                if remains:
                    code = 4
            except Exception as exc:
                print(json.dumps({"cleanup": "BLOCKED", "schema": schema, "error_type": type(exc).__name__}))
                code = 4
        for engine in engines.values():
            await engine.dispose()
        if code == 4:
            raise SystemExit(4)  # Cleanup failure must override an application-mode return.
    return code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
