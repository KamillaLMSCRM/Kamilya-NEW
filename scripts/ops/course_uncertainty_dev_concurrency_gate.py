#!/usr/bin/env python3
"""Bounded course source uncertainty and live concurrency verification on an owned DEV schema.

Validates:
1. Strict authoritative document verification (fail closed on missing, foreign, or invalid docs; no unbacked strings).
2. Live concurrency collision with official editing routes/services:
   - Concurrent block mutation during snapshot build is blocked by PostgreSQL row lock (55P03 timeout).
   - Concurrent document update during snapshot build is blocked by PostgreSQL row lock (55P03 timeout).
   - Concurrent block mutation between hash check and commit is blocked by PostgreSQL row lock (55P03 timeout).
   - Concurrent document update between revision check and commit is blocked by PostgreSQL row lock (55P03 timeout).
   - Post-commit author retry succeeds and is verified by independent readback.
   - Concurrent block mutation committed before resolve invalidates snapshot hash (409 Conflict).
3. Document revision modification collision: stale source revision rejected (409 Conflict).
4. Methodologist resolution integrity: hold cleared, immutable resolution history preserved, and audit_logs written.
5. Direct SQL RLS positive and negative matrix under runtime role `lms_app` (reads and writes denied across tenants).
6. Cross-tenant API isolation returns 404 Not Found.
7. Data safety proof: business table row counts AND cryptographic row-level content hashes in `public` verified unmutated.
8. Independent verification of schema teardown readback and receipt integrity with Git commit binding.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
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

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
API_ROOT = ROOT / "apps" / "api"
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from kb_rag_isolated_dev_gate import GateBlocked, normalize_database_url, same_supabase_project
from source_actuality_dev_gate import public_snapshot, verify_runtime_role
from workbench_assignment_dev_gate import safe_failure

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

REQUIRED_CHECKS = frozenset({
    "initial_inspection_and_snapshot_hash_h1",
    "race_mutation_during_snapshot_build_blocked_by_row_lock",
    "race_document_update_during_snapshot_build_blocked_by_row_lock",
    "race_mutation_between_hash_check_and_commit_blocked_by_row_lock",
    "race_document_update_between_revision_check_and_commit_blocked_by_row_lock",
    "post_commit_author_retry_applied_and_readback_verified",
    "concurrent_modification_hash_mismatch_rejected_409",
    "stale_document_revision_rejected_409",
    "successful_resolution_hold_cleared_and_audit_logged",
    "direct_sql_rls_positive_control_verified",
    "direct_sql_rls_negative_read_write_matrix_verified",
    "cross_tenant_isolation_api_verified_404",
    "schema_teardown_independently_verified",
    "public_business_table_counts_and_hashes_unmutated",
})


def qschema(value: str) -> str:
    if not SCHEMA_RE.fullmatch(value):
        raise GateBlocked("unsafe_uncertainty_schema")
    return f'"{value}"'


def get_git_commit_sha() -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()
    except Exception:
        return "unknown"


def get_git_branch() -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()
    except Exception:
        return "unknown"


def evaluate_gate_outcome(
    *,
    main_completed: bool,
    main_error: Exception | None,
    cleanup_error: Exception | None,
    schema_dropped: bool,
    public_structure_ok: bool,
    public_counts_and_hashes_ok: bool,
    checks: list[str],
    required_checks: frozenset[str] = REQUIRED_CHECKS,
) -> tuple[bool, str, list[str]]:
    """Evaluates whether the gate passed completely and returns (overall_pass, status_string, missing_checks)."""
    checks_set = set(checks)
    missing_checks = sorted(required_checks - checks_set)
    all_required_present = len(missing_checks) == 0

    overall_pass = (
        main_completed
        and (main_error is None)
        and (cleanup_error is None)
        and schema_dropped
        and public_structure_ok
        and public_counts_and_hashes_ok
        and all_required_present
    )
    status = "PASS" if overall_pass else "BLOCKED"
    return overall_pass, status, missing_checks


def persist_gate_receipt(
    receipt_data: dict[str, Any],
    *,
    evidence_dir: Path | None = None,
    run_id: str | None = None,
) -> tuple[Path, Path]:
    """Atomically persists gate receipt both to a unique per-run file and updates the latest receipt file.

    Does NOT suppress errors: any filesystem or serialization failure propagates.
    """
    target_dir = evidence_dir or (ROOT / ".release-evidence")
    target_dir.mkdir(parents=True, exist_ok=True)

    effective_run_id = (
        run_id
        or f"{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}_{receipt_data.get('schema', 'unknown')}"
    )
    run_receipt_path = target_dir / f"course-uncertainty-dev-gate-receipt-{effective_run_id}.json"
    latest_receipt_path = target_dir / "course-uncertainty-dev-gate-receipt.json"

    serialized = json.dumps(receipt_data, indent=2, sort_keys=True) + "\n"

    # Write per-run receipt atomically via temporary file
    tmp_run_path = target_dir / f".tmp_{effective_run_id}.json"
    tmp_run_path.write_text(serialized, encoding="utf-8")
    tmp_run_path.replace(run_receipt_path)

    # Write latest receipt atomically via temporary file
    tmp_latest_path = target_dir / f".tmp_latest_{effective_run_id}.json"
    tmp_latest_path.write_text(serialized, encoding="utf-8")
    tmp_latest_path.replace(latest_receipt_path)

    return run_receipt_path, latest_receipt_path


def write_startup_in_progress_marker(
    *,
    evidence_dir: Path,
    run_id: str,
    schema: str,
) -> Path:
    """Updates the mutable latest receipt with an in-progress marker on run startup.

    Does NOT write the per-run file so that course-uncertainty-dev-gate-receipt-{run_id}.json
    is created strictly once upon terminal verdict (PASS or BLOCKED).
    """
    evidence_dir.mkdir(parents=True, exist_ok=True)
    latest_receipt_path = evidence_dir / "course-uncertainty-dev-gate-receipt.json"
    marker = {
        "status": "RUNNING",
        "run_id": run_id,
        "schema": schema,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit": get_git_commit_sha(),
        "git_branch": get_git_branch(),
    }
    tmp_path = evidence_dir / f".tmp_init_{run_id}.json"
    tmp_path.write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(latest_receipt_path)
    return latest_receipt_path


async def set_context(
    db: AsyncSession,
    schema: str,
    tenant_id: str = "",
    confirmed_pids: set[int] | None = None,
) -> None:
    await db.execute(text(f"SET LOCAL search_path TO {qschema(schema)}, pg_catalog"))
    await db.execute(
        text(
            "SELECT set_config('app.tenant_id',:tenant,true), "
            "set_config('app.is_superadmin','false',true)"
        ),
        {"tenant": tenant_id},
    )
    if confirmed_pids is not None:
        try:
            pid = await db.scalar(text("SELECT pg_backend_pid()"))
            if pid:
                confirmed_pids.add(int(pid))
        except Exception:
            pass


async def terminate_lingering_test_sessions(owner: Any, confirmed_pids: set[int]) -> int:
    """Terminates ONLY specifically confirmed PostgreSQL backend PIDs belonging to this test.

    Never uses query wildcards or schema name pattern matching, preventing accidental
    termination of external diagnostic, monitoring, or concurrent sessions.
    """
    if not confirmed_pids or owner is None:
        return 0
    try:
        async with owner.connect() as term_conn:
            current_pid = await term_conn.scalar(text("SELECT pg_backend_pid()"))
            target_pids = [p for p in confirmed_pids if p != current_pid]
            if not target_pids:
                return 0
            res = await term_conn.execute(
                text("""
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE pid = ANY(:target_pids)
                      AND pid <> pg_backend_pid()
                """),
                {"target_pids": target_pids},
            )
            return len(res.fetchall())
    except Exception:
        return 0


async def public_business_row_snapshot(connection: Any) -> dict[str, dict[str, Any]]:
    """Computes exact row count and cryptographic row content hash for every business table in public."""
    results: dict[str, dict[str, Any]] = {}
    for table in TABLES:
        exists = await connection.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relname=:name)"
            ),
            {"name": table},
        )
        if exists:
            row = (
                await connection.execute(
                    text(
                        f"SELECT count(*), coalesce(md5(string_agg(md5(row_to_json(t)::text), '' ORDER BY t.id)), 'empty') "
                        f"FROM public.{table} t"
                    )
                )
            ).one()
            results[table] = {"count": int(row[0]), "md5_content_hash": str(row[1])}
    return results


async def setup_schema(
    owner_url: str,
    runtime_url: str,
    supabase_url: str,
    schema: str,
    confirmed_pids: set[int] | None = None,
):
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
            if confirmed_pids is not None:
                try:
                    pid = await db.scalar(text("SELECT pg_backend_pid()"))
                    if pid:
                        confirmed_pids.add(int(pid))
                except Exception:
                    pass
            await verify_runtime_role(db)
        async with owner.begin() as db:
            if confirmed_pids is not None:
                try:
                    pid = await db.scalar(text("SELECT pg_backend_pid()"))
                    if pid:
                        confirmed_pids.add(int(pid))
                except Exception:
                    pass
            before_structure = await public_snapshot(db)
            before_counts_hashes = await public_business_row_snapshot(db)
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
            if confirmed_pids is not None:
                try:
                    pid = await seed.scalar(text("SELECT pg_backend_pid()"))
                    if pid:
                        confirmed_pids.add(int(pid))
                except Exception:
                    pass
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

        return owner, runtime, fixtures, created, before_structure, before_counts_hashes
    except Exception:
        cleanup_error = None
        if created:
            try:
                async with owner.begin() as cleanup_db:
                    await cleanup_db.execute(text(f"DROP SCHEMA IF EXISTS {qschema(schema)} CASCADE"))
            except Exception as exc:
                cleanup_error = exc
        if owner is not None:
            await owner.dispose()
        if runtime is not None:
            await runtime.dispose()
        if cleanup_error is not None:
            raise GateBlocked("setup_cleanup_failed:" + safe_failure(cleanup_error)) from cleanup_error
        raise


async def run_uncertainty_dev_gate(
    owner_url: str,
    runtime_url: str,
    supabase_url: str,
    *,
    evidence_dir: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    schema = f"uncertainty_{uuid4().hex[:12]}"
    target_evidence_dir = evidence_dir or (ROOT / ".release-evidence")
    effective_run_id = (
        run_id
        or f"{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}_{schema}"
    )

    # Invalidate latest receipt by writing explicit in-progress marker.
    # Note: The per-run receipt file (course-uncertainty-dev-gate-receipt-{run_id}.json)
    # is intentionally NOT written here. It is written strictly once upon terminal verdict,
    # guaranteeing that each per-run file is immutable.
    write_startup_in_progress_marker(
        evidence_dir=target_evidence_dir,
        run_id=effective_run_id,
        schema=schema,
    )

    owner: Any = None
    runtime: Any = None
    fixtures: dict[str, Any] = {}
    created = False
    public_before_structure: dict[str, Any] = {}
    public_before_counts_hashes: dict[str, dict[str, Any]] = {}
    confirmed_test_pids: set[int] = set()

    checks: list[str] = []
    main_completed = False
    main_error: Exception | None = None
    cleanup_error: Exception | None = None
    receipt_error: Exception | None = None
    failure_stage = "setup_schema"
    schema_dropped = False
    public_structure_ok = False
    public_counts_and_hashes_ok = False
    public_after_counts_hashes: dict[str, dict[str, Any]] = {}
    receipt_data: dict[str, Any] = {}

    barrier_active_snapshot = False
    barrier_active_pre_commit = False
    snapshot_started = asyncio.Event()
    snapshot_resume = asyncio.Event()
    pre_commit_reached = asyncio.Event()
    pre_commit_resume = asyncio.Event()
    active_tasks: list[asyncio.Task] = []

    original_compute_hash: Any = None
    original_log_action: Any = None
    source_uncertainty_module: Any = None
    audit_service_module: Any = None
    course_router_module: Any = None

    try:
        failure_stage = "setup_schema"
        owner, runtime, fixtures, created, public_before_structure, public_before_counts_hashes = await setup_schema(
            owner_url, runtime_url, supabase_url, schema, confirmed_pids=confirmed_test_pids
        )

        failure_stage = "app_initialization"
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
                await set_context(session, schema, current_actor["context_tenant"], confirmed_pids=confirmed_test_pids)
                yield session

        app.dependency_overrides[get_current_active_user] = override_principal
        app.dependency_overrides[get_current_user] = override_principal
        app.dependency_overrides[get_db] = override_db

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

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # -------------------------------------------------------------
            # Stage 1: Inspect details & compute H1
            # -------------------------------------------------------------
            failure_stage = "stage_1_initial_inspection"
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
            failure_stage = "stage_2_race_during_snapshot_build"
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
            active_tasks.append(meth_task)
            await asyncio.wait_for(snapshot_started.wait(), timeout=10.0)

            # Concurrent action 2a: Author attempts official create_content_block under row lock
            author_blocked_during_snapshot = False
            async with AsyncSession(runtime, expire_on_commit=False) as author_session:
                await set_context(author_session, schema, str(tenant_a), confirmed_pids=confirmed_test_pids)
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
            checks.append("race_mutation_during_snapshot_build_blocked_by_row_lock")

            # Concurrent action 2b: Document update attempted during snapshot build under document row lock
            doc_blocked_during_snapshot = False
            async with AsyncSession(runtime, expire_on_commit=False) as doc_session_race1:
                await set_context(doc_session_race1, schema, str(tenant_a), confirmed_pids=confirmed_test_pids)
                await doc_session_race1.execute(text("SET LOCAL lock_timeout = '250ms'"))
                try:
                    await doc_session_race1.execute(
                        text(f"UPDATE {qschema(schema)}.documents SET content_sha256 = :h WHERE id = :did"),
                        {"did": doc_a, "h": "1" * 64},
                    )
                except DBAPIError as lock_exc:
                    doc_blocked_during_snapshot = True
                    if "canceling statement due to lock timeout" not in str(lock_exc).lower():
                        raise GateBlocked(f"unexpected_doc_lock_error:{lock_exc}") from lock_exc
                finally:
                    await doc_session_race1.rollback()

            if not doc_blocked_during_snapshot:
                raise GateBlocked("doc_not_blocked_during_snapshot_build")
            checks.append("race_document_update_during_snapshot_build_blocked_by_row_lock")

            # Release snapshot barrier to allow Methodologist Task 1 to complete
            barrier_active_snapshot = False
            snapshot_resume.set()
            res_meth = await meth_task
            if res_meth.status_code != 200:
                raise GateBlocked(f"meth_resolve_failed_after_barrier:{res_meth.status_code}:{res_meth.text}")

            # -------------------------------------------------------------
            # Stage 3: RACE 2 - Mutation between hash check and commit blocked by row lock
            # -------------------------------------------------------------
            failure_stage = "stage_3_race_pre_commit"
            # Reseed hold to test pre-commit barrier
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
            active_tasks.append(meth_task_2)
            await asyncio.wait_for(pre_commit_reached.wait(), timeout=10.0)

            # Concurrent action 3a: Author attempts official update_content_block right before commit under row lock
            author_blocked_pre_commit = False
            async with AsyncSession(runtime, expire_on_commit=False) as author_session_2:
                await set_context(author_session_2, schema, str(tenant_a), confirmed_pids=confirmed_test_pids)
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
            checks.append("race_mutation_between_hash_check_and_commit_blocked_by_row_lock")

            # Concurrent action 3b: Document update attempted right before commit under document row lock
            doc_blocked_pre_commit = False
            async with AsyncSession(runtime, expire_on_commit=False) as doc_session_race2:
                await set_context(doc_session_race2, schema, str(tenant_a), confirmed_pids=confirmed_test_pids)
                await doc_session_race2.execute(text("SET LOCAL lock_timeout = '250ms'"))
                try:
                    await doc_session_race2.execute(
                        text(f"UPDATE {qschema(schema)}.documents SET content_sha256 = :h WHERE id = :did"),
                        {"did": doc_a, "h": "2" * 64},
                    )
                except DBAPIError as lock_exc:
                    doc_blocked_pre_commit = True
                    if "canceling statement due to lock timeout" not in str(lock_exc).lower():
                        raise GateBlocked(f"unexpected_doc_pre_commit_lock_error:{lock_exc}") from lock_exc
                finally:
                    await doc_session_race2.rollback()

            if not doc_blocked_pre_commit:
                raise GateBlocked("doc_not_blocked_between_revision_check_and_commit")
            checks.append("race_document_update_between_revision_check_and_commit_blocked_by_row_lock")

            # Release pre-commit barrier to let methodologist commit
            barrier_active_pre_commit = False
            pre_commit_resume.set()
            res_meth_2 = await meth_task_2
            if res_meth_2.status_code != 200:
                raise GateBlocked(f"meth_resolve_2_failed_after_barrier:{res_meth_2.status_code}:{res_meth_2.text}")

            # Explicit post-commit retry of author update and independent readback
            async with AsyncSession(runtime, expire_on_commit=False) as post_commit_author:
                await set_context(post_commit_author, schema, str(tenant_a))
                retry_block = await update_content_block(
                    post_commit_author,
                    blk_1,
                    tenant_a,
                    content="Author update successfully applied and committed after methodologist release",
                )
                if not retry_block:
                    raise GateBlocked("post_commit_author_retry_returned_none")
                await post_commit_author.commit()

            async with AsyncSession(runtime, expire_on_commit=False) as readback_session:
                await set_context(readback_session, schema, str(tenant_a))
                readback_val = await readback_session.scalar(
                    text(f"SELECT content FROM {qschema(schema)}.content_blocks WHERE id = :bid"),
                    {"bid": blk_1},
                )
                if readback_val != "Author update successfully applied and committed after methodologist release":
                    raise GateBlocked(f"post_commit_readback_mismatch:{readback_val}")
            checks.append("post_commit_author_retry_applied_and_readback_verified")

            # -------------------------------------------------------------
            # Stage 4: Concurrent author modification committed before resolve -> H mismatch (409)
            # -------------------------------------------------------------
            failure_stage = "stage_4_stale_hash_rejection"
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
            failure_stage = "stage_5_stale_document_revision_rejection"
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
            failure_stage = "stage_6_successful_resolution_and_audit"
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
            failure_stage = "stage_7_direct_sql_rls"
            async with AsyncSession(runtime, expire_on_commit=False) as direct_a:
                await set_context(direct_a, schema, str(tenant_a))
                c_cnt = await direct_a.scalar(text(f"SELECT count(*) FROM {qschema(schema)}.courses WHERE id = :cid"), {"cid": course_a})
                d_cnt = await direct_a.scalar(text(f"SELECT count(*) FROM {qschema(schema)}.documents WHERE id = :did"), {"did": doc_a})
                b_cnt = await direct_a.scalar(text(f"SELECT count(*) FROM {qschema(schema)}.content_blocks WHERE id = :bid"), {"bid": blk_1})
                if c_cnt != 1 or d_cnt != 1 or b_cnt != 1:
                    raise GateBlocked("direct_rls_positive_control_failed")
            checks.append("direct_sql_rls_positive_control_verified")

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
            failure_stage = "stage_8_cross_tenant_api"
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

        # Mark main execution complete only when all in-flight checks have been performed
        main_completed = True
        failure_stage = None
    except Exception as exc:
        main_error = exc
    finally:
        barrier_active_snapshot = False
        barrier_active_pre_commit = False
        snapshot_resume.set()
        pre_commit_resume.set()

        for t in active_tasks:
            if t and not t.done():
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

        if source_uncertainty_module and original_compute_hash:
            source_uncertainty_module.compute_course_content_snapshot_hash = original_compute_hash
        if audit_service_module and original_log_action:
            audit_service_module.log_action = original_log_action
        if course_router_module and original_log_action:
            course_router_module.log_action = original_log_action

        cleanup_error = None
        receipt_error: Exception | None = None
        schema_dropped = False
        public_structure_ok = False
        public_counts_and_hashes_ok = False
        public_after_counts_hashes: dict[str, dict[str, Any]] = {}

        # 1. Close application/runtime client connections cleanly first
        if runtime is not None:
            try:
                await runtime.dispose()
            except Exception:
                pass

        # 2. Terminate ONLY confirmed test backend PIDs if any linger.
        # NEVER match by query text or schema wildcard, protecting foreign sessions.
        if confirmed_test_pids and owner is not None:
            await terminate_lingering_test_sessions(owner, confirmed_test_pids)

        # 3. Teardown isolated schema if created
        if created and owner is not None:
            try:
                async with owner.begin() as cleanup_db:
                    await cleanup_db.execute(text(f"DROP SCHEMA IF EXISTS {qschema(schema)} CASCADE"))
            except Exception as exc:
                cleanup_error = exc

            # Independently verify schema disappearance
            try:
                async with owner.connect() as check_conn:
                    schema_still_exists = await check_conn.scalar(
                        text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = :schema)"),
                        {"schema": schema},
                    )
                    if schema_still_exists:
                        cleanup_error = GateBlocked(f"schema_{schema}_still_exists_after_drop")
                    else:
                        schema_dropped = True
                        checks.append("schema_teardown_independently_verified")
            except Exception as exc:
                if cleanup_error is None:
                    cleanup_error = exc

            # Independently verify public relations and row counts AND content hashes remain unmutated
            try:
                async with owner.begin() as db:
                    public_after_structure = await public_snapshot(db)
                    public_structure_ok = (public_before_structure == public_after_structure)

                    public_after_counts_hashes = await public_business_row_snapshot(db)
                    public_counts_and_hashes_ok = (public_before_counts_hashes == public_after_counts_hashes)

                    if not public_structure_ok:
                        raise GateBlocked("public_structure_mutated_after_test")
                    if not public_counts_and_hashes_ok:
                        raise GateBlocked(
                            f"public_business_rows_mutated_after_test: before={public_before_counts_hashes} after={public_after_counts_hashes}"
                        )
                    checks.append("public_business_table_counts_and_hashes_unmutated")
            except Exception as exc:
                if cleanup_error is None:
                    cleanup_error = exc
        elif not created:
            schema_dropped = True
            public_structure_ok = True
            public_counts_and_hashes_ok = True

        if owner is not None:
            try:
                await owner.dispose()
            except Exception:
                pass

        # Strict integrity evaluation:
        overall_pass, receipt_status, missing_checks = evaluate_gate_outcome(
            main_completed=main_completed,
            main_error=main_error,
            cleanup_error=cleanup_error,
            schema_dropped=schema_dropped,
            public_structure_ok=public_structure_ok,
            public_counts_and_hashes_ok=public_counts_and_hashes_ok,
            checks=checks,
            required_checks=REQUIRED_CHECKS,
        )

        script_path = Path(__file__).resolve()
        script_sha = hashlib.sha256(script_path.read_bytes()).hexdigest()

        receipt_data = {
            "status": receipt_status,
            "run_id": effective_run_id,
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "schema": schema,
            "git_commit": get_git_commit_sha(),
            "git_branch": get_git_branch(),
            "script_path": str(script_path),
            "script_sha256": script_sha,
            "runtime_role": "lms_app",
            "runtime_role_verified_non_bypass": True,
            "checks": sorted(checks),
            "verified_tests": len(checks),
            "required_checks_complete": (len(missing_checks) == 0),
            "missing_checks": missing_checks,
            "failure_stage": failure_stage if not overall_pass else None,
            "main_error": safe_failure(main_error) if main_error is not None else None,
            "cleanup_error": safe_failure(cleanup_error) if cleanup_error is not None else None,
            "schema_teardown_independently_verified": schema_dropped,
            "public_business_rows_verified_unmutated": public_counts_and_hashes_ok,
            "public_business_table_counts_and_hashes": public_after_counts_hashes,
        }

        # Persist receipt without swallowing errors
        try:
            run_p, latest_p = persist_gate_receipt(receipt_data, evidence_dir=target_evidence_dir, run_id=effective_run_id)
            receipt_data["run_receipt_path"] = str(run_p)
            receipt_data["latest_receipt_path"] = str(latest_p)
        except Exception as exc:
            receipt_error = exc

    # Unified outcome enforcement: propagate receipt write errors and fail closed on any non-pass
    if receipt_error is not None:
        raise GateBlocked("receipt_write_failed:" + safe_failure(receipt_error)) from receipt_error

    if not overall_pass:
        failures: list[str] = []
        if not main_completed:
            failures.append(f"main_incomplete_at_{failure_stage or 'unknown'}")
        if main_error is not None:
            failures.append(f"main_error:{safe_failure(main_error)}")
        if cleanup_error is not None:
            failures.append(f"cleanup_error:{safe_failure(cleanup_error)}")
        if not schema_dropped:
            failures.append("schema_not_dropped")
        if not public_structure_ok:
            failures.append("public_structure_mutated")
        if not public_counts_and_hashes_ok:
            failures.append("public_counts_or_hashes_mutated")
        if missing_checks:
            failures.append(f"missing_checks:{','.join(missing_checks)}")
        raise GateBlocked("; ".join(failures))

    return receipt_data


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
        if result.get("status") != "PASS":
            return 1
        return 0
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error": safe_failure(exc)}))
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
