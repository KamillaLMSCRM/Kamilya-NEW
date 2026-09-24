"""Exercise migration 0163 and Learning Actions RLS in disposable Supabase DEV."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import sys
from pathlib import Path
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from kb_rag_isolated_dev_gate import normalize_database_url, same_supabase_project

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "apps" / "api"
SCHEMA_PATTERN = re.compile(r"^la_dev_[0-9a-f]{12}$")


def _schema(value: str) -> str:
    if not SCHEMA_PATTERN.fullmatch(value):
        raise ValueError("unsafe_schema")
    return value


def _load_migration():
    path = API / "alembic" / "versions" / "0163_learning_actions.py"
    spec = importlib.util.spec_from_file_location("learning_actions_0163", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("migration_loader_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migrate(connection, schema: str, direction: str) -> None:
    context = MigrationContext.configure(
        connection, opts={"version_table_schema": _schema(schema)}
    )
    module = _load_migration()
    with Operations.context(context):
        getattr(module, direction)()


async def _expect_rejected(connection, statement, params: dict) -> None:
    nested = await connection.begin_nested()
    try:
        await connection.execute(statement, params)
    except DBAPIError:
        await nested.rollback()
        return
    await nested.rollback()
    raise AssertionError("expected_statement_rejected")


async def run(env_file: Path) -> dict:
    values = dotenv_values(env_file)
    owner_url = normalize_database_url(values.get("MIGRATION_DATABASE_URL") or "")
    runtime_url = normalize_database_url(values.get("DATABASE_URL") or "")
    supabase_url = values.get("SUPABASE_URL") or ""
    if not same_supabase_project(owner_url, supabase_url) or not same_supabase_project(
        runtime_url, supabase_url
    ):
        raise ValueError("canonical_dev_identity_mismatch")
    if (make_url(runtime_url).username or "").split(".")[0] != "lms_app":
        raise ValueError("runtime_role_not_lms_app")
    if any(make_url(url).database != "postgres" for url in (owner_url, runtime_url)):
        raise ValueError("unexpected_database")

    schema = _schema(f"la_dev_{uuid4().hex[:12]}")
    options = {
        "poolclass": NullPool,
        "hide_parameters": True,
        "connect_args": {
            "timeout": 20,
            "command_timeout": 45,
            "server_settings": {
                "search_path": f'"{schema}",pg_catalog',
                "statement_timeout": "45000",
            },
        },
    }
    owner = create_async_engine(owner_url, **options)
    runtime = create_async_engine(runtime_url, **options)
    report = {"schema": schema, "checks": [], "passed": False, "cleanup": False}
    created = False
    public_before = None
    ids: dict[str, UUID] = {
        name: uuid4()
        for name in (
            "tenant_a",
            "tenant_b",
            "methodologist_a",
            "methodologist_b",
            "learner_a",
            "learner_b",
            "course_a",
            "course_b",
            "enrollment_a",
            "enrollment_b",
            "action_a",
        )
    }
    q = f'"{schema}"'
    try:
        async with runtime.connect() as connection:
            role = (
                await connection.execute(
                    text(
                        "SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
                    )
                )
            ).one()
            assert role == ("lms_app", False, False), "runtime_role_not_restricted"
        async with owner.begin() as connection:
            public_before = (
                (
                    await connection.execute(
                        text(
                            "SELECT version_num FROM public.alembic_version ORDER BY version_num"
                        )
                    )
                )
                .scalars()
                .all()
            )
            await connection.execute(text(f"CREATE SCHEMA {q}"))
            await connection.execute(text(f"REVOKE ALL ON SCHEMA {q} FROM PUBLIC"))
            await connection.execute(text(f"GRANT USAGE ON SCHEMA {q} TO lms_app"))
        created = True
        async with owner.begin() as connection:
            await connection.execute(
                text(f"CREATE TABLE {q}.tenants (id uuid PRIMARY KEY)")
            )
            await connection.execute(
                text(
                    f"CREATE TABLE {q}.users (id uuid PRIMARY KEY,tenant_id uuid NOT NULL,role text NOT NULL,is_active boolean NOT NULL DEFAULT true)"
                )
            )
            await connection.execute(
                text(
                    f"CREATE TABLE {q}.courses (id uuid PRIMARY KEY,tenant_id uuid NOT NULL,title text NOT NULL)"
                )
            )
            await connection.execute(
                text(
                    f"CREATE TABLE {q}.enrollments (id uuid PRIMARY KEY,tenant_id uuid NOT NULL,user_id uuid NOT NULL,course_id uuid NOT NULL,status text NOT NULL)"
                )
            )
            for table in ("tenants", "users", "courses", "enrollments"):
                column = "id" if table == "tenants" else "tenant_id"
                await connection.execute(
                    text(f"ALTER TABLE {q}.{table} ENABLE ROW LEVEL SECURITY")
                )
                await connection.execute(
                    text(f"ALTER TABLE {q}.{table} FORCE ROW LEVEL SECURITY")
                )
                await connection.execute(
                    text(
                        f"CREATE POLICY fixture_tenant ON {q}.{table} USING ({column}=nullif(current_setting('app.tenant_id',true),'')::uuid)"
                    )
                )
                await connection.execute(
                    text(f"GRANT SELECT ON {q}.{table} TO lms_app")
                )
            await connection.execute(
                text(f"INSERT INTO {q}.tenants(id) VALUES (:ta),(:tb)"),
                {"ta": ids["tenant_a"], "tb": ids["tenant_b"]},
            )
            await connection.execute(
                text(
                    f"INSERT INTO {q}.users(id,tenant_id,role) VALUES (:ma,:ta,'methodologist'),(:mb,:tb,'methodologist'),(:la,:ta,'student'),(:lb,:tb,'student')"
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
                    f"INSERT INTO {q}.courses(id,tenant_id,title) VALUES (:ca,:ta,'A'),(:cb,:tb,'B')"
                ),
                {
                    "ca": ids["course_a"],
                    "cb": ids["course_b"],
                    "ta": ids["tenant_a"],
                    "tb": ids["tenant_b"],
                },
            )
            await connection.execute(
                text(
                    f"INSERT INTO {q}.enrollments(id,tenant_id,user_id,course_id,status) VALUES (:ea,:ta,:la,:ca,'enrolled'),(:eb,:tb,:lb,:cb,'enrolled')"
                ),
                {
                    "ea": ids["enrollment_a"],
                    "eb": ids["enrollment_b"],
                    "ta": ids["tenant_a"],
                    "tb": ids["tenant_b"],
                    "la": ids["learner_a"],
                    "lb": ids["learner_b"],
                    "ca": ids["course_a"],
                    "cb": ids["course_b"],
                },
            )
            for direction in ("upgrade", "downgrade", "upgrade"):
                await connection.run_sync(
                    lambda sync, step=direction: _migrate(sync, schema, step)
                )
                exists = bool(
                    await connection.scalar(
                        text("SELECT to_regclass(:name) IS NOT NULL"),
                        {"name": f"{schema}.learning_actions"},
                    )
                )
                assert exists == (direction == "upgrade"), "migration_cycle_readback"
        report["checks"].append("migration_upgrade_downgrade_reupgrade")

        async with runtime.begin() as connection:
            await connection.execute(
                text("SELECT set_config('app.tenant_id',:tenant,true)"),
                {"tenant": str(ids["tenant_a"])},
            )
            await connection.execute(
                text("""INSERT INTO learning_actions
                    (id,tenant_id,target_type,target_key,enrollment_id,course_id,issue_type,action_type,owner_id,created_by,baseline_snapshot)
                    VALUES (:id,:tenant,'enrollment',:target,:enrollment,:course,'not_started','manual_review',:owner,:actor,'{}'::jsonb)"""),
                {
                    "id": ids["action_a"],
                    "tenant": ids["tenant_a"],
                    "target": f"enrollment:{ids['enrollment_a']}",
                    "enrollment": ids["enrollment_a"],
                    "course": ids["course_a"],
                    "owner": ids["methodologist_a"],
                    "actor": ids["methodologist_a"],
                },
            )
            await _expect_rejected(
                connection,
                text(
                    "INSERT INTO learning_action_events(tenant_id,action_id,event_type,actor_id,payload) VALUES (:tenant,:action,'created',:actor,'{}'::jsonb)"
                ),
                {
                    "tenant": ids["tenant_a"],
                    "action": ids["action_a"],
                    "actor": ids["methodologist_b"],
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO learning_action_events(tenant_id,action_id,event_type,actor_id,payload) VALUES (:tenant,:action,'created',:actor,'{}'::jsonb)"
                ),
                {
                    "tenant": ids["tenant_a"],
                    "action": ids["action_a"],
                    "actor": ids["methodologist_a"],
                },
            )
            assert (
                int(
                    await connection.scalar(
                        text("SELECT count(*) FROM learning_actions")
                    )
                    or 0
                )
                == 1
            ), "tenant_a_action_visible"
            await _expect_rejected(
                connection,
                text("""INSERT INTO learning_actions
                    (id,tenant_id,target_type,target_key,enrollment_id,course_id,issue_type,action_type,owner_id,created_by,baseline_snapshot)
                    VALUES (:id,:tenant,'enrollment',:target,:foreign_enrollment,:course,'not_started','manual_review',:owner,:actor,'{}'::jsonb)"""),
                {
                    "id": uuid4(),
                    "tenant": ids["tenant_a"],
                    "target": f"enrollment:{ids['enrollment_b']}",
                    "foreign_enrollment": ids["enrollment_b"],
                    "course": ids["course_a"],
                    "owner": ids["methodologist_a"],
                    "actor": ids["methodologist_a"],
                },
            )
            await _expect_rejected(
                connection,
                text(
                    "UPDATE learning_action_events SET payload='{}'::jsonb WHERE action_id=:action"
                ),
                {"action": ids["action_a"]},
            )
            await _expect_rejected(
                connection,
                text("DELETE FROM learning_actions WHERE id=:action"),
                {"action": ids["action_a"]},
            )
            await connection.execute(
                text("""UPDATE learning_actions SET status='completed',resolution='observed',
                    outcome_snapshot=CAST(:outcome AS jsonb),closed_at=now(),updated_at=now() WHERE id=:action"""),
                {"action": ids["action_a"], "outcome": '{"available": true}'},
            )
            await connection.execute(
                text(
                    "INSERT INTO learning_action_events(tenant_id,action_id,event_type,actor_id,payload) VALUES (:tenant,:action,'closed',:actor,'{}'::jsonb)"
                ),
                {
                    "tenant": ids["tenant_a"],
                    "action": ids["action_a"],
                    "actor": ids["methodologist_a"],
                },
            )
            assert (
                int(
                    await connection.scalar(
                        text("SELECT count(*) FROM learning_action_events")
                    )
                    or 0
                )
                == 2
            ), "append_only_events_retained"
        report["checks"].extend(
            (
                "tenant_owned_insert_and_close",
                "cross_tenant_target_rejected",
                "cross_tenant_event_actor_rejected",
                "event_update_and_action_delete_rejected",
            )
        )

        async with runtime.begin() as connection:
            await connection.execute(
                text("SELECT set_config('app.tenant_id',:tenant,true)"),
                {"tenant": str(ids["tenant_b"])},
            )
            assert (
                int(
                    await connection.scalar(
                        text("SELECT count(*) FROM learning_actions")
                    )
                    or 0
                )
                == 0
            ), "tenant_b_isolated"
        report["checks"].append("tenant_read_isolation")
        report["passed"] = True
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        if isinstance(exc, AssertionError) and re.fullmatch(r"[a-z0-9_]+", str(exc)):
            report["failed_check"] = str(exc)
    finally:
        if created:
            try:
                async with owner.begin() as connection:
                    await connection.execute(text(f"DROP SCHEMA {q} CASCADE"))
                async with owner.connect() as connection:
                    report["cleanup"] = bool(
                        await connection.scalar(
                            text(
                                "SELECT NOT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:schema)"
                            ),
                            {"schema": schema},
                        )
                    )
                    public_after = (
                        (
                            await connection.execute(
                                text(
                                    "SELECT version_num FROM public.alembic_version ORDER BY version_num"
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    report["shared_migration_head_unchanged"] = (
                        public_before == public_after
                    )
            except Exception as exc:
                report["cleanup_error_type"] = type(exc).__name__
                report["passed"] = False
        await owner.dispose()
        await runtime.dispose()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args.env_file.resolve(strict=True)))
    except Exception as error:
        result = {"passed": False, "error_type": type(error).__name__}
    print(json.dumps(result, indent=2))
    sys.exit(
        0
        if result.get("passed")
        and result.get("cleanup")
        and result.get("shared_migration_head_unchanged")
        else 1
    )
