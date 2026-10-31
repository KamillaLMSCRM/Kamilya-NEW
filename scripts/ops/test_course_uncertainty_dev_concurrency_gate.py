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
    terminate_lingering_test_sessions,
    write_startup_in_progress_marker,
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

    async def fake_setup_schema(*args, **kwargs):
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

    async def fake_setup_schema(*args, **kwargs):
        return fake_owner, fake_runtime, fixtures, True, {}, {}

    monkeypatch.setattr("scripts.ops.course_uncertainty_dev_concurrency_gate.setup_schema", fake_setup_schema)
    monkeypatch.setattr("scripts.ops.course_uncertainty_dev_concurrency_gate.public_snapshot", AsyncMock(return_value={}))
    monkeypatch.setattr("scripts.ops.course_uncertainty_dev_concurrency_gate.public_business_row_snapshot", AsyncMock(return_value={}))

    # Make final persist_gate_receipt fail
    def fail_persist(receipt_data, *, evidence_dir=None, run_id=None):
        raise OSError("Simulated filesystem write error during final receipt save")

    monkeypatch.setattr("scripts.ops.course_uncertainty_dev_concurrency_gate.persist_gate_receipt", fail_persist)

    with pytest.raises(GateBlocked, match="receipt_write_failed:"):
        await run_uncertainty_dev_gate("owner_url", "runtime_url", "supabase_url", evidence_dir=tmp_path, run_id="run_write_err")


def test_startup_in_progress_marker_does_not_create_run_receipt(tmp_path: Path) -> None:
    run_id = "test_run_startup_01"
    latest_path = write_startup_in_progress_marker(evidence_dir=tmp_path, run_id=run_id, schema="uncertainty_abc123")

    assert latest_path.exists()
    latest_data = json.loads(latest_path.read_text(encoding="utf-8"))
    assert latest_data["status"] == "RUNNING"
    assert latest_data["run_id"] == run_id

    # Crucial: Per-run file MUST NOT exist at startup (ensures immutability upon terminal write)
    per_run_path = tmp_path / f"course-uncertainty-dev-gate-receipt-{run_id}.json"
    assert not per_run_path.exists()


@pytest.mark.asyncio
async def test_run_uncertainty_dev_gate_early_setup_failure_persists_terminal_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pre-seed latest receipt with an initial RUNNING state
    run_id = "run_early_setup_fail"

    async def broken_setup(owner_url, runtime_url, supabase_url, schema, confirmed_pids=None):
        raise ConnectionRefusedError("Simulated database connection refused during setup")

    monkeypatch.setattr("scripts.ops.course_uncertainty_dev_concurrency_gate.setup_schema", broken_setup)

    with pytest.raises(GateBlocked, match="main_incomplete_at_setup_schema"):
        await run_uncertainty_dev_gate("owner_url", "runtime_url", "supabase_url", evidence_dir=tmp_path, run_id=run_id)

    # Verify latest receipt is now BLOCKED (NOT left in RUNNING!)
    latest_path = tmp_path / "course-uncertainty-dev-gate-receipt.json"
    assert latest_path.exists()
    latest_data = json.loads(latest_path.read_text(encoding="utf-8"))
    assert latest_data["status"] == "BLOCKED"
    assert latest_data["failure_stage"] == "setup_schema"
    assert "ConnectionRefusedError" in str(latest_data["main_error"])

    # Verify per-run receipt was created with BLOCKED terminal status
    per_run_path = tmp_path / f"course-uncertainty-dev-gate-receipt-{run_id}.json"
    assert per_run_path.exists()
    per_run_data = json.loads(per_run_path.read_text(encoding="utf-8"))
    assert per_run_data["status"] == "BLOCKED"
    assert per_run_data["failure_stage"] == "setup_schema"


@pytest.mark.asyncio
async def test_cleanup_terminates_only_confirmed_test_pids_and_never_untracked_foreign_pids() -> None:
    executed_statements = []
    executed_params = []

    mock_conn = AsyncMock()
    # Owner current backend PID is 999
    mock_conn.scalar = AsyncMock(return_value=999)

    async def mock_execute(statement, params=None):
        executed_statements.append(str(statement))
        executed_params.append(params)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(101,), (102,)]
        return mock_result

    mock_conn.execute = mock_execute

    mock_owner = MagicMock()
    mock_owner.connect.return_value.__aenter__.return_value = mock_conn

    # Test sessions recorded PIDs: 101, 102, and owner 999
    # Foreign untracked PID (e.g. 555 executing a query with the schema name) is NOT in confirmed_pids
    confirmed_pids = {101, 102, 999}
    killed_count = await terminate_lingering_test_sessions(mock_owner, confirmed_pids)

    assert killed_count == 2
    assert len(executed_statements) == 1
    sql = executed_statements[0]
    params = executed_params[0]

    # Negative check 1: SQL statement MUST NOT contain query text wildcard or schema matching
    assert "query LIKE" not in sql
    assert "LIKE" not in sql
    assert "pg_terminate_backend" in sql

    # Negative check 2: Target PIDs must contain strictly 101 and 102, NEVER owner (999) or untracked foreign (555)
    target_pids = set(params["target_pids"])
    assert target_pids == {101, 102}
    assert 999 not in target_pids
    assert 555 not in target_pids
