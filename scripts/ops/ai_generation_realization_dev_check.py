"""Synthetic realization repository gate using the canonical isolated DEV schema.

No provider, customer-course or public migration writes. Default mode is offline.
The checkpoint gate owns migration/RLS/cleanup; this adapter exercises the actual
WorkerCycleJournal with JSONB, cold instances and delivery ownership.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATHS = (
    "apps/api/app/modules/ai/evidence_engine/application.py",
    "apps/api/app/modules/ai/worker_lesson_cycle.py",
    "apps/api/app/modules/ai/lesson_surface_review.py",
    "apps/api/app/modules/ai/generation_checkpoint.py",
    "apps/api/app/modules/ai/delivery_ownership.py",
    "scripts/ops/ai_generation_checkpoint_dev_check.py",
    "scripts/ops/ai_generation_realization_dev_check.py",
)


def source_digest() -> str:
    rows = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_PATHS}
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def canonical_env_file() -> Path:
    result = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=ROOT, check=True, capture_output=True, text=True)
    return Path(result.stdout.strip()).resolve(strict=True).parent / ".env"


async def exercise(owner: Any, runtime: Any, schema: str, tenant_a: Any, tenant_b: Any,
                   job_a: str, resume_job: str, checks: list[str]) -> None:
    del owner, schema
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models.registry import load_all_models
    from app.modules.ai.delivery_ownership import delivery_id
    from app.modules.ai.generation_checkpoint import AIGenerationCheckpointError
    from app.modules.ai.worker_lesson_cycle import REALIZATION_POLICY, WorkerCycleJournal
    from sqlalchemy.orm import configure_mappers

    load_all_models()
    configure_mappers()
    sessions = async_sessionmaker(runtime, expire_on_commit=False)
    journal = WorkerCycleJournal(str(tenant_a), job_a, sessions)
    plan = {"kind": REALIZATION_POLICY, "tenant_id": str(tenant_a), "job_id": job_a,
            "lesson_id": "synthetic", "ordinal": 0, "prefix_digest": "synthetic-prefix"}
    value = {"kind": REALIZATION_POLICY, "realization_plan": plan,
             "lesson": {"content": "Synthetic source-owned lesson.", "fact_ids": ["synthetic-fact"]},
             "assessment": {"questions": [], "audit": {"coverage": {"requires_review": True}}}}
    assert await journal.read_owned_realization("new-realization", plan) is None, "cold_start"
    checks.append("cold_start")
    token = delivery_id.set(job_a)
    try:
        await journal.prepare("complete", plan)
        await journal.save_value("complete", value)
        await journal.prepare("incomplete", plan)
    finally:
        delivery_id.reset(token)
    cold = WorkerCycleJournal(str(tenant_a), job_a, sessions)
    assert await cold.read_owned_realization("complete", plan) == value, "jsonb_cold_restore"
    try:
        await cold.read_owned_realization("incomplete", plan)
    except ValueError as exc:
        assert str(exc) == "worker_cycle_realization_checkpoint_incomplete", "incomplete_reason"
    else:
        raise AssertionError("incomplete_accepted")
    checks.extend(("jsonb_cold_restore", "incomplete_rejected"))
    for key, replacement in (("ordinal", 1), ("prefix_digest", "foreign-prefix"),
                             ("tenant_id", str(tenant_b)), ("job_id", resume_job)):
        try:
            await cold.read_owned_realization("complete", {**plan, key: replacement})
        except ValueError as exc:
            assert str(exc) == "worker_cycle_realization_plan_changed", "drift_reason"
        else:
            raise AssertionError("drift_accepted")
    checks.append("identity_drift_rejected")
    assert await WorkerCycleJournal(str(tenant_b), job_a, sessions).read_owned_realization("complete", plan) is None, "cross_tenant"
    assert await WorkerCycleJournal(str(tenant_a), resume_job, sessions).read_owned_realization("complete", plan) is None, "cross_job"
    checks.extend(("cross_tenant", "cross_job"))
    token = delivery_id.set("foreign-delivery")
    try:
        from app.modules.ai.delivery_ownership import DeliveryOwnershipLostError

        try:
            await cold.prepare("foreign-write", plan)
        except DeliveryOwnershipLostError:
            pass
        else:
            raise AssertionError("stale_write_accepted")
    finally:
        delivery_id.reset(token)
    assert await cold.read_owned_realization("foreign-write", plan) is None, "stale_plan_created"
    checks.append("stale_delivery_denied")
    # An actual missing repository plan remains distinguishable from corruption.
    assert issubclass(AIGenerationCheckpointError, RuntimeError)


async def execute(*, env_file: Path, revision: str, expected_source: str, custody_path: Path) -> dict[str, Any]:
    if sys.flags.optimize or source_digest() != expected_source:
        raise ValueError("source_identity_invalid")
    import ai_generation_checkpoint_dev_check as canonical

    original_exercise = canonical.exercise_runtime
    original_validate = canonical.validate_schema
    schema_name = None

    def with_custody(schema: str) -> str:
        nonlocal schema_name
        value = original_validate(schema)
        if schema_name is None:
            with custody_path.open("x", encoding="utf-8") as handle:
                json.dump({"state": "CREATE_INTENT", "schema": value,
                           "source_sha256": expected_source}, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            schema_name = value
        elif schema_name != value:
            raise ValueError("schema_identity_changed")
        return value

    try:
        canonical.exercise_runtime = exercise
        canonical.validate_schema = with_custody
        result = await canonical.run(env_file, revision)
    finally:
        canonical.exercise_runtime = original_exercise
        canonical.validate_schema = original_validate
    result["source_unchanged"] = source_digest() == expected_source
    result["source_sha256"] = expected_source
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-public-revision")
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--custody", type=Path)
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "OFFLINE_PREFLIGHT", "network_attempted": False,
                          "source_sha256": source_digest()}))
        return 0
    try:
        if args.custody is None or not args.custody.parent.is_dir() or args.custody.is_symlink():
            raise ValueError("custody_parent_missing")
        evidence_root = (ROOT / ".release-evidence").resolve(strict=True)
        if not args.custody.resolve().is_relative_to(evidence_root):
            raise ValueError("custody_outside_evidence")
        sys.path.insert(0, str(ROOT / "apps" / "api"))
        result = asyncio.run(execute(env_file=canonical_env_file(),
            revision=args.expected_public_revision, expected_source=args.expected_source_sha256,
            custody_path=args.custody))
        safe = {key: result.get(key) is True for key in
                ("passed", "cleanup", "shared_migration_head_unchanged", "source_unchanged")}
        allowed = {"runtime_role_restricted", "migration_upgrade_downgrade_reupgrade", "rls_force_and_acl",
                   "cold_start", "jsonb_cold_restore", "incomplete_rejected", "identity_drift_rejected",
                   "cross_tenant", "cross_job", "stale_delivery_denied"}
        output = {"status": "PASS" if all(safe.values()) else "BLOCKED", **safe,
                  "checks": [check for check in result.get("checks", ()) if check in allowed],
                  "source_sha256": result["source_sha256"]}
        if not all(safe.values()):
            output["error_class"] = result.get("error_type", "unavailable")
            check = result.get("failed_check")
            output["failed_check"] = check if isinstance(check, str) and check.isidentifier() else "unavailable"
        print(json.dumps(output))
        return 0 if all(safe.values()) else 1
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error_class": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
