#!/usr/bin/env python3
"""Bounded keyed-course-publication transaction proof on an owned DEV schema.

This gate never writes public business tables.  It is intentionally narrower
than the publication acceptance suite: release creation is a real owned
``ContentRelease`` insert, while assignment activation is a no-op stub.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from kb_rag_isolated_dev_gate import GateBlocked, same_supabase_project
from source_actuality_dev_gate import public_snapshot, verify_runtime_role
from workbench_assignment_dev_gate import safe_failure

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_RE = re.compile(r"^publish_[0-9a-f]{12}$")
TABLES = (
    "tenants",
    "users",
    "user_roles",
    "courses",
    "workflow_idempotency_keys",
    "content_releases",
    "course_approval_policies",
    "modules",
    "lessons",
    "quizzes",
    "audit_logs",
)


def qschema(value: str) -> str:
    if not SCHEMA_RE.fullmatch(value):
        raise GateBlocked("unsafe_publish_schema")
    return f'"{value}"'


async def context(db: AsyncSession, schema: str, tenant: str = "") -> None:
    await db.execute(text(f"SET LOCAL search_path TO {qschema(schema)}, pg_catalog"))
    await db.execute(
        text(
            "SELECT set_config('app.tenant_id',:tenant,true), set_config('app.is_superadmin','false',true)"
        ),
        {"tenant": tenant},
    )
    for table in TABLES:
        resolved = await db.scalar(
            text(
                "SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE c.oid=to_regclass(:name)"
            ),
            {"name": table},
        )
        if resolved != schema:
            raise GateBlocked("publish_table_resolution")


async def setup(owner_url: str, runtime_url: str, supabase_url: str, schema: str):
    if not all(
        same_supabase_project(url, supabase_url) for url in (owner_url, runtime_url)
    ):
        raise GateBlocked("canonical_dev_identity_mismatch")
    if (make_url(runtime_url).username or "").split(".")[0] != "lms_app":
        raise GateBlocked("wrong_runtime_role")
    if any(make_url(url).database != "postgres" for url in (owner_url, runtime_url)):
        raise GateBlocked("unexpected_database")
    owner = create_async_engine(owner_url, poolclass=NullPool, hide_parameters=True)
    runtime = create_async_engine(runtime_url, poolclass=NullPool, hide_parameters=True)
    created = False
    try:
        async with runtime.connect() as db:
            await verify_runtime_role(db)
        async with owner.begin() as db:
            before = await public_snapshot(db)
            await db.execute(text(f"CREATE SCHEMA {qschema(schema)}"))
            created = True
            await db.execute(
                text(f"REVOKE ALL ON SCHEMA {qschema(schema)} FROM PUBLIC")
            )
            await db.execute(
                text(f"GRANT USAGE ON SCHEMA {qschema(schema)} TO lms_app")
            )
            for table in TABLES:
                await db.execute(
                    text(
                        f"CREATE TABLE {qschema(schema)}.{table} (LIKE public.{table} INCLUDING ALL)"
                    )
                )
                await db.execute(
                    text(
                        f"GRANT SELECT,INSERT,UPDATE,DELETE ON {qschema(schema)}.{table} TO lms_app"
                    )
                )
                await db.execute(
                    text(
                        f"ALTER TABLE {qschema(schema)}.{table} ENABLE ROW LEVEL SECURITY"
                    )
                )
                await db.execute(
                    text(
                        f"ALTER TABLE {qschema(schema)}.{table} FORCE ROW LEVEL SECURITY"
                    )
                )
                tenant_expr = (
                    "id = NULLIF(current_setting('app.tenant_id',true),'')::uuid"
                    if table == "tenants"
                    else "tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid"
                )
                await db.execute(
                    text(
                        f"CREATE POLICY publish_tenant ON {qschema(schema)}.{table} "
                        f"USING ({tenant_expr}) WITH CHECK ({tenant_expr})"
                    )
                )
        # DDL must commit before any second connection seeds the owned tables.
        async with owner.begin() as seed:
            await seed.execute(
                text(f"SET LOCAL search_path TO {qschema(schema)}, pg_catalog")
            )
            tenant_a, tenant_b = uuid4(), uuid4()
            actor_a, actor_b = uuid4(), uuid4()
            await seed.execute(
                text(
                    "INSERT INTO tenants(id,name,slug,status,plan,is_demo,is_financial_organization) VALUES (:a,'Synthetic A','publish-a','active','free',false,false),(:b,'Synthetic B','publish-b','active','free',false,false)"
                ),
                {"a": tenant_a, "b": tenant_b},
            )
            for tenant, actor, email in (
                (tenant_a, actor_a, "methodologist-a@example.invalid"),
                (tenant_b, actor_b, "methodologist-b@example.invalid"),
            ):
                await seed.execute(
                    text(
                        "INSERT INTO users(id,tenant_id,email,first_name,last_name,role,is_active,status) VALUES (:id,:tenant,:email,'Synthetic','Methodologist','methodologist',true,'active')"
                    ),
                    {"id": actor, "tenant": tenant, "email": email},
                )
                await seed.execute(
                    text(
                        "INSERT INTO user_roles(id,tenant_id,user_id,role) VALUES (:id,:tenant,:user,'methodologist')"
                    ),
                    {"id": uuid4(), "tenant": tenant, "user": actor},
                )
        async with owner.begin() as db:
            after = await public_snapshot(db)
            if before != after:
                raise GateBlocked("public_snapshot_changed")
        return owner, runtime, tenant_a, tenant_b, actor_a, actor_b, created, before
    except Exception:
        cleanup_error = None
        if created:
            try:
                async with owner.begin() as cleanup_db:
                    await cleanup_db.execute(
                        text(f"DROP SCHEMA IF EXISTS {qschema(schema)} CASCADE")
                    )
            except Exception as exc:
                cleanup_error = exc
        await owner.dispose()
        await runtime.dispose()
        if cleanup_error is not None:
            raise GateBlocked(
                "setup_cleanup_failed:" + safe_failure(cleanup_error)
            ) from cleanup_error
        raise


async def run(owner_url: str, runtime_url: str, supabase_url: str) -> dict:
    schema = f"publish_{uuid4().hex[:12]}"
    (
        owner,
        runtime,
        tenant_a,
        tenant_b,
        actor_a,
        actor_b,
        created,
        public_before,
    ) = await setup(owner_url, runtime_url, supabase_url, schema)
    try:
        sys.path.insert(0, str(ROOT / "apps" / "api"))
        from fastapi import HTTPException
        from app.models.courses import Course
        from app.models.tenants import Tenant  # noqa: F401 - registers real FK target
        from app.modules.courses import router as course_router
        from app.modules.courses.release_models import ContentRelease
    except Exception:
        async with owner.begin() as db:
            await db.execute(text(f"DROP SCHEMA IF EXISTS {qschema(schema)} CASCADE"))
        await owner.dispose()
        await runtime.dispose()
        raise

    class Request:
        client = None
        headers = {}

    async def fake_release(db, course, *, published_by):
        release = ContentRelease(
            tenant_id=course.tenant_id,
            course_id=course.id,
            version=1,
            snapshot={"course": str(course.id), "stub": True},
            snapshot_sha256="0" * 64,
            published_by=published_by,
        )
        db.add(release)
        await db.flush()
        course.current_release_id = release.id
        return release

    async def no_activation(db, course):
        return None

    original_activation = course_router.activate_course_assignments
    original_refresh = course_router.refresh_course_assignments
    course_router.activate_course_assignments = no_activation
    course_router.refresh_course_assignments = no_activation
    import app.modules.courses.release_service as release_service

    old_release = release_service.create_course_release
    release_service.create_course_release = fake_release
    checks: list[str] = []
    try:
        async with AsyncSession(runtime, expire_on_commit=False) as db:
            await context(db, schema, str(tenant_a))
            course_a = Course(
                tenant_id=tenant_a,
                title="Synthetic publish A",
                description="bounded",
                status="draft",
                created_by=actor_a,
            )
            db.add(course_a)
            await db.flush()
            response = await course_router.publish_course(
                course_a.id, Request(), db, SimpleActor(actor_a, tenant_a), "publish-a"
            )
            if response.status != "published" or response.current_release_id is None:
                raise GateBlocked("publish_response_not_published")
            course_id, release_id = response.id, response.current_release_id
            await db.commit()
        checks.append("keyed_publish_dto_and_atomic_receipt")
        async with AsyncSession(runtime) as db:
            await context(db, schema, str(tenant_a))
            persisted = (
                await db.execute(
                    text("SELECT status,current_release_id FROM courses WHERE id=:id"),
                    {"id": course_id},
                )
            ).one()
            key_count = await db.scalar(
                text(
                    "SELECT count(*) FROM workflow_idempotency_keys WHERE tenant_id=:tenant AND key='publish-a' AND operation='course.publish'"
                ),
                {"tenant": tenant_a},
            )
            release_count = await db.scalar(
                text(
                    "SELECT count(*) FROM content_releases WHERE tenant_id=:tenant AND course_id=:id"
                ),
                {"tenant": tenant_a, "id": course_id},
            )
            audit_count = await db.scalar(
                text(
                    "SELECT count(*) FROM audit_logs WHERE tenant_id=:tenant AND action='publish' AND resource_type='course' AND resource_id=:id"
                ),
                {"tenant": tenant_a, "id": str(course_id)},
            )
            if (
                persisted.status != "published"
                or persisted.current_release_id != release_id
                or key_count != 1
                or release_count != 1
                or audit_count != 1
            ):
                raise GateBlocked("publish_persisted_state_mismatch")
            await db.rollback()
        async with runtime.connect() as connection:
            async with AsyncSession(bind=connection) as db:
                await context(db, schema, str(tenant_a))
                await db.commit()
                await connection.begin()
                await connection.execute(
                    text(f"SET LOCAL search_path TO {qschema(schema)}, pg_catalog")
                )
                tenant_setting = await connection.scalar(
                    text("SELECT current_setting('app.tenant_id',true)")
                )
                if (
                    tenant_setting not in (None, "")
                    or await connection.scalar(text("SELECT count(*) FROM courses"))
                    != 0
                ):
                    raise GateBlocked("same_connection_context_not_cleared")
                await connection.rollback()
        checks.append("same_connection_empty_context_denied")
        async with AsyncSession(runtime, expire_on_commit=False) as db:
            await context(db, schema, str(tenant_a))
            replay = await course_router.publish_course(
                course_id, Request(), db, SimpleActor(actor_a, tenant_a), "publish-a"
            )
            if replay.id != course_id or replay.current_release_id != release_id:
                raise GateBlocked("replay_identity_mismatch")
            if (
                await db.scalar(
                    text("SELECT count(*) FROM content_releases WHERE course_id=:id"),
                    {"id": course_id},
                )
                != 1
            ):
                raise GateBlocked("replay_created_second_release")
            await db.commit()
        checks.append("same_key_replay")
        async with AsyncSession(runtime, expire_on_commit=False) as db:
            await context(db, schema, str(tenant_a))
            course_b = Course(
                tenant_id=tenant_a,
                title="Synthetic publish B",
                description="bounded",
                status="draft",
                created_by=actor_a,
            )
            db.add(course_b)
            await db.flush()
            course_b_id = course_b.id
            await db.commit()
        async with AsyncSession(runtime, expire_on_commit=False) as db:
            await context(db, schema, str(tenant_a))
            try:
                await course_router.publish_course(
                    course_b_id,
                    Request(),
                    db,
                    SimpleActor(actor_a, tenant_a),
                    "publish-a",
                )
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise GateBlocked("same_key_conflict_status") from exc
                await db.rollback()
            else:
                raise GateBlocked("same_key_different_course_allowed")
        async with AsyncSession(runtime) as db:
            await context(db, schema, str(tenant_a))
            if (
                await db.scalar(
                    text("SELECT status FROM courses WHERE title='Synthetic publish B'")
                )
                != "draft"
            ):
                raise GateBlocked("conflicting_course_mutated")
            if (
                await db.scalar(
                    text(
                        "SELECT count(*) FROM content_releases WHERE course_id IN (SELECT id FROM courses WHERE title='Synthetic publish B')"
                    )
                )
                != 0
            ):
                raise GateBlocked("conflicting_course_release_created")
            await db.rollback()
        checks.append("same_key_different_course_rollback")
        async with AsyncSession(runtime, expire_on_commit=False) as db:
            await context(db, schema, str(tenant_b))
            try:
                await course_router.publish_course(
                    course_id,
                    Request(),
                    db,
                    SimpleActor(actor_b, tenant_b),
                    "publish-a",
                )
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise GateBlocked("cross_tenant_status") from exc
                await db.rollback()
            else:
                raise GateBlocked("cross_tenant_publish_not_denied")
        checks.append("cross_tenant_denied")
        async with AsyncSession(runtime, expire_on_commit=False) as db:
            await context(db, schema, str(tenant_a))
            course_c = Course(
                tenant_id=tenant_a,
                title="Synthetic publish C",
                description="bounded",
                status="draft",
                created_by=actor_a,
            )
            db.add(course_c)
            await db.flush()
            course_c_id = course_c.id
            await db.commit()
        async with AsyncSession(runtime, expire_on_commit=False) as db:
            await context(db, schema, str(tenant_a))
            original_commit = db.commit

            async def failing_commit():
                raise RuntimeError("injected_commit_failure")

            db.commit = failing_commit
            try:
                await course_router.publish_course(
                    course_c_id,
                    Request(),
                    db,
                    SimpleActor(actor_a, tenant_a),
                    "publish-c",
                )
            except RuntimeError:
                await db.rollback()
            else:
                raise GateBlocked("injected_commit_failure_not_observed")
            finally:
                db.commit = original_commit
        async with AsyncSession(runtime) as db:
            await context(db, schema, str(tenant_a))
            state = await db.execute(
                text(
                    "SELECT status,current_release_id FROM courses WHERE title='Synthetic publish C'"
                )
            )
            row = state.one()
            key_count = await db.scalar(
                text(
                    "SELECT count(*) FROM workflow_idempotency_keys WHERE key='publish-c'"
                )
            )
            release_count = await db.scalar(
                text(
                    "SELECT count(*) FROM content_releases WHERE course_id=(SELECT id FROM courses WHERE title='Synthetic publish C')"
                )
            )
            if (
                row.status != "draft"
                or row.current_release_id is not None
                or key_count != 0
                or release_count != 0
            ):
                raise GateBlocked("commit_failure_not_atomic")
            await db.rollback()
        checks.append("final_commit_failure_rollback")
        async with AsyncSession(runtime, expire_on_commit=False) as db:
            await context(db, schema, str(tenant_a))
            original_commit = db.commit
            db.commit = failing_commit
            try:
                await course_router.unpublish_course(
                    course_id,
                    Request(),
                    db,
                    SimpleActor(actor_a, tenant_a),
                    "unpublish-fail",
                )
            except RuntimeError as exc:
                if str(exc) != "injected_commit_failure":
                    raise GateBlocked("unexpected_unpublish_failure") from exc
                await db.rollback()
            else:
                raise GateBlocked("unpublish_commit_failure_not_observed")
            finally:
                db.commit = original_commit
        async with AsyncSession(runtime) as db:
            await context(db, schema, str(tenant_a))
            if (
                await db.scalar(
                    text("SELECT status FROM courses WHERE id=:id"), {"id": course_id}
                )
                != "published"
            ):
                raise GateBlocked("unpublish_failure_not_atomic")
            if (
                await db.scalar(
                    text(
                        "SELECT count(*) FROM workflow_idempotency_keys WHERE key='unpublish-fail'"
                    )
                )
                != 0
            ):
                raise GateBlocked("unpublish_failure_receipt_committed")
            if (
                await db.scalar(
                    text("SELECT count(*) FROM audit_logs WHERE action='unpublish'")
                )
                != 0
            ):
                raise GateBlocked("unpublish_failure_audit_committed")
            await db.rollback()
        checks.append("unpublish_commit_failure_rollback")
        async with AsyncSession(runtime, expire_on_commit=False) as db:
            await context(db, schema, str(tenant_a))
            response = await course_router.unpublish_course(
                course_id, Request(), db, SimpleActor(actor_a, tenant_a), "unpublish-a"
            )
            if (
                response.id != course_id
                or response.status != "draft"
                or response.published_at is not None
            ):
                raise GateBlocked("unpublish_response_mismatch")
        async with AsyncSession(runtime, expire_on_commit=False) as db:
            await context(db, schema, str(tenant_a))
            response = await course_router.unpublish_course(
                course_id, Request(), db, SimpleActor(actor_a, tenant_a), "unpublish-a"
            )
            if response.id != course_id or response.status != "draft":
                raise GateBlocked("unpublish_replay_mismatch")
            if (
                await db.scalar(
                    text(
                        "SELECT count(*) FROM workflow_idempotency_keys WHERE operation='course.unpublish'"
                    )
                )
                != 1
            ):
                raise GateBlocked("unpublish_receipt_count")
            if (
                await db.scalar(
                    text("SELECT count(*) FROM audit_logs WHERE action='unpublish'")
                )
                != 1
            ):
                raise GateBlocked("unpublish_replay_duplicate_audit")
            if (
                await db.scalar(
                    text("SELECT count(*) FROM content_releases WHERE course_id=:id"),
                    {"id": course_id},
                )
                != 1
            ):
                raise GateBlocked("unpublish_altered_release_count")
            await db.rollback()
        checks.append("unpublish_atomic_receipt_and_replay")
        async with AsyncSession(runtime, expire_on_commit=False) as db:
            await context(db, schema, str(tenant_a))
            try:
                await course_router.unpublish_course(
                    course_b_id,
                    Request(),
                    db,
                    SimpleActor(actor_a, tenant_a),
                    "unpublish-a",
                )
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise GateBlocked("unpublish_key_conflict_status") from exc
                await db.rollback()
            else:
                raise GateBlocked("unpublish_key_conflict_allowed")
        checks.append("unpublish_same_key_different_course_denied")
        async with AsyncSession(runtime, expire_on_commit=False) as db:
            await context(db, schema, str(tenant_a))
            concurrent_course = Course(
                tenant_id=tenant_a,
                title="Synthetic concurrent",
                description="bounded",
                status="draft",
                created_by=actor_a,
            )
            db.add(concurrent_course)
            await db.flush()
            concurrent_id = concurrent_course.id
            await db.commit()

        async def concurrent_operation(operation, key):
            async with AsyncSession(runtime, expire_on_commit=False) as db:
                await context(db, schema, str(tenant_a))
                return await operation(
                    concurrent_id, Request(), db, SimpleActor(actor_a, tenant_a), key
                )

        responses = await asyncio.gather(
            *(
                concurrent_operation(course_router.publish_course, "publish-concurrent")
                for _ in range(2)
            )
        )
        if (
            any(row.status != "published" for row in responses)
            or responses[0].current_release_id != responses[1].current_release_id
        ):
            raise GateBlocked("concurrent_publish_response_mismatch")
        responses = await asyncio.gather(
            *(
                concurrent_operation(
                    course_router.unpublish_course, "unpublish-concurrent"
                )
                for _ in range(2)
            )
        )
        if any(row.status != "draft" for row in responses):
            raise GateBlocked("concurrent_unpublish_response_mismatch")
        async with AsyncSession(runtime) as db:
            await context(db, schema, str(tenant_a))
            for operation, key, action in (
                ("course.publish", "publish-concurrent", "publish"),
                ("course.unpublish", "unpublish-concurrent", "unpublish"),
            ):
                if (
                    await db.scalar(
                        text(
                            "SELECT count(*) FROM workflow_idempotency_keys WHERE operation=:operation AND key=:key"
                        ),
                        {"operation": operation, "key": key},
                    )
                    != 1
                ):
                    raise GateBlocked("concurrent_receipt_count")
                if (
                    await db.scalar(
                        text(
                            "SELECT count(*) FROM audit_logs WHERE action=:action AND resource_id=:id"
                        ),
                        {"action": action, "id": str(concurrent_id)},
                    )
                    != 1
                ):
                    raise GateBlocked("concurrent_audit_count")
            if (
                await db.scalar(
                    text("SELECT count(*) FROM content_releases WHERE course_id=:id"),
                    {"id": concurrent_id},
                )
                != 1
            ):
                raise GateBlocked("concurrent_release_count")
            await db.rollback()
        checks.append("concurrent_publish_unpublish_exactly_once")
        # The finally block verifies both claims before this result can escape.
        return {
            "status": "PASS",
            "schema": schema,
            "checks": checks,
            "cleanup": True,
            "public_schema_neutral": True,
            "stubs": [
                "release_snapshot_construction",
                "assignment_activation",
                "assignment_refresh",
            ],
            "live_http_or_complete_publication_pipeline": "NOT_VERIFIED",
        }
    finally:
        release_service.create_course_release = old_release
        course_router.activate_course_assignments = original_activation
        course_router.refresh_course_assignments = original_refresh
        cleanup_error = None
        try:
            async with owner.begin() as db:
                await db.execute(
                    text(f"DROP SCHEMA IF EXISTS {qschema(schema)} CASCADE")
                )
                if (
                    await db.scalar(
                        text("SELECT to_regnamespace(:schema)"), {"schema": schema}
                    )
                    is not None
                ):
                    raise GateBlocked("cleanup_schema_still_exists")
                if await public_snapshot(db) != public_before:
                    raise GateBlocked("public_snapshot_changed_after_gate")
        except Exception as exc:
            cleanup_error = exc
        await owner.dispose()
        await runtime.dispose()
        if cleanup_error is not None:
            original = sys.exc_info()[1]
            original_class = type(original).__name__ if original is not None else "none"
            raise GateBlocked(
                "cleanup_failed:"
                + safe_failure(cleanup_error)
                + ":original:"
                + original_class
            ) from cleanup_error


class SimpleActor:
    def __init__(self, actor_id, tenant_id):
        self.id = actor_id
        self.tenant_id = tenant_id
        self.role = "methodologist"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "BLOCKED", "reason": "execute_required"}))
        return 2
    values = dotenv_values(args.env_file)
    from dotenv import load_dotenv

    load_dotenv(args.env_file, override=True)
    from kb_rag_isolated_dev_gate import normalize_database_url

    try:
        owner_url = normalize_database_url(values.get("MIGRATION_DATABASE_URL") or "")
        runtime_url = normalize_database_url(values.get("DATABASE_URL") or "")
        result = asyncio.run(
            run(owner_url, runtime_url, values.get("SUPABASE_URL") or "")
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error_class": safe_failure(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
