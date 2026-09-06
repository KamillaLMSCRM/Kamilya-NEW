"""Verify AI cancellation/save exclusion in a disposable Supabase DEV schema."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values
from kb_rag_isolated_dev_gate import normalize_database_url, same_supabase_project
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "apps" / "api"
SCHEMA_PATTERN = re.compile(r"^li_cancel_[0-9a-f]{12}$")


def validate_schema(value: str) -> str:
    if not SCHEMA_PATTERN.fullmatch(value):
        raise ValueError("unsafe_schema")
    return value


async def run(env_file: Path) -> dict:
    logging.disable(logging.CRITICAL)
    config = dotenv_values(env_file)
    owner_url = normalize_database_url(config.get("MIGRATION_DATABASE_URL") or "")
    runtime_url = normalize_database_url(config.get("DATABASE_URL") or "")
    supabase_url = config.get("SUPABASE_URL") or ""
    if not all(same_supabase_project(url, supabase_url) for url in (owner_url, runtime_url)):
        raise ValueError("not_canonical_supabase_dev")
    if (make_url(runtime_url).username or "").split(".")[0] != "lms_app":
        raise ValueError("wrong_runtime_role")
    if any(make_url(url).database != "postgres" for url in (owner_url, runtime_url)):
        raise ValueError("unexpected_database")

    schema = validate_schema("li_cancel_" + uuid4().hex[:12])
    options = {
        "poolclass": NullPool,
        "hide_parameters": True,
        "connect_args": {
            "timeout": 20,
            "command_timeout": 30,
            "server_settings": {
                "search_path": f'"{schema}",pg_catalog',
                "statement_timeout": "30000",
            },
        },
    }
    owner = create_async_engine(owner_url, **options)
    runtime = create_async_engine(runtime_url, **options)
    runtime_sessions = async_sessionmaker(runtime, expire_on_commit=False)
    report = {"schema": schema, "checks": [], "cleanup": False, "passed": False}
    created = False
    before_head = None
    tenant_id = uuid4()
    user_id = uuid4()

    try:
        async with runtime.connect() as connection:
            role = (
                await connection.execute(
                    text(
                        "SELECT current_user, rolsuper, rolbypassrls "
                        "FROM pg_roles WHERE rolname=current_user"
                    )
                )
            ).one()
            assert role == ("lms_app", False, False), "runtime_role_not_restricted"
        report["checks"].append("restricted_runtime_role")

        async with owner.begin() as connection:
            before_head = (
                await connection.execute(text("SELECT version_num FROM public.alembic_version"))
            ).scalar_one()
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'REVOKE ALL ON SCHEMA "{schema}" FROM PUBLIC'))
            await connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO lms_app'))
            await connection.execute(
                text(
                    f'CREATE FUNCTION "{schema}".set_current_tenant(value uuid) '
                    "RETURNS void LANGUAGE plpgsql AS $$ BEGIN "
                    "PERFORM set_config('app.tenant_id',value::text,true); END $$"
                )
            )
            for table in ("ai_jobs", "courses"):
                target = f'"{schema}"."{table}"'
                await connection.execute(
                    text(f'CREATE TABLE {target} (LIKE public."{table}" INCLUDING ALL)')
                )
                await connection.execute(text(f"REVOKE ALL ON {target} FROM PUBLIC, lms_app"))
                await connection.execute(
                    text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {target} TO lms_app")
                )
                await connection.execute(text(f"ALTER TABLE {target} ENABLE ROW LEVEL SECURITY"))
                await connection.execute(text(f"ALTER TABLE {target} FORCE ROW LEVEL SECURITY"))
                await connection.execute(
                    text(
                        f"CREATE POLICY fixture_tenant ON {target} "
                        "USING (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid) "
                        "WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)"
                    )
                )
        created = True

        os.environ["DATABASE_URL"] = runtime_url
        os.environ["APP_ENV"] = "test"
        os.environ.setdefault("JWT_SECRET", "synthetic-cancellation-test-only-32chars")
        sys.path.insert(0, str(API))
        from app.models import users as _users  # noqa: F401 - register FK target
        from app.modules.ai import pipeline
        from app.modules.ai.architect_schema import CourseStructure
        from app.modules.ai.pipeline import GenerationState
        from app.modules.ai.writer_schema import CourseContent
        from app.modules.courses import release_models as _release_models  # noqa: F401

        pipeline.async_session_factory = runtime_sessions

        async def seed_job(job_id: str) -> None:
            async with owner.begin() as connection:
                await connection.execute(
                    text(
                        f'INSERT INTO "{schema}".ai_jobs '
                        "(id,tenant_id,user_id,status,stage,progress,created_at,updated_at) "
                        "VALUES (:id,:tenant,:user_id,'running','assessment',95,now(),now())"
                    ),
                    {"id": job_id, "tenant": tenant_id, "user_id": user_id},
                )

        async def cancel(job_id: str) -> str:
            from app.modules.ai.job_service import get_ai_job

            async with runtime_sessions() as session:
                await session.execute(
                    text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)}
                )
                job = await get_ai_job(
                    session, job_id, tenant_id=str(tenant_id), for_update=True
                )
                assert job is not None, "job_not_visible"
                if job.status != "running":
                    return job.status
                job.status = "cancelled"
                job.stage = "cancelled"
                job.message = "Cancelled by synthetic DEV check"
                await session.commit()
                return "cancelled"

        def state(job_id: str) -> GenerationState:
            return GenerationState(
                job_id=job_id,
                structure=CourseStructure(title="Synthetic cancellation check"),
                content=CourseContent(title="Synthetic cancellation check"),
            )

        cancelled_first = "cancel-first-" + uuid4().hex
        await seed_job(cancelled_first)
        assert await cancel(cancelled_first) == "cancelled"
        try:
            await pipeline._save_generation_to_db(state(cancelled_first), tenant_id, user_id)
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancelled_save_not_rejected")
        report["checks"].append("cancel_committed_before_save_blocks_course")

        race_outcomes = {"cancelled": 0, "completed": 0}
        for _ in range(6):
            job_id = "cancel-race-" + uuid4().hex
            await seed_job(job_id)

            async def save_once(exact_job_id: str = job_id):
                try:
                    await pipeline._save_generation_to_db(
                        state(exact_job_id), tenant_id, user_id
                    )
                    return "completed"
                except asyncio.CancelledError:
                    return "cancelled"

            await asyncio.gather(save_once(), cancel(job_id))
            async with owner.connect() as connection:
                row = (
                    await connection.execute(
                        text(
                            f'SELECT status,course_id FROM "{schema}".ai_jobs WHERE id=:id'
                        ),
                        {"id": job_id},
                    )
                ).one()
                course_count = (
                    await connection.execute(
                        text(
                            f'SELECT count(*) FROM "{schema}".courses '
                            "WHERE tenant_id=:tenant AND created_by=:user_id"
                        ),
                        {"tenant": tenant_id, "user_id": user_id},
                    )
                ).scalar_one()
            if row.status == "cancelled":
                assert row.course_id is None and course_count == race_outcomes["completed"], (
                    "cancelled_job_has_course"
                )
            else:
                assert row.status == "completed" and row.course_id is not None, (
                    "completed_job_missing_course"
                )
                race_outcomes["completed"] += 1
                assert course_count == race_outcomes["completed"], "course_count_mismatch"
            race_outcomes[row.status] += 1 if row.status == "cancelled" else 0

        assert sum(race_outcomes.values()) == 6, "race_iterations_missing"
        report["checks"].append("concurrent_cancel_save_never_splits_job_and_course")
        report["race_outcomes"] = race_outcomes
        report["passed"] = True
    except Exception as error:
        report["error_type"] = type(error).__name__
        if isinstance(error, AssertionError) and re.fullmatch(r"[a-z0-9_]+", str(error)):
            report["failed_check"] = str(error)
    finally:
        if created:
            try:
                async with owner.begin() as connection:
                    await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
                async with owner.connect() as connection:
                    absent = (
                        await connection.execute(
                            text(
                                "SELECT NOT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:schema)"
                            ),
                            {"schema": schema},
                        )
                    ).scalar_one()
                    after_head = (
                        await connection.execute(
                            text("SELECT version_num FROM public.alembic_version")
                        )
                    ).scalar_one()
                report["cleanup"] = absent
                report["shared_migration_head_unchanged"] = before_head == after_head
            except Exception as error:
                report["cleanup_error_type"] = type(error).__name__
                report["passed"] = False
        await runtime.dispose()
        await owner.dispose()
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
    raise SystemExit(
        0
        if result.get("passed")
        and result.get("cleanup")
        and result.get("shared_migration_head_unchanged")
        else 1
    )
