"""Exercise migration 0162 in a disposable Supabase DEV schema."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from dotenv import dotenv_values
from kb_rag_isolated_dev_gate import normalize_database_url, same_supabase_project
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "apps" / "api"
SCHEMA_PATTERN = re.compile(r"^reassignment_dev_[0-9a-f]{12}$")


def _validated_schema(schema: str) -> str:
    if not SCHEMA_PATTERN.fullmatch(schema):
        raise ValueError("unsafe_schema")
    return schema


def _load_migration():
    path = API / "alembic" / "versions" / "0162_manual_reassignment_occurrences.py"
    spec = importlib.util.spec_from_file_location("manual_reassignment_0162", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("migration_loader_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _upgrade(sync_connection, schema: str) -> None:
    context = MigrationContext.configure(
        sync_connection, opts={"version_table_schema": schema}
    )
    with Operations.context(context):
        _load_migration().upgrade()


def _downgrade(sync_connection, schema: str) -> None:
    context = MigrationContext.configure(
        sync_connection, opts={"version_table_schema": schema}
    )
    with Operations.context(context):
        _load_migration().downgrade()


async def _public_revision(connection: AsyncConnection) -> str:
    if not await connection.scalar(
        text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
    ):
        return "absent"
    return str(
        await connection.scalar(text("SELECT version_num FROM public.alembic_version"))
        or "empty"
    )


async def _expect_rejected(
    connection: AsyncConnection, statement, params: dict
) -> None:
    savepoint = await connection.begin_nested()
    try:
        await connection.execute(statement, params)
    except Exception:
        await savepoint.rollback()
        return
    await savepoint.rollback()
    raise AssertionError("expected_statement_to_be_rejected")


async def _create_baseline(owner, schema: str) -> dict[str, UUID]:
    ids = {
        "tenant_a": uuid4(),
        "tenant_b": uuid4(),
        "methodologist_a": uuid4(),
        "methodologist_b": uuid4(),
        "learner_a": uuid4(),
        "learner_b": uuid4(),
        "course_a": uuid4(),
        "predecessor_a": uuid4(),
        "predecessor_b": uuid4(),
        "policy_a": uuid4(),
        "policy_ambiguous": uuid4(),
    }
    q = f'"{schema}"'
    async with owner.begin() as connection:
        await connection.execute(text(f"CREATE SCHEMA {q}"))
        await connection.execute(text(f"REVOKE ALL ON SCHEMA {q} FROM PUBLIC"))
        await connection.execute(text(f"GRANT USAGE ON SCHEMA {q} TO lms_app"))
        await connection.execute(
            text(
                f"CREATE TABLE {q}.users ("
                "id uuid PRIMARY KEY, tenant_id uuid NOT NULL, role text NOT NULL)"
            )
        )
        await connection.execute(
            text(
                f"CREATE TABLE {q}.enrollments ("
                "id uuid PRIMARY KEY, course_id uuid NOT NULL, "
                "user_id uuid NOT NULL, tenant_id uuid NOT NULL, "
                "status text NOT NULL, source text NOT NULL DEFAULT 'manual', "
                "recurring_assignment_id uuid NULL, "
                "learning_path_assignment_id uuid NULL)"
            )
        )
        await connection.execute(
            text(
                f"CREATE UNIQUE INDEX uq_enrollments_legacy_active ON {q}.enrollments "
                "(user_id,course_id,tenant_id) "
                "WHERE status IN ('enrolled','completed') "
                "AND recurring_assignment_id IS NULL "
                "AND learning_path_assignment_id IS NULL"
            )
        )
        await connection.execute(
            text(
                f"CREATE TABLE {q}.enrollment_access_policies ("
                "id uuid PRIMARY KEY, tenant_id uuid NOT NULL, enrollment_id uuid NOT NULL, "
                "user_id uuid NOT NULL, delivery_mode text NOT NULL DEFAULT 'email', "
                "link_expires_at timestamptz NULL, due_at timestamptz NULL, "
                "created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NULL)"
            )
        )
        await connection.execute(
            text(
                f"INSERT INTO {q}.users (id,tenant_id,role) VALUES "
                "(:ma,:ta,'methodologist'),(:mb,:tb,'methodologist'),"
                "(:la,:ta,'student'),(:lb,:tb,'student')"
            ),
            {
                "ma": ids["methodologist_a"],
                "mb": ids["methodologist_b"],
                "la": ids["learner_a"],
                "lb": ids["learner_b"],
                "ta": ids["tenant_a"],
                "tb": ids["tenant_b"],
            },
        )
        await connection.execute(
            text(
                f"INSERT INTO {q}.enrollments "
                "(id,course_id,user_id,tenant_id,status,source) VALUES "
                "(:ea,:course,:la,:ta,'completed','manual'),"
                "(:eb,:course,:lb,:tb,'completed','manual')"
            ),
            {
                "ea": ids["predecessor_a"],
                "eb": ids["predecessor_b"],
                "course": ids["course_a"],
                "la": ids["learner_a"],
                "lb": ids["learner_b"],
                "ta": ids["tenant_a"],
                "tb": ids["tenant_b"],
            },
        )
        await connection.execute(
            text(
                f"INSERT INTO {q}.enrollment_access_policies "
                "(id,tenant_id,enrollment_id,user_id,delivery_mode,link_expires_at,due_at,created_at,updated_at) "
                "VALUES (:id,:tenant,:enrollment,:user,'personal_link',"
                "now()+interval '7 days',now()+interval '14 days',now(),now())"
            ),
            {
                "id": ids["policy_a"],
                "tenant": ids["tenant_a"],
                "enrollment": ids["predecessor_a"],
                "user": ids["learner_a"],
            },
        )
        await connection.execute(
            text(
                f"INSERT INTO {q}.enrollment_access_policies "
                "(id,tenant_id,enrollment_id,user_id,delivery_mode,link_expires_at,due_at,created_at,updated_at) "
                "VALUES (:id,:tenant,:enrollment,:user,'email',"
                "now()+interval '7 days',now()+interval '14 days',now()-interval '30 days',now())"
            ),
            {
                "id": ids["policy_ambiguous"],
                "tenant": ids["tenant_b"],
                "enrollment": ids["predecessor_b"],
                "user": ids["learner_b"],
            },
        )
        for table in ("users", "enrollments"):
            await connection.execute(
                text(f"ALTER TABLE {q}.{table} ENABLE ROW LEVEL SECURITY")
            )
            await connection.execute(
                text(f"ALTER TABLE {q}.{table} FORCE ROW LEVEL SECURITY")
            )
            await connection.execute(
                text(
                    f"CREATE POLICY tenant_isolation ON {q}.{table} FOR ALL TO lms_app "
                    "USING (tenant_id="
                    "nullif(current_setting('app.tenant_id',true),'')::uuid) "
                    "WITH CHECK (tenant_id="
                    "nullif(current_setting('app.tenant_id',true),'')::uuid)"
                )
            )
            await connection.execute(
                text(f"REVOKE ALL ON TABLE {q}.{table} FROM PUBLIC, lms_app")
            )
            await connection.execute(
                text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {q}.{table} TO lms_app")
            )
        await connection.run_sync(_upgrade, schema)
        durations = (
            await connection.execute(
                text(
                    f"SELECT link_validity_minutes,due_window_minutes FROM {q}.enrollment_access_policies "
                    "WHERE id=:id"
                ),
                {"id": ids["policy_a"]},
            )
        ).one()
        assert tuple(durations) == (7 * 24 * 60, 14 * 24 * 60), "policy_duration_backfill_failed"
        ambiguous_durations = (
            await connection.execute(
                text(
                    f"SELECT link_validity_minutes,due_window_minutes FROM {q}.enrollment_access_policies "
                    "WHERE id=:id"
                ),
                {"id": ids["policy_ambiguous"]},
            )
        ).one()
        assert tuple(ambiguous_durations) == (None, None), "ambiguous_policy_backfill_must_fail_closed"
    return ids


async def _exercise_runtime(
    runtime, schema: str, ids: dict[str, UUID]
) -> tuple[list[str], UUID]:
    q = f'"{schema}"'
    checks: list[str] = []
    successor_id = uuid4()
    async with runtime.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(text(f"SET LOCAL search_path TO {q}, public"))
            role = await connection.execute(
                text(
                    "SELECT current_user, rolsuper, rolbypassrls "
                    "FROM pg_roles WHERE rolname=current_user"
                )
            )
            assert tuple(role.one()) == (
                "lms_app",
                False,
                False,
            ), "runtime_role_not_restricted"
            await connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"),
                {"tenant": str(ids["tenant_a"])},
            )
            await connection.execute(
                text(
                    "INSERT INTO enrollments "
                    "(id,course_id,user_id,tenant_id,status,source,previous_enrollment_id,"
                    "reassignment_reason,reassigned_by,reassigned_at) VALUES "
                    "(:id,:course,:user,:tenant,'enrolled','manual',:previous,"
                    "'annual refresh',:actor,now())"
                ),
                {
                    "id": successor_id,
                    "course": ids["course_a"],
                    "user": ids["learner_a"],
                    "tenant": ids["tenant_a"],
                    "previous": ids["predecessor_a"],
                    "actor": ids["methodologist_a"],
                },
            )
            checks.append("valid_same_tenant_occurrence_inserted")
            await _expect_rejected(
                connection,
                text(
                    "INSERT INTO enrollments "
                    "(id,course_id,user_id,tenant_id,status,source,previous_enrollment_id,"
                    "reassignment_reason,reassigned_by,reassigned_at) VALUES "
                    "(:id,:course,:user,:tenant,'enrolled','manual',:previous,"
                    "'bad predecessor',:actor,now())"
                ),
                {
                    "id": uuid4(),
                    "course": ids["course_a"],
                    "user": ids["learner_a"],
                    "tenant": ids["tenant_a"],
                    "previous": ids["predecessor_b"],
                    "actor": ids["methodologist_a"],
                },
            )
            checks.append("cross_tenant_predecessor_rejected")
            await _expect_rejected(
                connection,
                text(
                    "INSERT INTO enrollments "
                    "(id,course_id,user_id,tenant_id,status,source,previous_enrollment_id,"
                    "reassignment_reason,reassigned_by,reassigned_at) VALUES "
                    "(:id,:course,:user,:tenant,'completed','manual',:previous,"
                    "'bad actor',:actor,now())"
                ),
                {
                    "id": uuid4(),
                    "course": ids["course_a"],
                    "user": ids["learner_a"],
                    "tenant": ids["tenant_a"],
                    "previous": ids["predecessor_a"],
                    "actor": ids["methodologist_b"],
                },
            )
            checks.append("cross_tenant_actor_rejected")
            assert (
                await connection.scalar(text("SELECT count(*) FROM enrollments")) == 2
            )
            checks.extend(("tenant_read_isolation", "force_rls_runtime_write"))
            await transaction.commit()
        finally:
            if transaction.is_active:
                await transaction.rollback()
    return checks, successor_id


async def _exercise_downgrade_reupgrade(
    owner, schema: str, ids: dict[str, UUID], successor_id: UUID
) -> list[str]:
    q = f'"{schema}"'
    checks: list[str] = []
    async with owner.begin() as connection:
        await connection.execute(
            text(f"UPDATE {q}.users SET role='admin' WHERE id=:id"),
            {"id": ids["methodologist_a"]},
        )
        await connection.execute(
            text(f"UPDATE {q}.enrollments SET status='completed' WHERE id=:id"),
            {"id": successor_id},
        )
        checks.append("status_update_survives_actor_role_change")
    async with owner.begin() as connection:
        try:
            await connection.run_sync(_downgrade, schema)
        except Exception:
            checks.append("downgrade_refuses_existing_history")
        else:
            raise AssertionError("downgrade_did_not_protect_history")
    async with owner.begin() as connection:
        await connection.execute(
            text(f"DELETE FROM {q}.enrollments WHERE id=:id"), {"id": successor_id}
        )
        await connection.run_sync(_downgrade, schema)
        columns = int(
            await connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema=:schema "
                    "AND table_name='enrollments' AND column_name IN "
                    "('previous_enrollment_id','reassignment_reason','reassigned_by','reassigned_at')"
                ),
                {"schema": schema},
            )
            or 0
        )
        assert columns == 0, "downgrade_did_not_remove_columns"
        policy_columns = int(
            await connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema=:schema AND table_name='enrollment_access_policies' "
                    "AND column_name IN ('link_validity_minutes','due_window_minutes')"
                ),
                {"schema": schema},
            )
            or 0
        )
        assert policy_columns == 0, "downgrade_did_not_remove_policy_duration_columns"
        await connection.run_sync(_upgrade, schema)
        checks.extend(("clean_downgrade", "reupgrade"))
    return checks


async def main() -> int:
    values = dotenv_values(Path(os.environ.get("KAMILYA_DEV_ENV_FILE", ROOT / ".env")))
    owner_url = normalize_database_url(values.get("MIGRATION_DATABASE_URL") or "")
    runtime_url = normalize_database_url(values.get("DATABASE_URL") or "")
    if not same_supabase_project(owner_url, values.get("SUPABASE_URL") or ""):
        print(
            json.dumps(
                {"status": "BLOCKED", "reason": "canonical_dev_identity_mismatch"}
            )
        )
        return 2
    if not same_supabase_project(runtime_url, values.get("SUPABASE_URL") or ""):
        print(
            json.dumps({"status": "BLOCKED", "reason": "runtime_dev_identity_mismatch"})
        )
        return 2
    if (make_url(runtime_url).username or "").split(".")[0] != "lms_app":
        print(json.dumps({"status": "BLOCKED", "reason": "runtime_role_not_lms_app"}))
        return 2

    schema = _validated_schema(f"reassignment_dev_{uuid4().hex[:12]}")
    owner = create_async_engine(owner_url, poolclass=NullPool, hide_parameters=True)
    runtime = create_async_engine(runtime_url, poolclass=NullPool, hide_parameters=True)
    public_before = public_after = "not_read"
    stage = "read_public_revision_before"
    try:
        async with owner.connect() as connection:
            public_before = await _public_revision(connection)
        stage = "create_baseline_and_upgrade"
        ids = await _create_baseline(owner, schema)
        stage = "exercise_runtime"
        checks, successor_id = await _exercise_runtime(runtime, schema, ids)
        stage = "downgrade_reupgrade"
        checks.extend(await _exercise_downgrade_reupgrade(owner, schema, ids, successor_id))
        async with owner.connect() as connection:
            public_after = await _public_revision(connection)
        assert public_before == public_after, "shared_public_revision_changed"
        checks.append("shared_public_revision_unchanged")
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "target": "isolated_supabase_dev_schema",
                    "checks": checks,
                }
            )
        )
        return 0
    except Exception as exc:
        origin = getattr(exc, "orig", None)
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "stage": stage,
                    "reason": type(exc).__name__,
                    "sqlstate": getattr(origin, "sqlstate", None),
                }
            )
        )
        return 1
    finally:
        cleanup = "BLOCKED"
        try:
            async with owner.begin() as connection:
                await connection.execute(
                    text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                )
            async with owner.connect() as connection:
                residue = int(
                    await connection.scalar(
                        text("SELECT count(*) FROM pg_namespace WHERE nspname=:schema"),
                        {"schema": schema},
                    )
                    or 0
                )
            cleanup = "PASS" if residue == 0 else "BLOCKED"
        finally:
            print(
                json.dumps(
                    {
                        "cleanup": cleanup,
                        "schema": "disposable",
                        "public_revision_unchanged": public_before != "not_read"
                        and public_before == public_after,
                    }
                )
            )
            await runtime.dispose()
            await owner.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
