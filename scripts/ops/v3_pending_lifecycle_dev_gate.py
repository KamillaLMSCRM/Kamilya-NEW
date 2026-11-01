"""Atomic-claim DEV gate candidate with explicit exact-input execution boundary.

The real journal and PostgreSQL transactions are used by the exercise body;
there is no provider invocation. Do not infer executed or production evidence.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXECUTION_ENABLED = False
DEV_REF_SHA256 = "5b535773cb7222384bbb54ad3f8c2e741fa6176bec4ce586abcd82d17ee0062e"


def source_digest() -> str:
    files = {p for root in (ROOT / "apps/api/app", ROOT / "apps/api/alembic", ROOT / "scripts/ops")
             for p in root.rglob("*.py") if "__pycache__" not in p.parts}
    manifest = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def exercise(owner: Any, runtime: Any, schema: str, tenant_a: Any, tenant_b: Any,
                   job_a: str, _resume_job: str, checks: list[str]) -> None:
    if not EXECUTION_ENABLED:
        raise RuntimeError("pending_lifecycle_gate_unreviewed")
    import ai_generation_checkpoint_dev_check as canonical
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.models.ai_job import AIJob
    from app.models.registry import load_all_models
    from app.modules.ai.delivery_ownership import delivery_id
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    from app.modules.ai.v3.pending_stage_transactions import (
        claim_with_pending, finalize_pending, pending_sql_predicate,
    )
    from app.modules.ai.v3.stage_checkpoint import _digest
    from app.modules.ai.worker_lesson_cycle import WorkerCycleJournal

    canonical.validate_schema(schema)
    load_all_models()
    sessions = async_sessionmaker(runtime, expire_on_commit=False)
    async with runtime.begin() as conn:
        await canonical.set_tenant(conn, tenant_a)
        user_id = (await conn.execute(text(f'SELECT user_id FROM "{schema}".ai_jobs WHERE id=:id'),
                                      {"id": job_a})).scalar_one()
        await conn.execute(text(f'UPDATE "{schema}".ai_jobs SET params=CAST(:params AS json) WHERE id=:id'),
            {"id": job_a, "params": json.dumps({"source_analysis": {"generation_engine": "evidence_v3"}})})
    for payload, expected in (
        (None, False),
        ("null", False),
        ("{}", False),
        ('{"unrelated":true}', False),
        ('{"unrelated":{"v3_pending_stages":null}}', False),
        ('{"v3_pending_stages":null}', True),
        ('{"v3_pending_stages":{}}', True),
        ("[]", True),
        ('["v3_pending_stages"]', True),
        ('"synthetic"', True),
        ("42", True),
        ("true", True),
    ):
        async with sessions() as session:
            await canonical.set_tenant(session, tenant_a)
            await session.execute(text(f'UPDATE "{schema}".ai_jobs SET result=CAST(:value AS json) WHERE id=:id'),
                                  {"value": payload, "id": job_a})
            actual = await session.scalar(select(pending_sql_predicate()).where(AIJob.id == job_a))
            if actual is not expected:
                raise AssertionError("pending_presence_truth_invalid")
            await session.commit()
    checks.append("sql_null_absent_json_null_truth")
    async with runtime.begin() as conn:
        await canonical.set_tenant(conn, tenant_a)
        await conn.execute(text(f'UPDATE "{schema}".ai_jobs SET result=CAST(:value AS json) WHERE id=:id'),
                           {"value": json.dumps({"resume_count": 0}), "id": job_a})
    journal = WorkerCycleJournal(str(tenant_a), job_a, sessions)
    plan = {"tenant_id": str(tenant_a), "job_id": job_a, "kind": "synthetic-gate"}
    digest = _digest(plan)
    marker = {"identity": digest, "claim_token": "a" * 32}
    def validate(value: dict[str, Any]) -> dict[str, Any]:
        if value.get("identity") != digest or value.get("response") != {"synthetic": True}:
            raise ValueError("pending_gate_result_invalid")
        return value["response"]
    args = dict(journal=journal, user_id=user_id, plan=plan, result_key="pending-gate-result",
                claim_key="pending-gate-claim", marker=marker, validate=validate)
    token = delivery_id.set(job_a)
    try:
        if await claim_with_pending(**args) is not None:
            raise AssertionError("pending_initial_claim_invalid")
        try:
            await claim_with_pending(**args)
        except ExtractionOutcomeUnknownError as exc:
            if str(exc) != "v3_pending_existing":
                raise AssertionError("pending_duplicate_wrong_failure") from exc
        else:
            raise AssertionError("pending_duplicate_claim_accepted")
        async with sessions() as session:
            await canonical.set_tenant(session, tenant_b)
            if await session.scalar(select(AIJob.id).where(AIJob.id == job_a)) is not None:
                raise AssertionError("pending_foreign_tenant_visible")
        try:
            await finalize_pending(**(args | {"user_id": __import__("uuid").uuid4()}),
                                   value={"identity": digest, "response": {"synthetic": True}})
        except ExtractionOutcomeUnknownError as exc:
            if not isinstance(exc.__cause__, ValueError) or str(exc.__cause__) != "v3_pending_owner_invalid":
                raise AssertionError("pending_foreign_user_wrong_failure") from exc
        else:
            raise AssertionError("pending_foreign_user_accepted")
        async with sessions() as session:
            await canonical.set_tenant(session, tenant_a)
            if await session.scalar(select(pending_sql_predicate()).where(AIJob.id == job_a)) is not True:
                raise AssertionError("pending_foreign_user_marker_lost")
        result = await finalize_pending(**args, value={"identity": digest, "response": {"synthetic": True}})
        if result != {"synthetic": True}:
            raise AssertionError("pending_finalize_result_invalid")
        async with sessions() as session:
            await canonical.set_tenant(session, tenant_a)
            if await session.scalar(select(pending_sql_predicate()).where(AIJob.id == job_a)) is not False:
                raise AssertionError("pending_marker_not_cleared")
        # Hold the first transaction after its job lock, then start a distinct
        # claim in another session before permitting the first commit.
        from contextlib import asynccontextmanager

        locked, release, second_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
        pids: dict[str, int] = {}
        race_plan = {**plan, "kind": "synthetic-race-first"}
        race_digest = _digest(race_plan)
        race_args = args | {"plan": race_plan, "result_key": "pending-race-result-1",
                            "claim_key": "pending-race-claim-1",
                            "marker": {"identity": race_digest, "claim_token": "b" * 32}}
        second_plan = {**plan, "kind": "synthetic-race-second"}
        second_args = args | {"plan": second_plan, "result_key": "pending-race-result-2",
                              "claim_key": "pending-race-claim-2",
                              "marker": {"identity": _digest(second_plan), "claim_token": "c" * 32}}

        async def hold_first(_session: Any, _job: Any, _plan: Any) -> bool:
            pids["first"] = int(await _session.scalar(text("SELECT pg_backend_pid()")))
            locked.set()
            await release.wait()
            return True

        @asynccontextmanager
        async def second_session() -> Any:
            async with sessions() as session:
                pids["second"] = int(await session.scalar(text("SELECT pg_backend_pid()")))
                second_started.set()
                yield session

        second_journal = WorkerCycleJournal(str(tenant_a), job_a, second_session)
        second_args["journal"] = second_journal

        async def second_claim() -> Any:
            return await claim_with_pending(**second_args)

        async def run_race() -> None:
            first = asyncio.create_task(claim_with_pending(**race_args, verify_source=hold_first))
            second = None
            try:
                await locked.wait()
                second = asyncio.create_task(second_claim())
                await second_started.wait()
                async with runtime.connect() as observer:
                    blocked = False
                    for _ in range(50):
                        if second.done():
                            raise AssertionError("pending_race_second_not_blocked")
                        blocked = bool(await observer.scalar(text(
                            "SELECT :first = ANY(pg_blocking_pids(:second))"), pids))
                        if blocked:
                            break
                        await asyncio.sleep(0.1)
                    if not blocked:
                        raise AssertionError("pending_race_blocking_unverified")
                release.set()
                if await first is not None:
                    raise AssertionError("pending_race_first_not_claimed")
                try:
                    await second
                except ExtractionOutcomeUnknownError as exc:
                    if str(exc) != "v3_pending_existing":
                        raise AssertionError("pending_race_wrong_failure") from exc
                else:
                    raise AssertionError("pending_race_second_claimed")
            finally:
                release.set()
                for task in (first, second):
                    if task is not None and not task.done():
                        task.cancel()
                await asyncio.gather(*(task for task in (first, second) if task is not None), return_exceptions=True)

        await asyncio.wait_for(run_race(), timeout=20)
        def validate_race(value: dict[str, Any]) -> dict[str, Any]:
            if value.get("identity") != race_digest or value.get("response") != {"synthetic": True}:
                raise ValueError("pending_race_result_invalid")
            return value["response"]
        race_args["validate"] = validate_race
        race_value = {"identity": race_digest, "response": {"synthetic": True}}
        if await finalize_pending(**race_args, value=race_value) != {"synthetic": True}:
            raise AssertionError("pending_race_finalize_invalid")
        if await claim_with_pending(**race_args) != {"synthetic": True}:
            raise AssertionError("pending_race_replay_invalid")
        checks.append("concurrent_distinct_digest_claim_fenced")
        checks.extend(("owned_sequential_duplicate_finalize", "foreign_tenant_user_denied"))
    finally:
        delivery_id.reset(token)


async def execute_candidate(*, expected_source: str, expected_base_source: str, custody_path: Path) -> dict[str, Any]:
    """Canonical custody candidate; blocked outside exact-input CLI execution."""
    if not EXECUTION_ENABLED:
        raise RuntimeError("pending_lifecycle_gate_unreviewed")
    import ai_generation_realization_dev_check as base
    from dotenv import dotenv_values
    from kb_rag_isolated_dev_gate import normalize_database_url, same_supabase_project, supabase_project_ref
    from sqlalchemy.engine import make_url

    if source_digest() != expected_source:
        raise ValueError("pending_lifecycle_source_mismatch")
    evidence_root = (ROOT / ".release-evidence" / "dev").resolve(strict=True)
    if custody_path.exists() or custody_path.is_symlink() or custody_path.parent.resolve(strict=True) != evidence_root:
        raise ValueError("pending_lifecycle_custody_path_invalid")
    cursor = custody_path.parent
    while cursor != cursor.parent:
        if cursor.is_symlink():
            raise ValueError("pending_lifecycle_custody_path_invalid")
        cursor = cursor.parent
    env_file = base.canonical_env_file()
    if env_file.is_symlink():
        raise ValueError("pending_lifecycle_environment_invalid")
    config = dotenv_values(env_file)
    url = config.get("SUPABASE_URL") or ""
    ref = supabase_project_ref(url)
    owner = normalize_database_url(config.get("MIGRATION_DATABASE_URL") or "")
    runtime = normalize_database_url(config.get("DATABASE_URL") or "")
    def exact_role(value: str, role: str) -> bool:
        parsed = make_url(value)
        return parsed.database == "postgres" and (
            (parsed.host == f"db.{ref}.supabase.co" and parsed.username == role)
            or ((parsed.host or "").endswith(".pooler.supabase.com") and parsed.username == f"{role}.{ref}"))
    if (hashlib.sha256(ref.encode("ascii")).hexdigest() != DEV_REF_SHA256
            or not all(same_supabase_project(item, url) for item in (owner, runtime))
            or not exact_role(owner, "postgres") or not exact_role(runtime, "lms_app")):
        raise ValueError("pending_lifecycle_environment_invalid")
    original = base.exercise
    try:
        base.exercise = exercise
        result = await base.execute(env_file=env_file, revision="0184", expected_source=expected_base_source,
                                    custody_path=custody_path)
    finally:
        base.exercise = original
    expected = {"runtime_role_restricted", "migration_upgrade_downgrade_reupgrade", "rls_force_and_acl",
                "sql_null_absent_json_null_truth", "owned_sequential_duplicate_finalize", "foreign_tenant_user_denied",
                "concurrent_distinct_digest_claim_fenced"}
    checks = result.get("checks")
    if (source_digest() != expected_source or result.get("source_unchanged") is not True
            or result.get("passed") is not True or result.get("cleanup") is not True
            or result.get("shared_migration_head_unchanged") is not True or not isinstance(checks, list)
            or len(checks) != len(expected) or set(checks) != expected):
        raise ValueError("pending_lifecycle_gate_incomplete")
    return result


def main(argv: list[str] | None = None) -> int:
    global EXECUTION_ENABLED
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--expected-public-revision", default="")
    parser.add_argument("--expected-source-sha256", default="")
    parser.add_argument("--expected-base-sha256", default="")
    parser.add_argument("--custody-path", type=Path)
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({"status": "OFFLINE_ONLY", "source_sha256": source_digest(),
                          "project_sha256": DEV_REF_SHA256, "required_public_revision": "0184",
                          "custody": "canonical exclusive disposable-schema record and verified cleanup required",
                          "limitations": ["no database execution", "synthetic provider", "fixture RLS only",
                              "real cancellation and reservation refund are not tested",
                              "race proves one synthetic two-session lock wait, not production worker fencing",
                              "legacy-plan migration and completed-job reconstruction untested",
                              "custody parent must be controlled; pathname replacement race remains"]}, sort_keys=True))
        return 0
    if (args.confirm != "RUN_SYNTHETIC_PENDING_LIFECYCLE_DEV" or args.expected_public_revision != "0184"
            or args.custody_path is None or not re.fullmatch(r"[0-9a-f]{64}", args.expected_source_sha256)
            or not re.fullmatch(r"[0-9a-f]{64}", args.expected_base_sha256)):
        print(json.dumps({"status": "BLOCKED", "reason": "exact_execution_arguments_required"}))
        return 2
    try:
        EXECUTION_ENABLED = True
        result = asyncio.run(execute_candidate(expected_source=args.expected_source_sha256,
            expected_base_source=args.expected_base_sha256, custody_path=args.custody_path))
        print(json.dumps({"status": "PASS", "source_sha256": args.expected_source_sha256,
                          "checks": sorted(result["checks"]), "cleanup": True,
                          "public_revision_unchanged": True}, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({"status": "BLOCKED", "reason": "gate_failed_or_identity_unverified"}))
        return 1
    finally:
        EXECUTION_ENABLED = False


if __name__ == "__main__":
    raise SystemExit(main())
