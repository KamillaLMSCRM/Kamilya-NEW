#!/usr/bin/env python3
"""Real dashboard reads in an owned Supabase DEV schema, with no public writes."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values, load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import course_publish_dev_gate as isolation
from kb_rag_isolated_dev_gate import GateBlocked, normalize_database_url
from source_actuality_dev_gate import public_snapshot
from workbench_assignment_dev_gate import safe_failure

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/api"))


async def run(values: dict) -> dict:
    # Reuse the canonical isolation/identity/FORCE-RLS/cleanup implementation.
    isolation.TABLES = (
        "tenants",
        "users",
        "user_roles",
        "courses",
        "modules",
        "lessons",
        "enrollments",
        "progress",
        "certificates",
        "recurring_learning_assignments",
        "learning_path_assignments",
        "learning_path_cycle_instances",
        "enrollment_access_policies",
    )
    schema = "publish_" + uuid4().hex[:12]
    (
        owner,
        runtime,
        tenant_a,
        tenant_b,
        user_a,
        user_b,
        _,
        before,
    ) = await isolation.setup(
        normalize_database_url(values.get("MIGRATION_DATABASE_URL") or ""),
        normalize_database_url(values.get("DATABASE_URL") or ""),
        values.get("SUPABASE_URL") or "",
        schema,
    )
    checks = []
    try:
        # Import the existing course router to register the full ORM model graph.
        from app.modules.courses import router as course_router  # noqa: F401
        from app.models.enrollment import Enrollment
        from app.modules.lessons.models import Lesson, Module
        from app.models.progress import Progress
        from app.modules.certificates.models import Certificate
        from app.modules.courses.models import Course
        from app.modules.student.service import get_student_dashboard

        ids = [uuid4(), uuid4(), uuid4()]
        async with AsyncSession(owner, expire_on_commit=False) as db:
            await db.execute(
                text(
                    f"SET LOCAL search_path TO {isolation.qschema(schema)}, pg_catalog"
                )
            )
            for index, enrollment_id in enumerate(ids):
                course_id, module_id, lesson_id = uuid4(), uuid4(), uuid4()
                db.add(
                    Course(
                        id=course_id,
                        tenant_id=tenant_a,
                        title=f"Synthetic dashboard {index}",
                        status="published",
                    )
                )
                db.add(
                    Module(
                        id=module_id,
                        tenant_id=tenant_a,
                        course_id=course_id,
                        title="Synthetic",
                        order_index=0,
                    )
                )
                db.add(
                    Lesson(
                        id=lesson_id,
                        tenant_id=tenant_a,
                        module_id=module_id,
                        title="Synthetic",
                        order_index=0,
                    )
                )
                db.add(
                    Enrollment(
                        id=enrollment_id,
                        tenant_id=tenant_a,
                        user_id=user_a,
                        course_id=course_id,
                        status="completed",
                    )
                )
                # Manual enrollment keeps the existing legacy NULL progress scope.
                db.add(
                    Progress(
                        tenant_id=tenant_a,
                        user_id=user_a,
                        course_id=course_id,
                        lesson_id=lesson_id,
                        completed=True,
                    )
                )
                db.add(
                    Certificate(
                        tenant_id=tenant_a,
                        user_id=user_a,
                        course_id=course_id,
                        enrollment_id=enrollment_id,
                        certificate_number=f"QA-{uuid4().hex}",
                    )
                )
                if index == 0:
                    db.add(
                        Certificate(
                            tenant_id=tenant_a,
                            user_id=user_b,
                            course_id=course_id,
                            enrollment_id=None,
                            certificate_number=f"QA-{uuid4().hex}",
                        )
                    )
                    db.add(
                        Certificate(
                            tenant_id=tenant_b,
                            user_id=user_a,
                            course_id=course_id,
                            enrollment_id=enrollment_id,
                            certificate_number=f"QA-{uuid4().hex}",
                        )
                    )
            await db.commit()
        scenarios = (
            (tenant_a, user_a, None, 3, 3),
            (tenant_a, user_a, ids[0], 1, 1),
            (tenant_a, user_a, ids[1], 1, 1),
            (tenant_b, user_b, ids[0], 0, 0),
        )
        for tenant, user, scope, certificates, courses in scenarios:
            async with AsyncSession(runtime) as db:
                await isolation.context(db, schema, str(tenant))
                result = await get_student_dashboard(
                    db, user, tenant, enrollment_id=scope
                )
                if (
                    result["certificates_count"] != certificates
                    or result["total_courses"] != courses
                ):
                    raise GateBlocked("dashboard_scope_count_mismatch")
                await db.rollback()
            checks.append(
                {
                    "certificates": certificates,
                    "courses": courses,
                    "assignment_scoped": scope is not None,
                    "cross_tenant": tenant == tenant_b,
                }
            )
        async with AsyncSession(runtime) as db:
            await isolation.context(db, schema)
            result = await get_student_dashboard(db, user_a, tenant_a)
            if result["certificates_count"] != 0 or result["total_courses"] != 0:
                raise GateBlocked("empty_tenant_context_not_denied")
            await db.rollback()
        return {
            "status": "PASS",
            "checks": checks,
            "empty_context_denied": True,
            "cleanup": True,
            "public_schema_neutral": True,
            "public_business_writes": 0,
            "runtime_role": "lms_app",
            "schema": schema,
            "scope": "real service and SQL reads; not live HTTP authentication",
        }
    finally:
        try:
            async with owner.begin() as db:
                await db.execute(
                    text(f"DROP SCHEMA IF EXISTS {isolation.qschema(schema)} CASCADE")
                )
                if (
                    await db.scalar(
                        text("SELECT to_regnamespace(:name)"), {"name": schema}
                    )
                    is not None
                ):
                    raise GateBlocked("owned_schema_cleanup_failed")
                if await public_snapshot(db) != before:
                    raise GateBlocked("public_snapshot_changed")
        finally:
            await owner.dispose()
            await runtime.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "BLOCKED", "reason": "execute_required"}))
        return 2
    values = dotenv_values(args.env_file)
    load_dotenv(args.env_file, override=True)
    try:
        print(json.dumps(asyncio.run(run(values)), sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error_class": safe_failure(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
