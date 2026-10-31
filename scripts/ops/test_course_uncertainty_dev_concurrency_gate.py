import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.ops.course_uncertainty_dev_concurrency_gate import (
    REQUIRED_CHECKS,
    GateBlocked,
    evaluate_gate_outcome,
    persist_gate_receipt,
    run_uncertainty_dev_gate,
)


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test_secret_for_jwt_auth_minimum_32_characters_long")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://postgres:fake@localhost:5432/fake")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql+asyncpg://postgres:fake@localhost:5432/fake")


ALL_CHECKS = sorted(REQUIRED_CHECKS)


def test_evaluate_gate_outcome_all_present_passes() -> None:
    overall_pass, status, missing = evaluate_gate_outcome(
        main_completed=True,
        main_error=None,
        cleanup_error=None,
        schema_dropped=True,
        public_structure_ok=True,
        public_counts_and_hashes_ok=True,
        checks=ALL_CHECKS,
    )
    assert overall_pass is True
    assert status == "PASS"
    assert missing == []


def test_evaluate_gate_outcome_missing_required_checks_fails_closed() -> None:
    # Omit one check
    partial_checks = [c for c in ALL_CHECKS if c != "schema_teardown_independently_verified"]
    overall_pass, status, missing = evaluate_gate_outcome(
        main_completed=True,
        main_error=None,
        cleanup_error=None,
        schema_dropped=True,
        public_structure_ok=True,
        public_counts_and_hashes_ok=True,
        checks=partial_checks,
    )
    assert overall_pass is False
    assert status == "BLOCKED"
    assert missing == ["schema_teardown_independently_verified"]


def test_evaluate_gate_outcome_cleanup_error_fails_closed() -> None:
    overall_pass, status, missing = evaluate_gate_outcome(
        main_completed=True,
        main_error=None,
        cleanup_error=RuntimeError("schema still exists"),
        schema_dropped=False,
        public_structure_ok=True,
        public_counts_and_hashes_ok=True,
        checks=ALL_CHECKS,
    )
    assert overall_pass is False
    assert status == "BLOCKED"


def test_evaluate_gate_outcome_schema_not_dropped_fails_closed() -> None:
    overall_pass, status, missing = evaluate_gate_outcome(
        main_completed=True,
        main_error=None,
        cleanup_error=None,
        schema_dropped=False,
        public_structure_ok=True,
        public_counts_and_hashes_ok=True,
        checks=ALL_CHECKS,
    )
    assert overall_pass is False
    assert status == "BLOCKED"


def test_evaluate_gate_outcome_public_counts_or_hashes_mutated_fails_closed() -> None:
    overall_pass, status, missing = evaluate_gate_outcome(
        main_completed=True,
        main_error=None,
        cleanup_error=None,
        schema_dropped=True,
        public_structure_ok=True,
        public_counts_and_hashes_ok=False,
        checks=ALL_CHECKS,
    )
    assert overall_pass is False
    assert status == "BLOCKED"


def test_evaluate_gate_outcome_main_error_fails_closed() -> None:
    overall_pass, status, missing = evaluate_gate_outcome(
        main_completed=False,
        main_error=ValueError("unexpected crash in stage 2"),
        cleanup_error=None,
        schema_dropped=True,
        public_structure_ok=True,
        public_counts_and_hashes_ok=True,
        checks=ALL_CHECKS,
    )
    assert overall_pass is False
    assert status == "BLOCKED"


def test_persist_gate_receipt_creates_distinct_run_and_latest_atomic(tmp_path: Path) -> None:
    receipt_data = {
        "status": "PASS",
        "schema": "uncertainty_test123",
        "timestamp_utc": "2026-10-31T12:00:00Z",
        "verified_tests": 14,
    }
    run_id = "test_run_001"
    run_p, latest_p = persist_gate_receipt(receipt_data, evidence_dir=tmp_path, run_id=run_id)

    assert run_p.exists()
    assert latest_p.exists()
    assert run_p.name == f"course-uncertainty-dev-gate-receipt-{run_id}.json"
    assert latest_p.name == "course-uncertainty-dev-gate-receipt.json"

    # Both contain exact JSON data
    run_parsed = json.loads(run_p.read_text(encoding="utf-8"))
    latest_parsed = json.loads(latest_p.read_text(encoding="utf-8"))
    assert run_parsed == receipt_data
    assert latest_parsed == receipt_data

    # No leftover temporary files
    tmp_files = list(tmp_path.glob(".tmp*"))
    assert len(tmp_files) == 0


def test_persist_gate_receipt_propagates_write_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_replace(self: Path, target: Path) -> Path:
        raise OSError("Simulated disk replacement failure")

    monkeypatch.setattr(Path, "replace", broken_replace)

    receipt_data = {"status": "PASS", "schema": "uncertainty_broken"}
    with pytest.raises(OSError, match="Simulated disk replacement failure"):
        persist_gate_receipt(receipt_data, evidence_dir=tmp_path, run_id="broken_run")


