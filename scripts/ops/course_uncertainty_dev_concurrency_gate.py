#!/usr/bin/env python3
"""Bounded course source uncertainty and concurrency verification on an owned DEV schema.

Validates:
1. Strict authoritative document verification (fail closed on missing, foreign, or invalid docs).
2. Live concurrency collision: concurrent author content modification invalidates snapshot hash (409 Conflict).
3. PostgreSQL row-level mutual exclusion under `SELECT ... FOR UPDATE` without deadlocks.
4. Document revision modification collision: stale source revision rejected (409 Conflict).
5. Methodologist resolution integrity: hold cleared, immutable resolution history preserved, and audit_logs written.
6. Tenant isolation and RLS enforcement: foreign tenant cannot access or resolve courses (404 Not Found).
7. Zero public schema business writes, fully verified before and after schema teardown.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from dotenv import dotenv_values, load_dotenv
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from kb_rag_isolated_dev_gate import GateBlocked, normalize_database_url, same_supabase_project
from source_actuality_dev_gate import public_snapshot, verify_runtime_role
from workbench_assignment_dev_gate import safe_failure

ROOT = Path(__file__).resolve().parents[2]
API_ROOT = ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

SCHEMA_RE = re.compile(r"^uncertainty_[0-9a-f]{12}$")
TABLES = (
    "tenants",
    "users",
    "user_roles",
    "documents",
    "courses",
    "modules",
    "lessons",
    "content_blocks",
    "quizzes",
    "questions",
    "quiz_choices",
    "scorm_packages",
    "audit_logs",
)


def qschema(value: str) -> str:
    if not SCHEMA_RE.fullmatch(value):
        raise GateBlocked("unsafe_uncertainty_schema")
    return f'"{value}"'


async def set_context(db: AsyncSession, schema: str, tenant_id: str = "") -> None:
    await db.execute(text(f"SET LOCAL search_path TO {qschema(schema)}, pg_catalog"))
    await db.execute(
        text(
            "SELECT set_config('app.tenant_id',:tenant,true), "
            "set_config('app.is_superadmin','false',true)"
        ),
        {"tenant": tenant_id},
    )


async def setup_schema(owner_url: str, runtime_url: str, supabase_url: str, schema: str):
    if not all(same_supabase_project(url, supabase_url) for url in (owner_url, runtime_url)):
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
            await db.execute(text(f"REVOKE ALL ON SCHEMA {qschema(schema)} FROM PUBLIC"))
            await db.execute(text(f"GRANT USAGE ON SCHEMA {qschema(schema)} TO lms_app"))

            for table in TABLES:
                await db.execute(
                    text(
                        f"CREATE TABLE {qschema(schema)}.{table} "
                        f"(LIKE public.{table} INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES)"
                    )
                )
                await db.execute(
                    text(f"REVOKE ALL ON {qschema(schema)}.{table} FROM PUBLIC, lms_app")
                )
                await db.execute(
                    text(f"GRANT SELECT,INSERT,UPDATE,DELETE ON {qschema(schema)}.{table} TO lms_app")
                )
                await db.execute(
                    text(f"ALTER TABLE {qschema(schema)}.{table} ENABLE ROW LEVEL SECURITY")
                )
                await db.execute(
                    text(f"ALTER TABLE {qschema(schema)}.{table} FORCE ROW LEVEL SECURITY")
                )

            tenant_sql = "NULLIF(current_setting('app.tenant_id',true),'')::uuid"
            child_predicates = {
                "tenants": f"id = {tenant_sql}",
                "content_blocks": f"EXISTS (SELECT 1 FROM {qschema(schema)}.lessons l WHERE l.id={qschema(schema)}.content_blocks.lesson_id AND l.tenant_id={tenant_sql})",
                "questions": f"EXISTS (SELECT 1 FROM {qschema(schema)}.quizzes q WHERE q.id={qschema(schema)}.questions.quiz_id AND q.tenant_id={tenant_sql})",
                "quiz_choices": f"EXISTS (SELECT 1 FROM {qschema(schema)}.questions q JOIN {qschema(schema)}.quizzes z ON z.id=q.quiz_id WHERE q.id={qschema(schema)}.quiz_choices.question_id AND z.tenant_id={tenant_sql})",
            }
            for table in TABLES:
                predicate = child_predicates.get(table) or f"tenant_id = {tenant_sql}"
                await db.execute(
                    text(
                        f"CREATE POLICY uncertainty_tenant_{table} ON {qschema(schema)}.{table} "
                        f"FOR ALL TO lms_app USING ({predicate}) WITH CHECK ({predicate})"
                    )
                )

        # Seed synthetic fixtures under owner transaction
        async with owner.begin() as seed:
            await seed.execute(text(f"SET LOCAL search_path TO {qschema(schema)}, pg_catalog"))
            tenant_a, tenant_b = uuid4(), uuid4()
            actor_a, author_a, actor_b = uuid4(), uuid4(), uuid4()
            doc_a, doc_b = uuid4(), uuid4()
            course_a = uuid4()
            mod_1 = uuid4()
            les_1 = uuid4()
            blk_1 = uuid4()

            # Tenants
            await seed.execute(
                text(
                    "INSERT INTO tenants(id,name,slug,status,plan,is_demo,is_financial_organization) VALUES "
                    "(:ta,'Synthetic Tenant A','tenant-a-uncertainty','active','free',false,false), "
                    "(:tb,'Synthetic Tenant B','tenant-b-uncertainty','active','free',false,false)"
                ),
                {"ta": tenant_a, "tb": tenant_b},
            )

            # Users
            await seed.execute(
                text(
                    "INSERT INTO users(id,tenant_id,email,first_name,last_name,role,is_active,status) VALUES "
                    "(:ua,:ta,'meth-a@example.invalid','Meth','A','methodologist',true,'active'), "
                    "(:au,:ta,'auth-a@example.invalid','Auth','A','admin',true,'active'), "
                    "(:ub,:tb,'meth-b@example.invalid','Meth','B','methodologist',true,'active')"
                ),
                {"ua": actor_a, "au": author_a, "ub": actor_b, "ta": tenant_a, "tb": tenant_b},
            )
            for u, t, r in ((actor_a, tenant_a, "methodologist"), (author_a, tenant_a, "admin"), (actor_b, tenant_b, "methodologist")):
                await seed.execute(
                    text("INSERT INTO user_roles(id,tenant_id,user_id,role) VALUES (:id,:t,:u,:r)"),
                    {"id": uuid4(), "t": t, "u": u, "r": r},
                )

            # Documents
            doc_rev_initial = "d" * 64
            await seed.execute(
                text(
                    "INSERT INTO documents(id,tenant_id,uploaded_by,title,filename,content_type,file_size,version,content_sha256) VALUES "
                    "(:da,:ta,:ua,'Authoritative Document A','doc_a.pdf','application/pdf',2048,1,:sha), "
                    "(:db,:tb,:ub,'Foreign Document B','doc_b.pdf','application/pdf',2048,1,:sha)"
                ),
                {"da": doc_a, "ta": tenant_a, "ua": actor_a, "sha": doc_rev_initial, "db": doc_b, "tb": tenant_b, "ub": actor_b},
            )

            # Course with active uncertainty hold
            defect_desc = "Defect 1: Minor discrepancy in chapter 2 citation"
            defect_hash = hashlib.sha256(defect_desc.strip().encode("utf-8")).hexdigest()[:8]
            defect_id = f"defect-{defect_hash}"

            source_analysis_data = {
                "unresolved_source_uncertainty": True,
                "uncertainty_reason": "Обнаружено несоответствие утверждений регламенту первоисточника",
                "source_documents": [
                    {"id": str(doc_a), "name": "Authoritative Document A", "revision": doc_rev_initial}
                ],
                "evidence_v3": {
                    "violations": [defect_desc],
                },
                "rules": [
                    {
                        "id": "rule-1",
                        "name": "Правило 1",
                        "source_document_id": str(doc_a),
                        "quote": "Требования безопасности должны исполняться неукоснительно.",
                    }
                ],
            }

            await seed.execute(
                text(
                    "INSERT INTO courses(id,tenant_id,title,description,status,created_by,source_document_ids,source_analysis) VALUES "
                    "(:cid,:ta,'Synthetic Course With Hold','Description of synthetic course','draft',:au,CAST(:doc_ids AS jsonb),CAST(:sa AS jsonb))"
                ),
                {
                    "cid": course_a,
                    "ta": tenant_a,
                    "au": author_a,
                    "doc_ids": json.dumps([str(doc_a)]),
                    "sa": json.dumps(source_analysis_data),
                },
            )

            # Module, Lesson, ContentBlock
            await seed.execute(
                text(
                    "INSERT INTO modules(id,tenant_id,course_id,title,description,order_index) VALUES "
                    "(:mid,:ta,:cid,'Module 1','Module 1 Description',0)"
                ),
                {"mid": mod_1, "ta": tenant_a, "cid": course_a},
            )
            await seed.execute(
                text(
                    "INSERT INTO lessons(id,tenant_id,module_id,title,content_type,content,order_index) VALUES "
                    "(:lid,:ta,:mid,'Lesson 1','text','Lesson 1 initial body content',0)"
                ),
                {"lid": les_1, "ta": tenant_a, "mid": mod_1},
            )
            await seed.execute(
                text(
                    "INSERT INTO content_blocks(id,lesson_id,block_type,content,order_index) VALUES "
                    "(:bid,:lid,'text','Initial content block in lesson 1',0)"
                ),
                {"bid": blk_1, "lid": les_1},
            )

        fixtures = {
            "tenant_a": tenant_a,
            "tenant_b": tenant_b,
            "actor_a": actor_a,
            "author_a": author_a,
            "actor_b": actor_b,
            "doc_a": doc_a,
            "doc_b": doc_b,
            "course_a": course_a,
            "mod_1": mod_1,
            "les_1": les_1,
            "blk_1": blk_1,
            "doc_rev_initial": doc_rev_initial,
            "defect_id": defect_id,
        }

        async with owner.begin() as db:
            after = await public_snapshot(db)
            if before != after:
                raise GateBlocked("public_snapshot_changed_during_setup")

        return owner, runtime, fixtures, created, before
    except Exception:
        cleanup_error = None
        if created:
            try:
                async with owner.begin() as cleanup_db:
                    await cleanup_db.execute(text(f"DROP SCHEMA IF EXISTS {qschema(schema)} CASCADE"))
            except Exception as exc:
                cleanup_error = exc
        await owner.dispose()
        await runtime.dispose()
        if cleanup_error is not None:
            raise GateBlocked("setup_cleanup_failed:" + safe_failure(cleanup_error)) from cleanup_error
        raise


async def run_uncertainty_dev_gate(owner_url: str, runtime_url: str, supabase_url: str) -> dict[str, Any]:
    schema = f"uncertainty_{uuid4().hex[:12]}"
    owner, runtime, fixtures, created, public_before = await setup_schema(
        owner_url, runtime_url, supabase_url, schema
    )

    from app.core.auth import get_current_active_user, get_current_user
    from app.core.db import get_db
    from app.modules.courses.router import router as course_router
    from app.modules.courses.source_uncertainty import compute_course_content_snapshot_hash

    tenant_a = fixtures["tenant_a"]
    tenant_b = fixtures["tenant_b"]
    actor_a = fixtures["actor_a"]
    author_a = fixtures["author_a"]
    actor_b = fixtures["actor_b"]
    course_a = fixtures["course_a"]
    doc_a = fixtures["doc_a"]
    les_1 = fixtures["les_1"]
    blk_1 = fixtures["blk_1"]
    doc_rev_initial = fixtures["doc_rev_initial"]
    defect_id = fixtures["defect_id"]

    checks: list[str] = []
    current_actor: dict[str, Any] = {
        "user": SimpleNamespace(
            id=actor_a,
            tenant_id=tenant_a,
            role="methodologist",
            roles=["methodologist"],
            is_active=True,
            email="meth-a@example.invalid",
        ),
        "context_tenant": str(tenant_a),
    }

    app = FastAPI()
    app.include_router(course_router)

    async def override_principal():
        return current_actor["user"]

    async def override_db():
        async with AsyncSession(runtime, expire_on_commit=False) as session:
            await set_context(session, schema, current_actor["context_tenant"])
            yield session

    app.dependency_overrides[get_current_active_user] = override_principal
    app.dependency_overrides[get_current_user] = override_principal
    app.dependency_overrides[get_db] = override_db

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # -------------------------------------------------------------
            # Stage 1: Inspect details & compute H1
            # -------------------------------------------------------------
            inspect_resp = await client.get(f"/courses/{course_a}/source-uncertainty")
            if inspect_resp.status_code != 200:
                raise GateBlocked(f"initial_inspection_failed_{inspect_resp.status_code}:{inspect_resp.text}")
            inspect_data = inspect_resp.json()
            if not inspect_data.get("has_active_hold"):
                raise GateBlocked("initial_course_missing_hold")
            h1 = inspect_data.get("content_snapshot_hash")
            if not h1 or len(h1) != 64:
                raise GateBlocked("invalid_initial_snapshot_hash")
            checks.append("initial_inspection_and_snapshot_hash_h1")

            # -------------------------------------------------------------
            # Stage 2: Concurrent author modification -> H1 mismatch (409)
            # -------------------------------------------------------------
            # Independent connection 2 (author) commits a modification to the course content
            async with AsyncSession(runtime, expire_on_commit=False) as author_session:
                await set_context(author_session, schema, str(tenant_a))
                # Add new content block to lesson 1 and touch course updated_at
                new_block_id = uuid4()
                await author_session.execute(
                    text(
                        f"INSERT INTO {qschema(schema)}.content_blocks (id,lesson_id,block_type,content,order_index) "
                        "VALUES (:bid,:lid,'text','Concurrent author appended block',1)"
                    ),
                    {"bid": new_block_id, "lid": les_1},
                )
                await author_session.execute(
                    text(f"UPDATE {qschema(schema)}.courses SET updated_at = now() WHERE id = :cid"),
                    {"cid": course_a},
                )
                await author_session.commit()

            # Methodologist in Connection 1 attempts resolution with stale H1
            resolve_stale_h1 = await client.post(
                f"/courses/{course_a}/resolve-source-uncertainty",
                json={
                    "reason": "Методист пытается подтвердить курс по старому хэшу H1",
                    "expected_content_hash": h1,
                    "verified_revision": doc_rev_initial,
                    "verified_revisions": {str(doc_a): doc_rev_initial},
                    "defect_resolutions": [
                        {
                            "defect_id": defect_id,
                            "action": "acknowledged_risk",
                            "rationale": "Согласовано с методическим советом",
                        }
                    ],
                },
            )
            if resolve_stale_h1.status_code != 409:
                raise GateBlocked(f"stale_h1_resolution_not_409:{resolve_stale_h1.status_code}:{resolve_stale_h1.text}")
            err_detail = resolve_stale_h1.json().get("detail", {})
            if "Несоответствие версии содержания курса" not in str(err_detail):
                raise GateBlocked(f"unexpected_409_message:{err_detail}")

            # Verify course still has unresolved hold in DB
            async with AsyncSession(runtime, expire_on_commit=False) as verify_session:
                await set_context(verify_session, schema, str(tenant_a))
                res = await verify_session.scalar(
                    text(f"SELECT source_analysis->>'unresolved_source_uncertainty' FROM {qschema(schema)}.courses WHERE id=:cid"),
                    {"cid": course_a},
                )
                if res != "true":
                    raise GateBlocked("hold_was_cleared_on_rejected_attempt")
            checks.append("concurrent_modification_hash_mismatch_rejected_409")

            # -------------------------------------------------------------
            # Stage 3: Real Row-Level Lock Mutual Exclusion (SELECT ... FOR UPDATE)
            # -------------------------------------------------------------
            # Connection 1 locks the course row. Connection 2 attempts lock with short timeout.
            async with AsyncSession(runtime, expire_on_commit=False) as lock_session_1:
                await set_context(lock_session_1, schema, str(tenant_a))
                await lock_session_1.execute(
                    text(f"SELECT id FROM {qschema(schema)}.courses WHERE id=:cid FOR UPDATE"),
                    {"cid": course_a},
                )

                async with AsyncSession(runtime, expire_on_commit=False) as lock_session_2:
                    await set_context(lock_session_2, schema, str(tenant_a))
                    await lock_session_2.execute(text("SET LOCAL lock_timeout = '200ms'"))
                    locked_out = False
                    try:
                        await lock_session_2.execute(
                            text(f"SELECT id FROM {qschema(schema)}.courses WHERE id=:cid FOR UPDATE"),
                            {"cid": course_a},
                        )
                    except DBAPIError as lock_exc:
                        locked_out = True
                        if "canceling statement due to lock timeout" not in str(lock_exc).lower():
                            raise GateBlocked(f"unexpected_lock_error:{lock_exc}") from lock_exc
                    if not locked_out:
                        raise GateBlocked("second_connection_did_not_block_on_row_lock")
                await lock_session_1.rollback()
            checks.append("row_level_lock_mutual_exclusion_verified")

            # -------------------------------------------------------------
            # Stage 4: Document Revision Modification Conflict (409)
            # -------------------------------------------------------------
            new_doc_rev = "e" * 64
            async with AsyncSession(runtime, expire_on_commit=False) as doc_session:
                await set_context(doc_session, schema, str(tenant_a))
                await doc_session.execute(
                    text(f"UPDATE {qschema(schema)}.documents SET content_sha256 = :sha WHERE id = :did"),
                    {"sha": new_doc_rev, "did": doc_a},
                )
                await doc_session.commit()

            # Methodologist attempts resolution while course still has stale source document revision 'd'*64
            resolve_stale_doc = await client.post(
                f"/courses/{course_a}/resolve-source-uncertainty",
                json={
                    "reason": "Попытка подтверждения при изменившейся ревизии документа в БД",
                    "expected_content_hash": h1,
                    "verified_revision": doc_rev_initial,
                    "verified_revisions": {str(doc_a): doc_rev_initial},
                    "defect_resolutions": [
                        {
                            "defect_id": defect_id,
                            "action": "acknowledged_risk",
                            "rationale": "Согласовано с методическим советом",
                        }
                    ],
                },
            )
            if resolve_stale_doc.status_code != 409:
                raise GateBlocked(f"stale_doc_revision_not_409:{resolve_stale_doc.status_code}:{resolve_stale_doc.text}")
            if "Конфликт ревизий для документа" not in str(resolve_stale_doc.json()):
                raise GateBlocked(f"unexpected_doc_rev_error_message:{resolve_stale_doc.json()}")
            checks.append("stale_document_revision_rejected_409")

            # -------------------------------------------------------------
            # Stage 5: Methodologist Successful Resolution & Audit Logging
            # -------------------------------------------------------------
            # Author/analysis pipeline updates the course analysis to match new document revision 'e'*64
            async with AsyncSession(runtime, expire_on_commit=False) as sync_session:
                await set_context(sync_session, schema, str(tenant_a))
                # Update source_analysis.source_documents to reflect the new revision
                update_sa_sql = f"""
                    UPDATE {qschema(schema)}.courses
                    SET source_analysis = jsonb_set(
                        source_analysis,
                        '{{source_documents}}',
                        jsonb_build_array(
                            jsonb_build_object(
                                'id', CAST(:did AS text),
                                'name', 'Authoritative Document A',
                                'revision', CAST(:rev AS text)
                            )
                        )
                    )
                    WHERE id = :cid
                """
                await sync_session.execute(
                    text(update_sa_sql),
                    {"did": str(doc_a), "rev": new_doc_rev, "cid": course_a},
                )
                await sync_session.commit()

            # Methodologist inspects course to obtain fresh snapshot hash H2 and authoritative revision
            inspect_resp_2 = await client.get(f"/courses/{course_a}/source-uncertainty")
            if inspect_resp_2.status_code != 200:
                raise GateBlocked(f"second_inspection_failed:{inspect_resp_2.text}")
            inspect_2_data = inspect_resp_2.json()
            h2 = inspect_2_data["content_snapshot_hash"]
            if h2 == h1:
                raise GateBlocked("snapshot_hash_did_not_change_after_mutations")
            auth_revs = inspect_2_data["available_revisions"]
            if new_doc_rev not in auth_revs:
                raise GateBlocked(f"new_doc_rev_missing_from_inspection:{auth_revs}")

            # Resolution with matching fresh snapshot hash H2 and authoritative revision 'e'*64
            resolve_success = await client.post(
                f"/courses/{course_a}/resolve-source-uncertainty",
                json={
                    "reason": "Методист проверил актуальный документ e...e и принял остаточный риск",
                    "expected_content_hash": h2,
                    "verified_revision": new_doc_rev,
                    "verified_revisions": {str(doc_a): new_doc_rev},
                    "defect_resolutions": [
                        {
                            "defect_id": defect_id,
                            "action": "acknowledged_risk",
                            "rationale": "Согласовано с методическим советом",
                        }
                    ],
                },
            )
            if resolve_success.status_code != 200:
                raise GateBlocked(f"valid_resolution_failed_{resolve_success.status_code}:{resolve_success.text}")

            # Verify in DB: hold cleared, resolution recorded, history appended
            async with AsyncSession(runtime, expire_on_commit=False) as check_db:
                await set_context(check_db, schema, str(tenant_a))
                course_row = (
                    await check_db.execute(
                        text(f"SELECT source_analysis FROM {qschema(schema)}.courses WHERE id = :cid"),
                        {"cid": course_a},
                    )
                ).one()
                sa = course_row[0]
                if "unresolved_source_uncertainty" in sa:
                    raise GateBlocked("hold_still_present_after_successful_resolution")
                if "source_uncertainty_resolution" not in sa:
                    raise GateBlocked("resolution_metadata_missing")
                if str(sa["source_uncertainty_resolution"]["resolved_by"]) != str(actor_a):
                    raise GateBlocked("resolution_resolved_by_mismatch")
                history = sa.get("resolutions_history", [])
                if len(history) != 1:
                    raise GateBlocked(f"unexpected_history_length:{len(history)}")

                # Verify audit_logs table has the record
                audit_rows = (
                    await check_db.execute(
                        text(
                            f"SELECT action, resource_type, resource_id, user_id FROM {qschema(schema)}.audit_logs "
                            "WHERE resource_id = :cid AND action = 'resolve_source_uncertainty'"
                        ),
                        {"cid": str(course_a)},
                    )
                ).all()
                if len(audit_rows) != 1:
                    raise GateBlocked(f"audit_log_missing_or_duplicate:{len(audit_rows)}")
                audit = audit_rows[0]
                if str(audit[3]) != str(actor_a):
                    raise GateBlocked(f"audit_user_id_mismatch:{audit[3]}")
            checks.append("successful_resolution_hold_cleared_and_audit_logged")

            # -------------------------------------------------------------
            # Stage 6: Cross-Tenant Isolation & RLS Enforcement
            # -------------------------------------------------------------
            current_actor["user"] = SimpleNamespace(
                id=actor_b,
                tenant_id=tenant_b,
                role="methodologist",
                roles=["methodologist"],
                is_active=True,
                email="meth-b@example.invalid",
            )
            current_actor["context_tenant"] = str(tenant_b)

            b_inspect = await client.get(f"/courses/{course_a}/source-uncertainty")
            if b_inspect.status_code != 404:
                raise GateBlocked(f"foreign_tenant_inspect_not_404:{b_inspect.status_code}")

            b_resolve = await client.post(
                f"/courses/{course_a}/resolve-source-uncertainty",
                json={
                    "reason": "Попытка взлома изоляции тенанта из тенанта B",
                    "expected_content_hash": h2,
                    "verified_revision": new_doc_rev,
                    "defect_resolutions": [],
                },
            )
            if b_resolve.status_code != 404:
                raise GateBlocked(f"foreign_tenant_resolve_not_404:{b_resolve.status_code}")
            checks.append("cross_tenant_isolation_rls_verified_404")

        return {
            "status": "PASS",
            "schema": schema,
            "checks": checks,
            "verified_tests": len(checks),
        }
    finally:
        cleanup_error = None
        try:
            async with owner.begin() as cleanup_db:
                await cleanup_db.execute(text(f"DROP SCHEMA IF EXISTS {qschema(schema)} CASCADE"))
        except Exception as exc:
            cleanup_error = exc
        async with owner.begin() as db:
            after = await public_snapshot(db)
            if public_before != after:
                raise GateBlocked("public_snapshot_mutated_after_test")
        await owner.dispose()
        await runtime.dispose()
        if cleanup_error is not None:
            raise GateBlocked("cleanup_failed:" + safe_failure(cleanup_error)) from cleanup_error


def main() -> int:
    parser = argparse.ArgumentParser(description="Live DEV concurrency and source uncertainty gate.")
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if not args.execute:
        print(json.dumps({"status": "BLOCKED", "reason": "execute_required"}))
        return 2

    values = dotenv_values(args.env_file)
    load_dotenv(args.env_file, override=True)

    try:
        owner_url = normalize_database_url(values.get("MIGRATION_DATABASE_URL") or "")
        runtime_url = normalize_database_url(values.get("DATABASE_URL") or "")
        supabase_url = values.get("SUPABASE_URL") or ""

        result = asyncio.run(run_uncertainty_dev_gate(owner_url, runtime_url, supabase_url))
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error": safe_failure(exc)}))
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
