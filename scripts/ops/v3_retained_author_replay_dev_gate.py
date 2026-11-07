"""Synthetic retained-author transaction gate; offline unless explicitly enabled.

No HTTP or provider calls. Source verification is a synthetic fixture, not a
claim about real document provenance or a complete course generation.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
DEV_REF_SHA256 = "5b535773cb7222384bbb54ad3f8c2e741fa6176bec4ce586abcd82d17ee0062e"
AUTHOR_OUTPUT_TOKENS = 16384
AUTHOR_GROUP = f"practical:author:editorial:v31:output={AUTHOR_OUTPUT_TOKENS}"
ENABLED = False
_STAGE = "not_started"
_FAILURE_DIAGNOSTIC: dict[str, str] = {}


def fixture_actor_uuid(value: Any) -> UUID:
    """Normalize the database driver's UUID subclass for the strict receipt constructor."""
    return UUID(str(value))


def source_digest() -> str:
    roots = (ROOT / "apps/api/app", ROOT / "apps/api/alembic", ROOT / "scripts/ops")
    files = {p for root in roots for p in root.rglob("*.py") if "__pycache__" not in p.parts}
    values = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def _exercise(owner: Any, runtime: Any, schema: str, tenant_a: Any, tenant_b: Any,
                   job_a: str, resume_job: str, checks: list[str]) -> None:
    global _STAGE
    if not ENABLED:
        raise RuntimeError("gate_not_enabled")
    del owner, schema, resume_job
    from copy import deepcopy
    from unittest.mock import patch
    from uuid import uuid4

    import ai_generation_checkpoint_dev_check as canonical
    from app.models.registry import load_all_models
    from app.models.ai_job import AIJob
    from app.modules.ai.delivery_ownership import delivery_id
    from app.modules.ai.job_service import (AIJobSubmissionUnavailableError, InMemoryAIJobDispatcher,
        claim_generation_execution, resume_interrupted_ai_job)
    from app.modules.ai.managed_luna_client import ManagedLunaClient
    from app.modules.ai.managed_response_rejection import ManagedResponseRejectedError
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    from app.modules.ai.v3.managed_rejection_quarantine import KEY, private_key, private_plan, retain_managed_rejection
    from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
    from app.modules.ai.v3.pending_stage_transactions import claim_with_pending, finalize_pending
    from app.modules.ai.v3.practical_contract import _course_format
    from app.modules.ai.v3.response_contracts import response_contract_hash
    from app.modules.ai.v3.retained_author_replay import AUTHORIZATION_KEY, AUTHORIZATION_POLICY, owned_candidate
    from app.modules.ai.v3.stage_checkpoint import _digest, stage_once, stage_plan
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy.orm import configure_mappers

    _STAGE = "model_initialization"
    load_all_models()
    configure_mappers()
    sessions = async_sessionmaker(runtime, expire_on_commit=False)
    _STAGE = "fixture_job"
    async with sessions() as session:
        await canonical.set_tenant(session, tenant_a)
        job = await session.scalar(select(AIJob).where(AIJob.id == job_a).with_for_update())
        if job is None:
            raise AssertionError("fixture_job_missing")
        actor = fixture_actor_uuid(job.user_id)
        job.status = "running"
        job.params = {"source_analysis": {"generation_engine": "evidence_v3", "analysis_mode": "direct_source"}}
        job.result = {}
        await session.commit()

    _STAGE = "client_and_plan"
    source = "a" * 64
    journal = PendingStageJournal(str(tenant_a), actor, job_a, sessions)
    client = ManagedLunaClient(base_url="http://10.77.77.2:18999/v1", api_key="synthetic-only",
        tenant_id=tenant_a, user_id=actor, job_id=job_a, credential_revision="synthetic", model="gpt-6-luna")
    messages = [{"role": "user", "content": "Synthetic source only."}]
    fmt = _course_format(["SRC1"])
    plan = stage_plan(journal, stage="lesson", group_id=AUTHOR_GROUP,
        source_sha256=source, route_fingerprint=client.cache_fingerprint(), messages=messages, response_format=fmt)
    digest = _digest(plan)
    claim_key, result_key = "v3-stage-claim:" + digest, "v3-stage-result:" + digest
    marker = {"identity": digest, "claim_token": "c" * 32}
    async def verify(_session: Any, _job: Any, candidate_plan: dict[str, Any]) -> bool:
        return candidate_plan == plan and candidate_plan.get("source_sha256") == source

    journal.verify_source = verify
    async def initial_ownership() -> bool:
        return True  # Synthetic fixture only; the actual replay rechecks the journal and source.

    _STAGE = "prepare_synthetic_request"
    capability = await client.prepare(messages, max_output_tokens=AUTHOR_OUTPUT_TOKENS,
                                      ownership_checkpoint=initial_ownership, response_format=fmt)
    wire_hash = hashlib.sha256(client._prepared[capability]).hexdigest()
    client.discard(capability)
    question = {"id": "q1", "prompt": "Synthetic?", "choices": ["A", "B", "C"], "correct_index": 0,
                "explanation": "Synthetic.", "source_refs": ["SRC1"]}
    response = {"title": "Synthetic", "lessons": [
        {"id": "l1", "title": "One", "content": "Text", "questions": [question]},
        {"id": "l2", "title": "Two", "content": "Text", "questions": [question]}]}
    raw = json.dumps({"model": "gpt-6-luna", "structured_output_policy": "typed-json-object-v1",
        "response_format_sha256": response_contract_hash(fmt), "choices": [{"message": {"content": json.dumps(response)}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 2}}).encode()
    options = dict(journal=journal, user_id=actor, plan=plan, claim_key=claim_key, result_key=result_key,
                   marker=marker, validate=lambda value: value["response"], verify_source=verify)
    token = delivery_id.set(job_a)
    try:
        _STAGE = "initial_pending_claim"
        if await claim_with_pending(**options) is not None:
            raise AssertionError("initial_claim_invalid")
        _STAGE = "construct_synthetic_rejection"
        rejection = ManagedResponseRejectedError(raw=raw, tenant_id=tenant_a, user_id=actor,
            job_id=job_a, stage=digest, route_fingerprint=plan["route_fingerprint"], wire_request_sha256=wire_hash,
            phase="structured_shape", cause=ValueError("synthetic"), configured_model="gpt-6-luna")
        _STAGE = "retain_synthetic_rejection"
        await retain_managed_rejection(journal=journal, plan=plan, claim_key=claim_key, result_key=result_key,
                                       marker=marker, rejection=rejection, verify_source=verify)
        async with sessions() as session:
            await canonical.set_tenant(session, tenant_a)
            job = await session.scalar(select(AIJob).where(AIJob.id == job_a).with_for_update())
            candidate = await owned_candidate(session, job)
            if candidate is None:
                raise AssertionError("candidate_missing")
            original_reference = deepcopy(job.result[KEY])
            original_receipt = deepcopy(candidate["receipt"])
            job.status = "interrupted"
            await session.commit()
        _STAGE = "concurrent_resume"
        dispatcher = InMemoryAIJobDispatcher()
        async def resume() -> bool:
            async with sessions() as session:
                await canonical.set_tenant(session, tenant_a)
                row = await session.scalar(select(AIJob).where(AIJob.id == job_a))
                try:
                    await resume_interrupted_ai_job(session, job=row, tenant_id=tenant_a,
                        task_kwargs={"job_id": job_a, "tenant_id": str(tenant_a)}, active_limit=8,
                        worker_concurrency=2, historical_estimate_seconds=1, dispatcher=dispatcher)
                    return True
                except AIJobSubmissionUnavailableError:
                    await session.rollback()
                    return False
        resumed = await asyncio.gather(resume(), resume())
        if sorted(resumed) != [False, True] or len(dispatcher.submissions) != 1:
            raise AssertionError("resume_not_unique")
        delivery = dispatcher.submissions[0][1]
        authorization = {"policy": AUTHORIZATION_POLICY, "stage": digest,
            "body_sha256": candidate["body_sha256"], "pending_sha256": candidate["pending_sha256"],
            "delivery_id": delivery}
        async with sessions() as session:
            await canonical.set_tenant(session, tenant_a)
            job = await session.scalar(select(AIJob).where(AIJob.id == job_a))
            if job.params.get(AUTHORIZATION_KEY) != authorization or job.result.get("delivery_task_id") != delivery:
                raise AssertionError("resume_authorization_invalid")
        async def claim(delivery_value: str, tenant: Any) -> bool:
            async with sessions() as session:
                return await claim_generation_execution(session, job_a, str(tenant), delivery_value)
        if await claim(str(uuid4()), tenant_a) or await claim(delivery, tenant_b):
            raise AssertionError("foreign_claim_allowed")
        _STAGE = "concurrent_delivery_claim"
        claims = await asyncio.gather(claim(delivery, tenant_a), claim(delivery, tenant_a))
        if sorted(claims) != [False, True]:
            raise AssertionError("delivery_claim_not_unique")
        checks.append("one_resume_one_delivery_claim_and_foreign_denied")
        delivery_id.reset(token)
        token = delivery_id.set(delivery)
        audit = {"policy": AUTHORIZATION_POLICY, "stage_sha256": digest,
                 "body_sha256": candidate["body_sha256"], "wire_request_sha256": wire_hash, "model": "gpt-6-luna"}
        value = {"identity": digest, "response": {"synthetic": True}, "direct_metadata": {
            "model": "gpt-6-luna", "usage": {"input_tokens": 7, "output_tokens": 2}}}

        async def snapshot() -> tuple[Any, Any]:
            async with sessions() as session:
                await canonical.set_tenant(session, tenant_a)
                row = await session.scalar(select(AIJob).where(AIJob.id == job_a))
                return deepcopy(row.result), deepcopy(row.params)

        _STAGE = "finalize_rollback_checks"
        before = await snapshot()
        for bad in ({**audit, "body_sha256": "e" * 64}, {**audit, "stage_sha256": "e" * 64},
                    {**audit, "wire_request_sha256": "e" * 64}):
            try:
                await finalize_pending(**options, value=value, replay_audit=bad)
            except ExtractionOutcomeUnknownError:
                pass
            else:
                raise AssertionError("bad_audit_allowed")
            if await snapshot() != before:
                raise AssertionError("rollback_changed_job")
        async def invalid_source(_session: Any, _job: Any, _plan: Any) -> bool:
            return False
        try:
            await finalize_pending(**(options | {"verify_source": invalid_source}), value=value, replay_audit=audit)
        except ExtractionOutcomeUnknownError:
            pass
        else:
            raise AssertionError("source_drift_allowed")
        if await snapshot() != before:
            raise AssertionError("source_rollback_changed_job")
        validations = 0
        def late_failure(item: dict[str, Any]) -> dict[str, Any]:
            nonlocal validations
            validations += 1
            if validations == 2:
                raise ValueError("synthetic_readback_failure")
            return item["response"]
        try:
            await finalize_pending(**(options | {"validate": late_failure}), value=value, replay_audit=audit)
        except ExtractionOutcomeUnknownError:
            pass
        else:
            raise AssertionError("late_failure_not_held")
        if validations != 2 or await snapshot() != before:
            raise AssertionError("late_failure_job_changed")
        async with sessions() as session:
            await canonical.set_tenant(session, tenant_a)
            saved = await journal.read_owned_value_in_session(session, result_key, plan)
            receipt = await journal.read_owned_value_in_session(session, private_key(digest), private_plan(plan))
            if saved is not None or receipt != original_receipt:
                raise AssertionError("late_failure_checkpoint_changed")
        checks.append("audit_and_source_failure_rollback")
        async def forbidden(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("unexpected_provider_call")
        client.invoke = forbidden
        stage_args = dict(stage="lesson", group_id=plan["group_id"], source_sha256=source,
            route_fingerprint=client.cache_fingerprint(), messages=messages, response_format=fmt,
            invoke=forbidden, direct_client=client, direct_max_output_tokens=AUTHOR_OUTPUT_TOKENS)
        _STAGE = "replay_and_drift_checks"
        with patch("app.modules.ai.managed_luna_client.httpx.AsyncClient", side_effect=AssertionError("HTTP forbidden")):
            foreign_actor = PendingStageJournal(str(tenant_a), uuid4(), job_a, sessions, verify_source=verify)
            try:
                await stage_once(foreign_actor, **stage_args)
            except ExtractionOutcomeUnknownError:
                pass
            else:
                raise AssertionError("foreign_actor_replay_allowed")
            async with sessions() as session:
                await canonical.set_tenant(session, tenant_b)
                if await session.scalar(select(AIJob.id).where(AIJob.id == job_a)) is not None:
                    raise AssertionError("foreign_tenant_job_visible")
            for field in ("stage", "body_sha256", "pending_sha256"):
                async with sessions() as session:
                    await canonical.set_tenant(session, tenant_a)
                    row = await session.scalar(select(AIJob).where(AIJob.id == job_a).with_for_update())
                    row.params = {**row.params, AUTHORIZATION_KEY: {**authorization, field: "e" * 64}}
                    await session.commit()
                try:
                    await stage_once(journal, **stage_args)
                except ExtractionOutcomeUnknownError:
                    pass
                else:
                    raise AssertionError("drifted_authorization_allowed")
                async with sessions() as session:
                    await canonical.set_tenant(session, tenant_a)
                    row = await session.scalar(select(AIJob).where(AIJob.id == job_a).with_for_update())
                    row.params = {**row.params, AUTHORIZATION_KEY: authorization}
                    await session.commit()
                if await snapshot() != before:
                    raise AssertionError("drifted_authorization_changed_job")
            for altered in ({"source_sha256": "f" * 64}, {"route_fingerprint": "f" * 64},
                            {"group_id": "practical:author:editorial:v31"},
                            {"messages": [{"role": "user", "content": "Changed."}]}):
                try:
                    await stage_once(journal, **(stage_args | altered))
                except ExtractionOutcomeUnknownError:
                    pass
                else:
                    raise AssertionError("changed_request_allowed")
            if await snapshot() != before:
                raise AssertionError("changed_request_changed_job")
            replayed = await stage_once(journal, **stage_args)
            if await stage_once(journal, **stage_args) != response:
                raise AssertionError("cold_replay_changed_response")
        if replayed != response:
            raise AssertionError("replay_changed_response")
        checks.append("marker_source_route_request_drift_no_http")
        async with sessions() as session:
            await canonical.set_tenant(session, tenant_a)
            job = await session.scalar(select(AIJob).where(AIJob.id == job_a))
            saved = await journal.read_owned_value_in_session(session, result_key, plan)
            receipt = await journal.read_owned_value_in_session(session, private_key(digest), private_plan(plan))
            if (job.result.get(KEY) != original_reference or receipt != original_receipt
                    or job.result.get("v3_retained_author_replay_audit") != audit
                    or saved.get("response") != response or saved.get("direct_metadata", {}).get("usage", {}).get("input_tokens") != 7
                    or saved.get("direct_metadata", {}).get("usage", {}).get("output_tokens") != 2):
                raise AssertionError("final_receipts_changed")
        try:
            await finalize_pending(**options, value=value, replay_audit=audit)
        except ExtractionOutcomeUnknownError:
            pass
        else:
            raise AssertionError("duplicate_finalize_allowed")
        checks.append("atomic_result_audit_usage_and_quarantine_unchanged")
    finally:
        client.close()
        delivery_id.reset(token)


async def exercise(owner: Any, runtime: Any, schema: str, tenant_a: Any, tenant_b: Any,
                   job_a: str, resume_job: str, checks: list[str]) -> None:
    global _STAGE
    _STAGE = "entry"
    _FAILURE_DIAGNOSTIC.clear()
    try:
        await _exercise(owner, runtime, schema, tenant_a, tenant_b, job_a, resume_job, checks)
    except Exception as exc:
        _FAILURE_DIAGNOSTIC.update({"stage": _STAGE, "error_class": type(exc).__name__})
        if type(exc) is ValueError and str(exc) in {"managed_rejection_invalid", "managed_luna_config_invalid",
                "managed_luna_request_invalid", "managed_luna_structured_format_invalid", "v3_pending_claim_invalid",
                "v3_pending_owner_invalid"}:
            _FAILURE_DIAGNOSTIC["error_code"] = str(exc)
        raise


async def execute_candidate(expected_source: str, expected_base: str, custody: Path) -> dict[str, Any]:
    if not ENABLED or source_digest() != expected_source:
        raise ValueError("source_identity_invalid")
    import ai_generation_realization_dev_check as base
    from dotenv import dotenv_values
    from kb_rag_isolated_dev_gate import normalize_database_url, same_supabase_project, supabase_project_ref
    from sqlalchemy.engine import make_url

    evidence = (ROOT / ".release-evidence" / "dev").resolve(strict=True)
    result_path = custody.with_suffix(".result.json")
    if (custody.exists() or custody.is_symlink() or result_path.exists() or result_path.is_symlink()
            or custody.parent.resolve(strict=True) != evidence):
        raise ValueError("custody_invalid")
    for parent in (custody.parent, *custody.parent.parents):
        if parent.is_symlink():
            raise ValueError("custody_invalid")
    env_file = base.canonical_env_file()
    if env_file.is_symlink():
        raise ValueError("environment_invalid")
    config = dotenv_values(env_file)
    url = config.get("SUPABASE_URL") or ""
    ref = supabase_project_ref(url)
    owner = normalize_database_url(config.get("MIGRATION_DATABASE_URL") or "")
    runtime = normalize_database_url(config.get("DATABASE_URL") or "")
    def exact_role(value: str, role: str) -> bool:
        parsed = make_url(value)
        return parsed.database == "postgres" and ((parsed.host == f"db.{ref}.supabase.co" and parsed.username == role)
            or ((parsed.host or "").endswith(".pooler.supabase.com") and parsed.username == f"{role}.{ref}"))
    if (hashlib.sha256(ref.encode("ascii")).hexdigest() != DEV_REF_SHA256
            or not all(same_supabase_project(value, url) for value in (owner, runtime))
            or not exact_role(owner, "postgres") or not exact_role(runtime, "lms_app")):
        raise ValueError("environment_invalid")
    previous = base.exercise
    try:
        base.exercise = exercise
        result = await base.execute(env_file=env_file, revision="0186", expected_source=expected_base, custody_path=custody)
    finally:
        base.exercise = previous
    expected = {"runtime_role_restricted", "migration_upgrade_downgrade_reupgrade", "rls_force_and_acl",
                "one_resume_one_delivery_claim_and_foreign_denied", "audit_and_source_failure_rollback",
                "marker_source_route_request_drift_no_http", "atomic_result_audit_usage_and_quarantine_unchanged"}
    safe_result: dict[str, Any] = {key: result.get(key) is True for key in
        ("passed", "cleanup", "shared_migration_head_unchanged", "source_unchanged")}
    safe_result["source_sha256"] = expected_source
    safe_result["public_revision"] = "0186"
    checks = result.get("checks")
    safe_result["checks"] = [check for check in checks if isinstance(check, str) and check in expected] if isinstance(checks, list) else []
    for key in ("error_type", "cleanup_error_type", "failed_check"):
        value = result.get(key)
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", value):
            safe_result[key] = value
    if _FAILURE_DIAGNOSTIC:
        safe_result["fixture_failure"] = dict(_FAILURE_DIAGNOSTIC)
    with result_path.open("x", encoding="utf-8") as handle:
        json.dump(safe_result, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    if (source_digest() != expected_source or any(result.get(k) is not True for k in
            ("passed", "cleanup", "shared_migration_head_unchanged", "source_unchanged"))
            or set(result.get("checks", ())) != expected or len(result["checks"]) != len(expected)):
        raise ValueError("gate_incomplete")
    return result


def main(argv: list[str] | None = None) -> int:
    global ENABLED
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
            "project_sha256": DEV_REF_SHA256, "required_public_revision": "0186",
            "limitations": ["no HTTP", "synthetic source verifier", "private-body tampering covered by unit tests only",
                            "no real course or provider acceptance"]}))
        return 0
    if (sys.flags.optimize or args.confirm != "RUN_SYNTHETIC_RETAINED_AUTHOR_REPLAY_DEV"
            or args.expected_public_revision != "0186" or args.custody_path is None
            or not re.fullmatch(r"[0-9a-f]{64}", args.expected_source_sha256)
            or not re.fullmatch(r"[0-9a-f]{64}", args.expected_base_sha256)):
        print(json.dumps({"status": "BLOCKED", "reason": "exact_execution_arguments_required"}))
        return 2
    sys.path.insert(0, str(ROOT / "apps/api"))
    try:
        ENABLED = True
        result = asyncio.run(execute_candidate(args.expected_source_sha256, args.expected_base_sha256, args.custody_path))
        print(json.dumps({"status": "PASS", "checks": sorted(result["checks"]),
            "source_sha256": args.expected_source_sha256, "cleanup": result["cleanup"],
            "shared_migration_head_unchanged": result["shared_migration_head_unchanged"],
            "public_revision": "0186", "source_unchanged": result["source_unchanged"]}))
        return 0
    except Exception:
        print(json.dumps({"status": "BLOCKED", "reason": "gate_failed_or_identity_unverified"}))
        return 1
    finally:
        ENABLED = False


if __name__ == "__main__":
    raise SystemExit(main())
