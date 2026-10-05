#!/usr/bin/env python3
"""Exact owned0178 proof; canonical DEV only, no public or provider writes."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "apps/api", ROOT / "scripts/ops"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dotenv import load_dotenv  # noqa: E402
from workbench_correction_application_dev_gate import run_gate  # noqa: E402
from workbench_document_dev_gate import (  # noqa: E402
    GateBlocked, canonical_config, safe_schema, sanitize_failure,
)

MIGRATION = ROOT / "apps/api/alembic/versions/0178_workbench_lesson_correction_lifecycle.py"
REQUIRED_CHECKS = frozenset({
    "catalog_fk_exact_immediate", "bounded_connection_peak", "ready_charge_replay",
    "known_failure_refund_once", "t2_rollback_no_provider", "t2_lost_ack_no_provider",
    "t3_lost_ack_ready_readback", "ledger_rls_two_tenants", "maintenance_authority",
    "ledger_identity_acl", "ledger_terminal_guard", "batch_input_bounds",
    "original_month_refund", "started_retained", "legacy_retained",
    "insufficient_aggregate_atomic", "dry_run_read_only", "bounded_ordering",
    "skip_locked_parent", "rollback_and_repeat", "late_completion_no_revival",
    "preview_24h_boundary", "receipt_90d_boundary", "receipt_visibility_protection",
    "removed_id_refused", "metadata_only_neighbor_invariant", "exact_tenant_purge",
    "populated_downgrade_refused", "empty_down_up", "populated_upgrade_no_backfill",
    "ledger_forged_admission", "malformed_accounting_atomic",
    "locked_state_action_provenance",
})
SOURCE_FILES = (
    "apps/api/alembic/versions/0178_workbench_lesson_correction_lifecycle.py",
    "apps/api/app/modules/methodologist_workbench/correction_models.py",
    "apps/api/app/modules/methodologist_workbench/correction_accounting.py",
    "apps/api/app/modules/methodologist_workbench/correction_service.py",
    "apps/api/app/modules/methodologist_workbench/correction_application.py",
    "apps/api/app/modules/admin/superadmin/service.py",
    "scripts/ops/workbench_correction_application_dev_gate.py",
    "scripts/ops/workbench_correction_lifecycle_dev_gate.py",
    "scripts/ops/workbench_correction_lifecycle_dev_checks.py",
)


def source_hashes():
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in SOURCE_FILES}


async def apply_0178(connection, schema, operation="upgrade"):
    safe_schema(schema)
    if operation not in {"upgrade", "downgrade"}:
        raise GateBlocked("invalid_migration_request")
    spec = importlib.util.spec_from_file_location("correction_lifecycle_0178", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.revision != "0178" or module.down_revision != "0177":
        raise GateBlocked("migration_identity_mismatch")

    def apply(sync):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        with Operations.context(MigrationContext.configure(sync, opts={"version_table_schema": schema})):
            getattr(module, operation)()
    await connection.run_sync(apply)


def main():
    from workbench_correction_lifecycle_dev_checks import verify_lifecycle
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    try:
        common = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        if args.env_file.resolve() != (Path(common).parent / ".env").resolve():
            raise GateBlocked("noncanonical_env_file")
        target = (ROOT / ".release-evidence/WB-CORRECTION-LIFECYCLE-20261005").resolve()
        output = args.evidence.resolve()
        if output.parent != target or output.suffix != ".json" or output.exists():
            raise GateBlocked("invalid_evidence_target")
        config = canonical_config(args.env_file)
        load_dotenv(args.env_file, override=True)
        frozen = source_hashes()
        result = asyncio.run(run_gate(
            config["owner_url"], config["runtime_url"], config["supabase_url"],
            f"workbench_{uuid4().hex[:12]}", extra_migration=apply_0178,
            verifier=verify_lifecycle, required_checks=REQUIRED_CHECKS,
            scope="workbench_correction_lifecycle_isolated_dev", migration="0178",
        ))
        result["source_sha256"] = frozen
        result["source_unchanged"] = frozen == source_hashes()
        if not result["source_unchanged"]:
            result["status"] = "BLOCKED"
            result["failure"] = "source_changed_during_gate"
        from workbench_document_dev_gate import assert_sanitized_evidence
        assert_sanitized_evidence(result)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "failure": sanitize_failure(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