@pytest.mark.asyncio
async def test_run_uncertainty_dev_gate_missing_checks_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Pre-seed a prior PASS receipt to verify pre-run invalidation and post-run BLOCKED state
    prior_pass_path = tmp_path / "course-uncertainty-dev-gate-receipt.json"
    prior_pass_path.write_text(json.dumps({"status": "PASS", "run_id": "old_pass"}), encoding="utf-8")

    fake_owner = MagicMock()
    fake_owner.begin = MagicMock()
    fake_owner.dispose = AsyncMock()
    fake_owner.connect = MagicMock()

    # check_conn.scalar -> schema exists? False (successfully dropped)
    fake_conn = AsyncMock()
    fake_conn.scalar = AsyncMock(return_value=False)
    fake_owner.connect.return_value.__aenter__.return_value = fake_conn

    # cleanup_db execute -> None
    fake_cleanup = AsyncMock()
    fake_owner.begin.return_value.__aenter__.return_value = fake_cleanup

    fake_runtime = MagicMock()
    fake_runtime.dispose = AsyncMock()

    fixtures = {
        "tenant_a": "ta", "tenant_b": "tb", "actor_a": "aa", "author_a": "aua",
        "actor_b": "ab", "course_a": "ca", "doc_a": "da", "les_1": "l1", "blk_1": "b1",
        "doc_rev_initial": "rev0", "defect_id": "def1", "defect_desc": "defect desc",
    }

    async def fake_setup_schema(o: str, r: str, s: str, schema_name: str):
        return fake_owner, fake_runtime, fixtures, True, {}, {}

    monkeypatch.setattr("scripts.ops.course_uncertainty_dev_concurrency_gate.setup_schema", fake_setup_schema)
    monkeypatch.setattr("scripts.ops.course_uncertainty_dev_concurrency_gate.public_snapshot", AsyncMock(return_value={}))
    monkeypatch.setattr("scripts.ops.course_uncertainty_dev_concurrency_gate.public_business_row_snapshot", AsyncMock(return_value={}))

    # Force a missing check in the execution by raising GateBlocked or causing incomplete checks
    with pytest.raises(GateBlocked, match="missing_checks:"):
        await run_uncertainty_dev_gate("owner_url", "runtime_url", "supabase_url", evidence_dir=tmp_path, run_id="run_fail_1")

    # Verify latest receipt is now BLOCKED (NOT old PASS!)
    latest_data = json.loads(prior_pass_path.read_text(encoding="utf-8"))
    assert latest_data["status"] == "BLOCKED"
    assert latest_data["required_checks_complete"] is False


@pytest.mark.asyncio
async def test_run_uncertainty_dev_gate_receipt_write_error_propagates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_owner = MagicMock()
    fake_owner.begin = MagicMock()
    fake_owner.dispose = AsyncMock()
    fake_owner.connect = MagicMock()
    fake_conn = AsyncMock()
    fake_conn.scalar = AsyncMock(return_value=False)
    fake_owner.connect.return_value.__aenter__.return_value = fake_conn
    fake_cleanup = AsyncMock()
    fake_owner.begin.return_value.__aenter__.return_value = fake_cleanup

    fake_runtime = MagicMock()
    fake_runtime.dispose = AsyncMock()
    fixtures = {
        "tenant_a": "ta", "tenant_b": "tb", "actor_a": "aa", "author_a": "aua",
        "actor_b": "ab", "course_a": "ca", "doc_a": "da", "les_1": "l1", "blk_1": "b1",
        "doc_rev_initial": "rev0", "defect_id": "def1", "defect_desc": "defect desc",
    }

    async def fake_setup_schema(o: str, r: str, s: str, schema_name: str):
        return fake_owner, fake_runtime, fixtures, True, {}, {}

    monkeypatch.setattr("scripts.ops.course_uncertainty_dev_concurrency_gate.setup_schema", fake_setup_schema)
    monkeypatch.setattr("scripts.ops.course_uncertainty_dev_concurrency_gate.public_snapshot", AsyncMock(return_value={}))
    monkeypatch.setattr("scripts.ops.course_uncertainty_dev_concurrency_gate.public_business_row_snapshot", AsyncMock(return_value={}))

    # Let init_marker succeed, but make final persist_gate_receipt fail
    real_persist = persist_gate_receipt
    calls = 0

    def fail_second_persist(receipt_data, *, evidence_dir=None, run_id=None):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OSError("Simulated filesystem write error during final receipt save")
        return real_persist(receipt_data, evidence_dir=evidence_dir, run_id=run_id)

    monkeypatch.setattr("scripts.ops.course_uncertainty_dev_concurrency_gate.persist_gate_receipt", fail_second_persist)

    with pytest.raises(GateBlocked, match="receipt_write_failed:"):
        await run_uncertainty_dev_gate("owner_url", "runtime_url", "supabase_url", evidence_dir=tmp_path, run_id="run_write_err")
