"""Run the AI generation checkpoint migration against an isolated Supabase DEV schema.

The gate never modifies public application data or the public migration head. It
creates one random disposable schema, exercises migration 0158 and the runtime
``lms_app`` role, then removes that exact schema. Output is deliberately
sanitized: no connection strings, SQL errors, payloads, or tenant identifiers.
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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from kb_rag_isolated_dev_gate import normalize_database_url, same_supabase_project

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "apps" / "api"
SCHEMA_PATTERN = re.compile(r"^aicp_dev_[0-9a-f]{12}$")


def validate_schema(schema: str) -> str:
    if not SCHEMA_PATTERN.fullmatch(schema):
        raise ValueError("unsafe_schema")
    return schema


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("migration_loader_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def migrate(connection, schema: str, direction: str) -> None:
    validate_schema(schema)
    context = MigrationContext.configure(
        connection,
        opts={"version_table_schema": schema},
    )
    module = load_module(
        "ai_generation_checkpoint_migration",
        API / "alembic" / "versions" / "0158_ai_generation_checkpoints.py",
    )
    with Operations.context(context):
        getattr(module, direction)()


async def set_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    await session.execute(
        text("SELECT set_current_tenant(:tenant_id)"),
        {"tenant_id": str(tenant_id)},
    )


async def create_fixture(owner: AsyncEngine, schema: str) -> tuple[UUID, UUID, str, str]:
    tenant_a = uuid4()
    tenant_b = uuid4()
    job_a = str(uuid4())
    resume_job = str(uuid4())
    async with owner.begin() as conn:
        await conn.execute(text(f'REVOKE ALL ON SCHEMA "{schema}" FROM PUBLIC'))
        await conn.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO lms_app'))
        await conn.execute(
            text(
                f'''CREATE FUNCTION "{schema}".set_current_tenant(value uuid)
                RETURNS void LANGUAGE plpgsql AS $$ BEGIN
                PERFORM set_config('app.tenant_id', value::text, true); END $$'''
            )
        )
        await conn.execute(
            text(f'REVOKE ALL ON FUNCTION "{schema}".set_current_tenant(uuid) FROM PUBLIC')
        )
        await conn.execute(
            text(f'GRANT EXECUTE ON FUNCTION "{schema}".set_current_tenant(uuid) TO lms_app')
        )
        await conn.execute(
            text(
                f'''CREATE TABLE "{schema}".tenants (
                    id uuid PRIMARY KEY,
                    name text NOT NULL,
                    slug text NOT NULL UNIQUE
                )'''
            )
        )
        await conn.execute(
            text(
                f'''CREATE TABLE "{schema}".ai_jobs (
                    id varchar PRIMARY KEY,
                    tenant_id uuid NOT NULL REFERENCES "{schema}".tenants(id),
                    user_id uuid NOT NULL,
                    course_id uuid,
                    status varchar NOT NULL DEFAULT 'pending',
                    stage varchar NOT NULL DEFAULT 'queued',
                    progress integer NOT NULL DEFAULT 0,
                    message text,
                    params json,
                    result json,
                    errors json,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now(),
                    started_at timestamptz,
                    completed_at timestamptz
                )'''
            )
        )
        for table_name, tenant_column in (("tenants", "id"), ("ai_jobs", "tenant_id")):
            table = f'"{schema}".{table_name}'
            await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            await conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
            await conn.execute(
                text(
                    f'''CREATE POLICY fixture_tenant ON {table} FOR ALL TO lms_app
                    USING ({tenant_column}=nullif(current_setting('app.tenant_id',true),'')::uuid)
                    WITH CHECK ({tenant_column}=nullif(current_setting('app.tenant_id',true),'')::uuid)'''
                )
            )
            await conn.execute(text(f"REVOKE ALL ON {table} FROM PUBLIC, lms_app"))
            await conn.execute(text(f"GRANT SELECT, UPDATE ON {table} TO lms_app"))
        await conn.execute(
            text(f'INSERT INTO "{schema}".tenants (id,name,slug) VALUES (:a,\'A\',\'a\'),(:b,\'B\',\'b\')'),
            {"a": tenant_a, "b": tenant_b},
        )
        await conn.execute(
            text(
                f'''INSERT INTO "{schema}".ai_jobs
                (id,tenant_id,user_id,status,stage,progress,result)
                VALUES
                (:job_a,:tenant_a,:user_a,'running','content',40,CAST(:result AS json)),
                (:resume_job,:tenant_a,:user_b,'interrupted','interrupted',60,CAST(:result AS json))'''
            ),
            {
                "job_a": job_a,
                "resume_job": resume_job,
                "tenant_a": tenant_a,
                "user_a": uuid4(),
                "user_b": uuid4(),
                "result": json.dumps({"resume_count": 0}),
            },
        )
    return tenant_a, tenant_b, job_a, resume_job


async def exercise_runtime(
    owner: AsyncEngine,
    runtime: AsyncEngine,
    schema: str,
    tenant_a: UUID,
    tenant_b: UUID,
    job_a: str,
    resume_job: str,
    checks: list[str],
) -> None:
    del owner, schema
    from app.modules.ai.generation_checkpoint import (
        AIGenerationCheckpointError,
        AIGenerationCheckpointRepository,
        AIGenerationIncompleteError,
        PlannedLesson,
    )
    from app.modules.ai.job_service import (
        AIJobSubmissionUnavailableError,
        InMemoryAIJobDispatcher,
        get_ai_job,
        resume_interrupted_ai_job,
        update_ai_job,
    )

    sessions = async_sessionmaker(runtime, expire_on_commit=False)
    repository = AIGenerationCheckpointRepository()
    plan_key = "dev-live-plan"
    lessons = (
        PlannedLesson("module-1", "lesson-1", 0, 0),
        PlannedLesson("module-1", "lesson-2", 0, 1),
    )
    async with sessions() as session:
        await repository.create_plan(
            session,
            tenant_id=str(tenant_a),
            generation_key=plan_key,
            plan_revision="dev-revision-1",
            source_job_id=job_a,
            plan_payload={"lesson_count": 2},
            lessons=lessons,
        )
        await session.commit()
    checks.append("runtime_plan_created")

    ready = asyncio.Event()
    entered = 0
    enter_lock = asyncio.Lock()

    async def concurrent_claim(owner_name: str):
        nonlocal entered
        async with sessions() as session:
            async with enter_lock:
                entered += 1
                if entered == 2:
                    ready.set()
            await ready.wait()
            claimed = await repository.claim_item(
                session,
                tenant_id=str(tenant_a),
                generation_key=plan_key,
                module_key="module-1",
                lesson_key="lesson-1",
                stage="content",
                lease_owner=owner_name,
                lease_duration_seconds=30,
            )
            await session.commit()
            return claimed

    first, second = await asyncio.gather(
        concurrent_claim("delivery-a"),
        concurrent_claim("delivery-b"),
    )
    winners = [item for item in (first, second) if item is not None]
    assert len(winners) == 1, "concurrent_claim_not_exclusive"
    winning_owner = winners[0].lease_owner
    checks.append("concurrent_claim_exactly_once")

    async with sessions() as session:
        await repository.checkpoint_content(
            session,
            tenant_id=str(tenant_a),
            generation_key=plan_key,
            module_key="module-1",
            lesson_key="lesson-1",
            content_payload={"title": "Lesson 1"},
            lease_owner=winning_owner,
        )
        await session.commit()
    checks.append("owner_guarded_checkpoint")

    async with sessions() as session:
        claimed = await repository.claim_item(
            session,
            tenant_id=str(tenant_a),
            generation_key=plan_key,
            module_key="module-1",
            lesson_key="lesson-2",
            stage="content",
            lease_owner="expired-delivery",
            lease_duration_seconds=1,
        )
        assert claimed is not None, "lease_expiry_setup_failed"
        await session.commit()
    await asyncio.sleep(1.2)
    async with sessions() as session:
        reclaimed = await repository.claim_item(
            session,
            tenant_id=str(tenant_a),
            generation_key=plan_key,
            module_key="module-1",
            lesson_key="lesson-2",
            stage="content",
            lease_owner="replacement-delivery",
            lease_duration_seconds=30,
        )
        assert reclaimed is not None and reclaimed.attempt_count == 2, "expired_lease_not_reclaimed"
        await repository.checkpoint_content(
            session,
            tenant_id=str(tenant_a),
            generation_key=plan_key,
            module_key="module-1",
            lesson_key="lesson-2",
            content_payload={"title": "Lesson 2"},
            lease_owner="replacement-delivery",
        )
        await session.commit()
    checks.append("expired_lease_reclaimed")

    for lesson in lessons:
        async with sessions() as session:
            review = await repository.claim_item(
                session,
                tenant_id=str(tenant_a),
                generation_key=plan_key,
                module_key=lesson.module_key,
                lesson_key=lesson.lesson_key,
                stage="review",
                lease_owner=f"review-{lesson.lesson_key}",
            )
            assert review is not None, "review_claim_failed"
            await repository.checkpoint_review(
                session,
                tenant_id=str(tenant_a),
                generation_key=plan_key,
                module_key=lesson.module_key,
                lesson_key=lesson.lesson_key,
                review_payload={"approved": True},
                lease_owner=review.lease_owner,
            )
            assessment = await repository.claim_item(
                session,
                tenant_id=str(tenant_a),
                generation_key=plan_key,
                module_key=lesson.module_key,
                lesson_key=lesson.lesson_key,
                stage="assessment",
                lease_owner=f"assessment-{lesson.lesson_key}",
            )
            assert assessment is not None, "assessment_claim_failed"
            await repository.checkpoint_assessment(
                session,
                tenant_id=str(tenant_a),
                generation_key=plan_key,
                module_key=lesson.module_key,
                lesson_key=lesson.lesson_key,
                assessment_payload={"questions": [lesson.lesson_key]},
                lease_owner=assessment.lease_owner,
            )
            await session.commit()
    async with sessions() as session:
        await repository.assert_complete(
            session,
            tenant_id=str(tenant_a),
            generation_key=plan_key,
        )
        snapshots = await repository.load_checkpoints(
            session,
            tenant_id=str(tenant_a),
            generation_key=plan_key,
        )
        assert len(snapshots) == 2, "checkpoint_snapshot_count"
    checks.append("all_stages_complete_once")

    async with sessions() as session:
        try:
            await repository.load_plan(
                session,
                tenant_id=str(tenant_b),
                generation_key=plan_key,
            )
        except AIGenerationCheckpointError as exc:
            assert str(exc) == "generation_plan_not_found", "cross_tenant_error_changed"
        else:
            raise AssertionError("cross_tenant_plan_visible")
        await session.rollback()
    async with runtime.connect() as conn:
        count = (await conn.execute(text("SELECT count(*) FROM ai_generation_runs"))).scalar_one()
        assert count == 0, "unset_tenant_rows_visible"
    checks.append("rls_tenant_isolation")

    async with sessions() as session:
        await set_tenant(session, tenant_a)
        try:
            await session.execute(text("DELETE FROM ai_generation_runs"))
        except Exception:
            await session.rollback()
        else:
            raise AssertionError("runtime_delete_allowed")
    checks.append("runtime_delete_denied")

    dispatcher = InMemoryAIJobDispatcher()
    race_ready = asyncio.Event()
    race_entered = 0
    race_lock = asyncio.Lock()

    async def enter_race() -> None:
        nonlocal race_entered
        async with race_lock:
            race_entered += 1
            if race_entered == 2:
                race_ready.set()
        await race_ready.wait()

    async def resume_job_action() -> str:
        await enter_race()
        async with sessions() as session:
            await set_tenant(session, tenant_a)
            job = await get_ai_job(session, resume_job, tenant_id=str(tenant_a))
            assert job is not None, "resume_job_missing"
            try:
                await resume_interrupted_ai_job(
                    session,
                    job=job,
                    tenant_id=tenant_a,
                    task_kwargs={"job_id": resume_job, "tenant_id": str(tenant_a)},
                    active_limit=8,
                    worker_concurrency=2,
                    historical_estimate_seconds=1,
                    dispatcher=dispatcher,
                )
            except AIJobSubmissionUnavailableError:
                await session.rollback()
                return "not_resumable"
            return "resumed"

    async def cancel_job_action() -> str:
        await enter_race()
        async with sessions() as session:
            await set_tenant(session, tenant_a)
            job = await get_ai_job(
                session,
                resume_job,
                tenant_id=str(tenant_a),
                for_update=True,
            )
            assert job is not None, "cancel_job_missing"
            await update_ai_job(
                session,
                resume_job,
                tenant_id=str(tenant_a),
                status="cancelled",
                stage="cancelled",
                message="Cancelled by DEV gate",
                completed_at=datetime.now(UTC),
            )
            await session.commit()
            return "cancelled"

    checks.append("cancel_resume_race_started")
    race_result = await asyncio.gather(resume_job_action(), cancel_job_action())
    checks.append("cancel_resume_race_actions_completed")
    assert "cancelled" in race_result, "cancel_action_missing"
    assert len(dispatcher.submissions) <= 1, "resume_dispatched_twice"
    async with sessions() as session:
        await set_tenant(session, tenant_a)
        final_job = await get_ai_job(session, resume_job, tenant_id=str(tenant_a))
        assert final_job is not None and final_job.status == "cancelled", "cancel_not_terminal"
        checks.append("cancel_state_terminal")
        await update_ai_job(
            session,
            resume_job,
            tenant_id=str(tenant_a),
            status="running",
            stage="content",
        )
        await session.commit()
        checks.append("late_worker_update_attempted")
    async with sessions() as session:
        await set_tenant(session, tenant_a)
        persisted_job = await get_ai_job(session, resume_job, tenant_id=str(tenant_a))
        assert (
            persisted_job is not None and persisted_job.status == "cancelled"
        ), "late_worker_resurrected_cancelled_job"
    checks.append("cancel_resume_race_terminal")

    # Keep imported symbols exercised so accidental contract drift is visible.
    assert issubclass(AIGenerationIncompleteError, AIGenerationCheckpointError)


async def run(env_file: Path, expected_public_revision: str) -> dict[str, Any]:
    logging.disable(logging.CRITICAL)
    config = dotenv_values(env_file)
    owner_url = normalize_database_url(config.get("MIGRATION_DATABASE_URL") or "")
    runtime_url = normalize_database_url(config.get("DATABASE_URL") or "")
    supabase_url = config.get("SUPABASE_URL") or ""
    if not all(same_supabase_project(url, supabase_url) for url in (owner_url, runtime_url)):
        raise ValueError("not_canonical_supabase_dev")
    if make_url(runtime_url).username.split(".")[0] != "lms_app":
        raise ValueError("wrong_runtime_role")
    if any(make_url(url).database != "postgres" for url in (owner_url, runtime_url)):
        raise ValueError("unexpected_database")
    if not re.fullmatch(r"[0-9]{4}", expected_public_revision):
        raise ValueError("invalid_expected_public_revision")

    schema = validate_schema("aicp_dev_" + uuid4().hex[:12])
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
    report: dict[str, Any] = {
        "schema": schema,
        "checks": [],
        "passed": False,
        "cleanup": False,
        "public_revision": expected_public_revision,
    }
    created = False
    before: list[str] | None = None
    try:
        async with runtime.connect() as conn:
            role = (
                await conn.execute(
                    text(
                        "SELECT current_user, rolsuper, rolbypassrls "
                        "FROM pg_roles WHERE rolname=current_user"
                    )
                )
            ).one()
            assert role == ("lms_app", False, False), "runtime_role_not_restricted"
        report["checks"].append("runtime_role_restricted")

        async with owner.begin() as conn:
            before = (
                await conn.execute(
                    text("SELECT version_num FROM public.alembic_version ORDER BY version_num")
                )
            ).scalars().all()
            assert before == [expected_public_revision], "public_revision_mismatch"
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        created = True
        tenant_a, tenant_b, job_a, resume_job = await create_fixture(owner, schema)

        async with owner.begin() as conn:
            for direction in ("upgrade", "downgrade", "upgrade"):
                await conn.run_sync(
                    lambda sync, step=direction: migrate(sync, schema, step)
                )
                run_exists = (
                    await conn.execute(
                        text("SELECT to_regclass(:name) IS NOT NULL"),
                        {"name": f"{schema}.ai_generation_runs"},
                    )
                ).scalar_one()
                checkpoint_exists = (
                    await conn.execute(
                        text("SELECT to_regclass(:name) IS NOT NULL"),
                        {"name": f"{schema}.ai_generation_lesson_checkpoints"},
                    )
                ).scalar_one()
                expected = direction == "upgrade"
                assert run_exists == expected, "run_table_migration_readback"
                assert checkpoint_exists == expected, "checkpoint_table_migration_readback"
        report["checks"].append("migration_upgrade_downgrade_reupgrade")

        async with owner.connect() as conn:
            flags = (
                await conn.execute(
                    text(
                        "SELECT relname, relrowsecurity, relforcerowsecurity "
                        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname=:schema AND relname IN "
                        "('ai_generation_runs','ai_generation_lesson_checkpoints') "
                        "ORDER BY relname"
                    ),
                    {"schema": schema},
                )
            ).all()
            assert len(flags) == 2 and all(row[1:] == (True, True) for row in flags), "rls_force_flags"
            delete_grants = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM information_schema.role_table_grants "
                        "WHERE table_schema=:schema AND grantee='lms_app' "
                        "AND privilege_type='DELETE'"
                    ),
                    {"schema": schema},
                )
            ).scalar_one()
            assert delete_grants == 0, "runtime_delete_grant_present"
        report["checks"].append("rls_force_and_acl")

        os.environ["DATABASE_URL"] = runtime_url
        os.environ["APP_ENV"] = "test"
        os.environ.setdefault("JWT_SECRET", "synthetic-ai-checkpoint-dev-gate-only")
        sys.path.insert(0, str(API))
        await exercise_runtime(
            owner,
            runtime,
            schema,
            tenant_a,
            tenant_b,
            job_a,
            resume_job,
            report["checks"],
        )
        report["passed"] = True
    except Exception as exc:
        report["error_type"] = type(exc).__name__
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
                        await conn.execute(
                            text(
                                "SELECT version_num FROM public.alembic_version ORDER BY version_num"
                            )
                        )
                    ).scalars().all()
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
    parser.add_argument("--expected-public-revision", required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(
            run(
                args.env_file.resolve(strict=True),
                args.expected_public_revision,
            )
        )
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
