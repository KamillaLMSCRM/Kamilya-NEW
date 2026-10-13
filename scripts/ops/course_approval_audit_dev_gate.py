#!/usr/bin/env python3
"""Actual approval GETs/SQL in an owned DEV schema; no public business writes.

JWT identity is replaced by bound synthetic principals. This gate proves the
actual route/dependency/SQL/RLS path, not deployed login or public-schema policies.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from dotenv import dotenv_values, load_dotenv
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import course_publish_dev_gate as isolation
from kb_rag_isolated_dev_gate import GateBlocked, normalize_database_url
from source_actuality_dev_gate import public_snapshot
from workbench_assignment_dev_gate import safe_failure

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/api"))
TABLES = ("tenants", "users", "user_roles", "courses", "course_approval_policies",
          "course_approval_requests", "course_approval_revisions", "course_approval_reviewers",
          "workflow_work_items", "workflow_deliveries", "course_review_attempts")


async def run(values: dict) -> dict:
    original_tables = isolation.TABLES
    isolation.TABLES = TABLES
    schema = "publish_" + uuid4().hex[:12]
    try:
        owner, runtime, ta, tb, ua, ub, _, before = await isolation.setup(
            normalize_database_url(values.get("MIGRATION_DATABASE_URL") or ""),
            normalize_database_url(values.get("DATABASE_URL") or ""),
            values.get("SUPABASE_URL") or "", schema)
    except BaseException:
        isolation.TABLES = original_tables
        raise
    checks = []
    try:
        from app.core.auth import get_current_active_user
        from app.core.db import get_db
        from app.modules.course_approval.router import router

        ca, ca2, cb, ra, rb, va, vb = [uuid4() for _ in range(7)]
        async with owner.begin() as db:
            await db.execute(text(f"SET LOCAL search_path TO {isolation.qschema(schema)}, pg_catalog"))
            for tid, cid, title in [(ta, ca, "Synthetic A"), (ta, ca2, "Synthetic A unconfigured"), (tb, cb, "Synthetic B")]:
                await db.execute(text("INSERT INTO courses(id,tenant_id,title,status) VALUES(:id,:tenant,:title,'draft')"), {"id": cid, "tenant": tid, "title": title})
            for tid, cid, required in [(ta, ca, True), (tb, cb, False)]:
                await db.execute(text("INSERT INTO course_approval_policies(id,tenant_id,course_id,requires_approval) VALUES(:id,:tenant,:course,:required)"), {"id": uuid4(), "tenant": tid, "course": cid, "required": required})
            for tid, cid, rid, vid in [(ta, ca, ra, va), (tb, cb, rb, vb)]:
                await db.execute(text("INSERT INTO course_approval_revisions(id,tenant_id,course_id,revision_number,snapshot,snapshot_sha256,source_fingerprint) VALUES(:id,:tenant,:course,1,'{}',:sha,:sha)"), {"id": vid, "tenant": tid, "course": cid, "sha": "0" * 64})
                await db.execute(text("INSERT INTO course_approval_requests(id,tenant_id,revision_id,delivery_mode) VALUES(:id,:tenant,:revision,'personal_link')"), {"id": rid, "tenant": tid, "revision": vid})

        async def read(path, tenant, actor, role, context_tenant):
            app = FastAPI()
            app.include_router(router, prefix="/v1")

            async def principal():
                return SimpleNamespace(id=actor, tenant_id=tenant, role=role, is_active=True, roles=["admin", "methodologist"])

            async def database():
                async with AsyncSession(runtime) as session:
                    await isolation.context(session, schema, str(context_tenant) if context_tenant else "")
                    yield session
                    await session.rollback()

            app.dependency_overrides[get_current_active_user] = principal
            app.dependency_overrides[get_db] = database
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                return await client.get(path)

        for tenant, actor, course_ids, request_id in [(ta, ua, {str(ca), str(ca2)}, str(ra)), (tb, ub, {str(cb)}, str(rb))]:
            for role in ("admin", "methodologist"):
                response = await read("/v1/course-approval-courses", tenant, actor, role, tenant)
                rows = response.json()
                if response.status_code != 200 or {row["id"] for row in rows} != course_ids or any(set(row) != {"id", "title", "requires_approval"} for row in rows):
                    raise GateBlocked("catalog_metadata_or_tenant_mismatch")
                policies = {row["id"]: row["requires_approval"] for row in rows}
                expected = {str(ca): True, str(ca2): False} if tenant == ta else {str(cb): False}
                if policies != expected:
                    raise GateBlocked("policy_projection_mismatch")
                response = await read("/v1/course-approval-requests", tenant, actor, role, tenant)
                if response.status_code != 200 or [row["request_id"] for row in response.json()] != [request_id]:
                    raise GateBlocked("history_tenant_mismatch")
                checks.append(f"{role}_{'a' if tenant == ta else 'b'}_metadata_history")
        for context_tenant, name in [(None, "empty"), (tb, "foreign")]:
            for path in ("/v1/course-approval-courses", "/v1/course-approval-requests"):
                response = await read(path, ta, ua, "admin", context_tenant)
                if response.status_code != 200 or response.json() != []:
                    raise GateBlocked("tenant_context_not_fail_closed")
            checks.append(name + "_context_denies_a")
        for role in ("student", "superadmin", "teacher", "org_admin"):
            for path in ("/v1/course-approval-courses", "/v1/course-approval-requests"):
                if (await read(path, ta, ua, role, ta)).status_code != 403:
                    raise GateBlocked("active_role_permission_mismatch")
            checks.append(role + "_denied")
        return {"status": "PASS", "schema": schema, "checks": checks,
                "runtime_role": "lms_app", "force_rls": True, "cleanup": True,
                "public_schema_neutral": True, "public_business_writes": 0,
                "scope": "Actual GET routes/permissions and owned-schema SQL/RLS; JWT/deployed login not verified"}
    finally:
        try:
            async with owner.begin() as db:
                await db.execute(text(f"DROP SCHEMA IF EXISTS {isolation.qschema(schema)} CASCADE"))
                if await db.scalar(text("SELECT to_regnamespace(:schema)"), {"schema": schema}) is not None:
                    raise GateBlocked("owned_schema_cleanup_failed")
                if await public_snapshot(db) != before:
                    raise GateBlocked("public_snapshot_changed")
        finally:
            isolation.TABLES = original_tables
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
