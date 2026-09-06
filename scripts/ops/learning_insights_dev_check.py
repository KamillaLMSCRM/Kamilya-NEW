"""Synthetic learning-insights gate in a disposable Supabase DEV schema.

No public data is copied or changed. Credentials stay process-local. Only the
exact generated schema is removed. Output contains check names, never DB errors.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import logging
import os
import re
import sys
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from kb_rag_isolated_dev_gate import normalize_database_url, same_supabase_project

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "apps" / "api"
SCHEMA_PATTERN = re.compile(r"^li_dev_[0-9a-f]{12}$")
TABLES = (
    "tenants",
    "users",
    "courses",
    "enrollments",
    "content_releases",
    "positions",
    "departments",
    "modules",
    "lessons",
    "quizzes",
    "quiz_attempts",
    "documents",
    "ai_jobs",
    "document_embeddings",
)


def validate_schema(schema: str) -> str:
    if not SCHEMA_PATTERN.fullmatch(schema):
        raise ValueError("unsafe_schema")
    return schema


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def migrate(connection, schema: str, direction: str):
    validate_schema(schema)
    context = MigrationContext.configure(
        connection, opts={"version_table_schema": schema}
    )
    module = load_module(
        "learning_insights_migration",
        API / "alembic/versions/0155_learning_question_reviews.py",
    )
    with Operations.context(context):
        getattr(module, direction)()


async def run(env_file: Path) -> dict:
    # Existing regression workers log exception traces internally. Gate output
    # is intentionally restricted to sanitized check IDs and exception types.
    logging.disable(logging.CRITICAL)
    config = dotenv_values(env_file)
    owner_url = normalize_database_url(config.get("MIGRATION_DATABASE_URL") or "")
    runtime_url = normalize_database_url(config.get("DATABASE_URL") or "")
    supabase_url = config.get("SUPABASE_URL") or ""
    if not all(
        same_supabase_project(url, supabase_url) for url in (owner_url, runtime_url)
    ):
        raise ValueError("not_canonical_supabase_dev")
    if make_url(runtime_url).username.split(".")[0] != "lms_app":
        raise ValueError("wrong_runtime_role")
    if any(make_url(url).database != "postgres" for url in (owner_url, runtime_url)):
        raise ValueError("unexpected_database")
    schema = validate_schema("li_dev_" + uuid4().hex[:12])
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
    before = None
    try:
        async with runtime.connect() as conn:
            role = (
                await conn.execute(
                    text(
                        "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
                    )
                )
            ).one()
            assert role == ("lms_app", False, False), "runtime_role_not_restricted"
        async with owner.begin() as conn:
            before = (
                (
                    await conn.execute(
                        text(
                            "SELECT version_num FROM public.alembic_version ORDER BY version_num"
                        )
                    )
                )
                .scalars()
                .all()
            )
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        created = True
        async with owner.begin() as conn:
            await conn.execute(text(f'REVOKE ALL ON SCHEMA "{schema}" FROM PUBLIC'))
            await conn.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO lms_app'))
            await conn.execute(
                text(f"""CREATE FUNCTION "{schema}".set_current_tenant(value uuid)
                RETURNS void LANGUAGE plpgsql AS $$ BEGIN
                PERFORM set_config('app.tenant_id',value::text,true); END $$""")
            )
            for table in TABLES:
                sequences = (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name=:table AND column_default LIKE '%nextval%'"
                        ),
                        {"table": table},
                    )
                ).scalar_one()
                assert sequences == 0, "shared_sequence_default"
                target = f'"{schema}"."{table}"'
                await conn.execute(
                    text(f'CREATE TABLE {target} (LIKE public."{table}" INCLUDING ALL)')
                )
                await conn.execute(text(f"REVOKE ALL ON {target} FROM PUBLIC, lms_app"))
                await conn.execute(text(f"GRANT SELECT ON {target} TO lms_app"))
                await conn.execute(
                    text(f"ALTER TABLE {target} ENABLE ROW LEVEL SECURITY")
                )
                await conn.execute(
                    text(f"ALTER TABLE {target} FORCE ROW LEVEL SECURITY")
                )
                column = "id" if table == "tenants" else "tenant_id"
                await conn.execute(
                    text(
                        f"CREATE POLICY fixture_tenant ON {target} USING ({column}=nullif(current_setting('app.tenant_id',true),'')::uuid)"
                    )
                )
            for direction in ("upgrade", "downgrade", "upgrade"):
                await conn.run_sync(
                    lambda sync, step=direction: migrate(sync, schema, step)
                )
                exists = (
                    await conn.execute(
                        text("SELECT to_regclass(:name) IS NOT NULL"),
                        {"name": f"{schema}.learning_question_reviews"},
                    )
                ).scalar_one()
                assert exists == (direction == "upgrade"), "migration_readback"
        report["checks"].append("migration_upgrade_downgrade_reupgrade")
        # Settings can import only the restricted runtime credential; not the owner.
        os.environ["DATABASE_URL"] = runtime_url
        os.environ["APP_ENV"] = "test"
        os.environ.setdefault(
            "JWT_SECRET", "synthetic-learning-insights-test-only-32chars"
        )
        sys.path.insert(0, str(API))
        checks = load_module(
            "learning_insights_db_gate",
            API / "tests/integration/test_learning_insights_db.py",
        )
        await checks.exercise(owner, runtime, schema, report["checks"])
        await checks.exercise_document_regression(owner, report["checks"])
        report["passed"] = True
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        # Assertions use deliberately sanitized, constant check IDs only.
        if isinstance(exc, AssertionError) and re.fullmatch(r"[a-z0-9_]+", str(exc)):
            report["failed_check"] = str(exc)
    finally:
        if created:
            try:
                validate_schema(schema)
                async with owner.begin() as conn:
                    await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
                async with owner.connect() as conn:
                    absent = (
                        await conn.execute(
                            text(
                                "SELECT NOT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:schema)"
                            ),
                            {"schema": schema},
                        )
                    ).scalar_one()
                    after = (
                        (
                            await conn.execute(
                                text(
                                    "SELECT version_num FROM public.alembic_version ORDER BY version_num"
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                report["cleanup"] = absent
                report["shared_migration_head_unchanged"] = before == after
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
