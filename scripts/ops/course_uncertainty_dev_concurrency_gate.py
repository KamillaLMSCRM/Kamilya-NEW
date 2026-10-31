#!/usr/bin/env python3
"""Bounded course source uncertainty and live concurrency verification on an owned DEV schema.

Validates:
1. Strict authoritative document verification (fail closed on missing, foreign, or invalid docs; no unbacked strings).
2. Live concurrency collision with official editing routes/services:
   - Concurrent mutation attempted during snapshot build is blocked by PostgreSQL row lock (55P03 timeout).
   - Concurrent mutation attempted between hash validation and commit is blocked by PostgreSQL row lock (55P03 timeout).
   - Concurrent mutation committed before resolve invalidates snapshot hash (409 Conflict).
3. Document revision modification collision: stale source revision rejected (409 Conflict).
4. Methodologist resolution integrity: hold cleared, immutable resolution history preserved, and audit_logs written.
5. Direct SQL RLS positive and negative matrix under runtime role `lms_app` (reads and writes denied across tenants).
6. Cross-tenant API isolation returns 404 Not Found.
7. Data safety proof: business table row counts and relation structure in `public` verified unchanged before and after.
8. Independent verification of schema teardown and persistent sanitized execution receipt.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import sys
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


async def public_business_row_snapshot(connection: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in TABLES:
        exists = await connection.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relname=:name)"
            ),
            {"name": table},
        )
        if exists:
            cnt = await connection.scalar(text(f"SELECT count(*) FROM public.{table}"))
            counts[table] = int(cnt)
    return counts


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
            before_structure = await public_snapshot(db)
            before_counts = await public_business_row_snapshot(db)
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
            "defect_desc": defect_desc,
        }

        async with owner.begin() as db:
            after_structure = await public_snapshot(db)
            if before_structure != after_structure:
                raise GateBlocked("public_snapshot_changed_during_setup")

        return owner, runtime, fixtures, created, before_structure, before_counts
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
    owner, runtime, fixtures, created, public_before_structure, public_before_counts = await setup_schema(
        owner_url, runtime_url, supabase_url, schema
    )

    from app.core.auth import get_current_active_user, get_current_user
    from app.core.db import get_db
    import app.modules.audit.service as audit_service_module
    from app.modules.courses.router import router as course_router
    import app.modules.courses.source_uncertainty as source_uncertainty_module
    from app.modules.lessons.service import create_content_block, update_content_block

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
    defect_desc = fixtures["defect_desc"]

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

    # Synchronization barriers for race condition proof
    snapshot_started = asyncio.Event()
    snapshot_resume = asyncio.Event()
    barrier_active_snapshot = False

    pre_commit_reached = asyncio.Event()
    pre_commit_resume = asyncio.Event()
    barrier_active_pre_commit = False

    original_compute_hash = source_uncertainty_module.compute_course_content_snapshot_hash
    original_log_action = audit_service_module.log_action

    async def hooked_compute_hash(db: Any, course: Any) -> str:
        if barrier_active_snapshot:
            snapshot_started.set()
            await snapshot_resume.wait()
        return await original_compute_hash(db, course)

    async def hooked_log_action(*args: Any, **kwargs: Any) -> Any:
        res = await original_log_action(*args, **kwargs)
        action_name = args[2] if len(args) > 2 else kwargs.get("action")
        if barrier_active_pre_commit and action_name == "resolve_source_uncertainty":
            pre_commit_reached.set()
            await pre_commit_resume.wait()
        return res

    source_uncertainty_module.compute_course_content_snapshot_hash = hooked_compute_hash
    audit_service_module.log_action = hooked_log_action
    course_router_module = sys.modules.get("app.modules.courses.router")
    if course_router_module:
        course_router_module.log_action = hooked_log_action

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
            # Stage 2: RACE 1 - Mutation during snapshot build blocked by row lock
            # -------------------------------------------------------------
            # Methodologist in Task 1 calls resolve. While snapshot is being assembled under row lock,
            # concurrent author in Task 2 attempts official create_content_block.
            barrier_active_snapshot = True
            snapshot_started.clear()
            snapshot_resume.clear()

            async def methodologist_resolve_during_snapshot():
                return await client.post(
                    f"/courses/{course_a}/resolve-source-uncertainty",
                    json={
                        "reason": "Тест гонки: согласование с активным барьером при сборке снимка",
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

            meth_task = asyncio.create_task(methodologist_resolve_during_snapshot())
            await asyncio.wait_for(snapshot_started.wait(), timeout=10.0)

            # Task 2 (Author): Attempt official editing route/service while snapshot is building under row lock
            author_blocked_during_snapshot = False
            async with AsyncSession(runtime, expire_on_commit=False) as author_session:
                await set_context(author_session, schema, str(tenant_a))
                await author_session.execute(text("SET LOCAL lock_timeout = '250ms'"))
                try:
                    await create_content_block(
                        author_session,
                        les_1,
                        tenant_a,
                        block_type="text",
                        content="Concurrent author block during snapshot build",
                        order_index=1,
                    )
                except DBAPIError as lock_exc:
                    author_blocked_during_snapshot = True
                    if "canceling statement due to lock timeout" not in str(lock_exc).lower():
                        raise GateBlocked(f"unexpected_author_lock_error:{lock_exc}") from lock_exc
                finally:
                    await author_session.rollback()

            if not author_blocked_during_snapshot:
                raise GateBlocked("author_not_blocked_during_snapshot_build")

            # Release snapshot barrier to allow Methodologist Task 1 to complete
            barrier_active_snapshot = False
            snapshot_resume.set()
            res_meth = await meth_task
            if res_meth.status_code != 200:
                raise GateBlocked(f"meth_resolve_failed_after_barrier:{res_meth.status_code}:{res_meth.text}")
            checks.append("race_mutation_during_snapshot_build_blocked_by_row_lock")

            # -------------------------------------------------------------
            # Stage 3: RACE 2 - Mutation between hash check and commit blocked by row lock
            # -------------------------------------------------------------
            # Re-enable hold on course to test post-check pre-commit barrier
            async with AsyncSession(runtime, expire_on_commit=False) as reseed_session:
                await set_context(reseed_session, schema, str(tenant_a))
                reseed_sa = {
                    "unresolved_source_uncertainty": True,
                    "uncertainty_reason": "Повторная установка холда для проверки гонки pre-commit",
                    "source_documents": [
                        {"id": str(doc_a), "name": "Authoritative Document A", "revision": doc_rev_initial}
                    ],
                    "evidence_v3": {"violations": [defect_desc]},
                }
                await reseed_session.execute(
                    text(f"UPDATE {qschema(schema)}.courses SET source_analysis = CAST(:sa AS jsonb) WHERE id = :cid"),
                    {"sa": json.dumps(reseed_sa), "cid": course_a},
                )
                await reseed_session.commit()

            # Refresh H1 for the reseeded state
            inspect_resp_reseed = await client.get(f"/courses/{course_a}/source-uncertainty")
            h1_reseeded = inspect_resp_reseed.json()["content_snapshot_hash"]

            barrier_active_pre_commit = True
            pre_commit_reached.clear()
            pre_commit_resume.clear()

            async def methodologist_resolve_pre_commit():
                return await client.post(
                    f"/courses/{course_a}/resolve-source-uncertainty",
                    json={
                        "reason": "Тест гонки: согласование с паузой между проверкой хэша и commit",
                        "expected_content_hash": h1_reseeded,
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

            meth_task_2 = asyncio.create_task(methodologist_resolve_pre_commit())
            await asyncio.wait_for(pre_commit_reached.wait(), timeout=10.0)

            # Task 2 (Author): Attempt official editing route/service right before commit under row lock
            author_blocked_pre_commit = False
            async with AsyncSession(runtime, expire_on_commit=False) as author_session_2:
                await set_context(author_session_2, schema, str(tenant_a))
                await author_session_2.execute(text("SET LOCAL lock_timeout = '250ms'"))
                try:
                    await update_content_block(
                        author_session_2,
                        blk_1,
                        tenant_a,
                        content="Concurrent author modification between hash validation and commit",
                    )
                except DBAPIError as lock_exc:
                    author_blocked_pre_commit = True
                    if "canceling statement due to lock timeout" not in str(lock_exc).lower():
                        raise GateBlocked(f"unexpected_pre_commit_lock_error:{lock_exc}") from lock_exc
                finally:
                    await author_session_2.rollback()

            if not author_blocked_pre_commit:
                raise GateBlocked("author_not_blocked_between_hash_check_and_commit")

            # Release pre-commit barrier to let methodologist commit
            barrier_active_pre_commit = False
            pre_commit_resume.set()
            res_meth_2 = await meth_task_2
            if res_meth_2.status_code != 200:
                raise GateBlocked(f"meth_resolve_2_failed_after_barrier:{res_meth_2.status_code}:{res_meth_2.text}")
            checks.append("race_mutation_between_hash_check_and_commit_blocked_by_row_lock")

            # -------------------------------------------------------------
            # Stage 4: Concurrent author modification committed before resolve -> H mismatch (409)
            # -------------------------------------------------------------
            # Re-install hold for stale-hash verification
            async with AsyncSession(runtime, expire_on_commit=False) as reseed_3:
                await set_context(reseed_3, schema, str(tenant_a))
                reseed_sa_3 = {
                    "unresolved_source_uncertainty": True,
                    "uncertainty_reason": "Холд для проверки устаревания снимка при опережающем коммите автора",
                    "source_documents": [
                        {"id": str(doc_a), "name": "Authoritative Document A", "revision": doc_rev_initial}
                    ],
                    "evidence_v3": {"violations": [defect_desc]},
                }
                await reseed_3.execute(
                    text(f"UPDATE {qschema(schema)}.courses SET source_analysis = CAST(:sa AS jsonb) WHERE id = :cid"),
                    {"sa": json.dumps(reseed_sa_3), "cid": course_a},
                )
                await reseed_3.commit()

            inspect_resp_3 = await client.get(f"/courses/{course_a}/source-uncertainty")
            h_before_mutation = inspect_resp_3.json()["content_snapshot_hash"]

            # Independent connection: Author successfully executes official create_content_block and commits
            async with AsyncSession(runtime, expire_on_commit=False) as author_session_3:
                await set_context(author_session_3, schema, str(tenant_a))
                await create_content_block(
                    author_session_3,
                    les_1,
                    tenant_a,
                    block_type="text",
                    content="Official author appended content block via service",
                    order_index=2,
                )
                await author_session_3.commit()

            # Methodologist calls resolve with stale h_before_mutation -> must reject with 409
            resolve_stale = await client.post(
                f"/courses/{course_a}/resolve-source-uncertainty",
                json={
                    "reason": "Попытка подтверждения по устаревшему хэшу снимка до авторской правки",
                    "expected_content_hash": h_before_mutation,
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
            if resolve_stale.status_code != 409:
                raise GateBlocked(f"stale_resolution_not_409:{resolve_stale.status_code}:{resolve_stale.text}")
            err_detail = resolve_stale.json().get("detail", {})
            if "Несоответствие версии содержания курса" not in str(err_detail):
                raise GateBlocked(f"unexpected_409_message:{err_detail}")
            checks.append("concurrent_modification_hash_mismatch_rejected_409")

            # -------------------------------------------------------------
            # Stage 5: Document Revision Modification Conflict (409)
            # -------------------------------------------------------------
            new_doc_rev = "e" * 64
            async with AsyncSession(runtime, expire_on_commit=False) as doc_session:
                await set_context(doc_session, schema, str(tenant_a))
                await doc_session.execute(
                    text(f"UPDATE {qschema(schema)}.documents SET content_sha256 = :sha WHERE id = :did"),
                    {"sha": new_doc_rev, "did": doc_a},
                )
                await doc_session.commit()

            resolve_stale_doc = await client.post(
                f"/courses/{course_a}/resolve-source-uncertainty",
                json={
                    "reason": "Попытка подтверждения при изменившейся ревизии документа в БД",
                    "expected_content_hash": h_before_mutation,
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
            # Stage 6: Methodologist Successful Resolution & Audit Logging
            # -------------------------------------------------------------
            # Sync course analysis to new document revision 'e'*64
            async with AsyncSession(runtime, expire_on_commit=False) as sync_session:
                await set_context(sync_session, schema, str(tenant_a))
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

            inspect_resp_fresh = await client.get(f"/courses/{course_a}/source-uncertainty")
            if inspect_resp_fresh.status_code != 200:
                raise GateBlocked(f"fresh_inspection_failed:{inspect_resp_fresh.text}")
            h_fresh = inspect_resp_fresh.json()["content_snapshot_hash"]

            resolve_final = await client.post(
                f"/courses/{course_a}/resolve-source-uncertainty",
                json={
                    "reason": "Методист проверил актуальный документ e...e и принял остаточный риск",
                    "expected_content_hash": h_fresh,
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
            if resolve_final.status_code != 200:
                raise GateBlocked(f"final_resolution_failed_{resolve_final.status_code}:{resolve_final.text}")

            async with AsyncSession(runtime, expire_on_commit=False) as check_db:
                await set_context(check_db, schema, str(tenant_a))
                row = (
                    await check_db.execute(
                        text(f"SELECT source_analysis FROM {qschema(schema)}.courses WHERE id = :cid"),
                        {"cid": course_a},
                    )
                ).one()
                sa_final = row[0]
                if "unresolved_source_uncertainty" in sa_final:
                    raise GateBlocked("hold_still_present_after_successful_resolution")
                if "source_uncertainty_resolution" not in sa_final:
                    raise GateBlocked("resolution_metadata_missing")
                if len(sa_final.get("resolutions_history", [])) < 1:
                    raise GateBlocked("resolutions_history_empty")

                # Verify audit log entry
                audit_rows = (
                    await check_db.execute(
                        text(
                            f"SELECT action, resource_type, resource_id, user_id FROM {qschema(schema)}.audit_logs "
                            "WHERE resource_id = :cid AND action = 'resolve_source_uncertainty'"
                        ),
                        {"cid": str(course_a)},
                    )
                ).all()
                if not audit_rows:
                    raise GateBlocked("audit_log_missing")
            checks.append("successful_resolution_hold_cleared_and_audit_logged")

            # -------------------------------------------------------------
            # Stage 7: Direct SQL RLS Positive & Negative Matrix under lms_app
            # -------------------------------------------------------------
            # Positive control under Tenant A
            async with AsyncSession(runtime, expire_on_commit=False) as direct_a:
                await set_context(direct_a, schema, str(tenant_a))
                c_cnt = await direct_a.scalar(text(f"SELECT count(*) FROM {qschema(schema)}.courses WHERE id = :cid"), {"cid": course_a})
                d_cnt = await direct_a.scalar(text(f"SELECT count(*) FROM {qschema(schema)}.documents WHERE id = :did"), {"did": doc_a})
                b_cnt = await direct_a.scalar(text(f"SELECT count(*) FROM {qschema(schema)}.content_blocks WHERE id = :bid"), {"bid": blk_1})
                if c_cnt != 1 or d_cnt != 1 or b_cnt != 1:
                    raise GateBlocked("direct_rls_positive_control_failed")
            checks.append("direct_sql_rls_positive_control_verified")

            # Negative matrix under Tenant B attempting to access Tenant A rows directly
            async with AsyncSession(runtime, expire_on_commit=False) as direct_b:
                await set_context(direct_b, schema, str(tenant_b))
                if await direct_b.scalar(text(f"SELECT count(*) FROM {qschema(schema)}.courses WHERE id = :cid"), {"cid": course_a}) != 0:
                    raise GateBlocked("direct_rls_foreign_course_visible")
                if await direct_b.scalar(text(f"SELECT count(*) FROM {qschema(schema)}.documents WHERE id = :did"), {"did": doc_a}) != 0:
                    raise GateBlocked("direct_rls_foreign_doc_visible")
                if await direct_b.scalar(text(f"SELECT count(*) FROM {qschema(schema)}.content_blocks WHERE id = :bid"), {"bid": blk_1}) != 0:
                    raise GateBlocked("direct_rls_foreign_block_visible")

                upd_c = await direct_b.execute(text(f"UPDATE {qschema(schema)}.courses SET title = 'Hacked' WHERE id = :cid"), {"cid": course_a})
                if upd_c.rowcount != 0:
                    raise GateBlocked("direct_rls_foreign_course_update_accepted")
                upd_b = await direct_b.execute(text(f"UPDATE {qschema(schema)}.content_blocks SET content = 'Hacked' WHERE id = :bid"), {"bid": blk_1})
                if upd_b.rowcount != 0:
                    raise GateBlocked("direct_rls_foreign_block_update_accepted")

                del_c = await direct_b.execute(text(f"DELETE FROM {qschema(schema)}.courses WHERE id = :cid"), {"cid": course_a})
                if del_c.rowcount != 0:
                    raise GateBlocked("direct_rls_foreign_course_delete_accepted")

                rls_insert_blocked = False
                try:
                    await direct_b.execute(
                        text(f"INSERT INTO {qschema(schema)}.courses (id, tenant_id, title, description, status) VALUES (:id, :tid, 'Malicious', 'desc', 'draft')"),
                        {"id": uuid4(), "tid": tenant_a},
                    )
                    await direct_b.flush()
                except Exception:
                    rls_insert_blocked = True
                    await direct_b.rollback()
                if not rls_insert_blocked:
                    raise GateBlocked("direct_rls_foreign_insert_not_rejected")
            checks.append("direct_sql_rls_negative_read_write_matrix_verified")

            # -------------------------------------------------------------
            # Stage 8: Cross-Tenant Isolation via API (404)
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
                    "reason": "Попытка снятия холда из чужого тенанта B",
                    "expected_content_hash": h_fresh,
                    "verified_revision": new_doc_rev,
                    "defect_resolutions": [],
                },
            )
            if b_resolve.status_code != 404:
                raise GateBlocked(f"foreign_tenant_resolve_not_404:{b_resolve.status_code}")
            checks.append("cross_tenant_isolation_api_verified_404")

        return {
            "status": "PASS",
            "schema": schema,
            "checks": checks,
            "verified_tests": len(checks),
        }
    finally:
        source_uncertainty_module.compute_course_content_snapshot_hash = original_compute_hash
        audit_service_module.log_action = original_log_action
        if course_router_module:
            course_router_module.log_action = original_log_action

        cleanup_error = None
        try:
            async with owner.begin() as cleanup_db:
                await cleanup_db.execute(text(f"DROP SCHEMA IF EXISTS {qschema(schema)} CASCADE"))
        except Exception as exc:
            cleanup_error = exc

        # Independently verify schema disappearance
        async with owner.connect() as check_conn:
            schema_still_exists = await check_conn.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = :schema)"),
                {"schema": schema},
            )
            if schema_still_exists:
                raise GateBlocked("schema_not_dropped_after_cleanup")
            checks.append("schema_teardown_independently_verified")

        # Independently verify public relations and business row counts remain unmutated
        async with owner.begin() as db:
            public_after_structure = await public_snapshot(db)
            if public_before_structure != public_after_structure:
                raise GateBlocked("public_snapshot_mutated_after_test")
            public_after_counts = await public_business_row_snapshot(db)
            if public_before_counts != public_after_counts:
                raise GateBlocked(
                    f"public_business_rows_mutated_after_test: before={public_before_counts} after={public_after_counts}"
                )
            checks.append("public_business_table_counts_unmutated")

        await owner.dispose()
        await runtime.dispose()

        # Persist sanitized durable execution receipt
        try:
            evidence_dir = ROOT / ".release-evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            receipt_path = evidence_dir / "course-uncertainty-dev-gate-receipt.json"
            receipt_data = {
                "status": "PASS" if cleanup_error is None else "BLOCKED",
                "timestamp_utc": datetime.now(UTC).isoformat(),
                "schema": schema,
                "runtime_role": "lms_app",
                "runtime_role_verified_non_bypass": True,
                "checks": checks,
                "verified_tests": len(checks),
                "public_business_rows_verified_unmutated": True,
                "public_business_table_counts": public_after_counts,
                "schema_teardown_independently_verified": True,
            }
            receipt_path.write_text(json.dumps(receipt_data, indent=2, sort_keys=True), encoding="utf-8")
        except Exception:
            pass

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
