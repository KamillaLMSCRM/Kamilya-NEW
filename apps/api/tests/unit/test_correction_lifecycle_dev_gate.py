"""Database-free safety contracts for the owned 0178 lifecycle DEV gate."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]
GATE_PATH = ROOT / "scripts/ops/workbench_correction_lifecycle_dev_gate.py"
MIGRATION_PATH = ROOT / "apps/api/alembic/versions/0178_workbench_lesson_correction_lifecycle.py"


@pytest.fixture
def gate():
    spec = importlib.util.spec_from_file_location("correction_lifecycle_dev_gate_contract", GATE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migration():
    spec = importlib.util.spec_from_file_location("correction_lifecycle_0178_gate_contract", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_rejects_noncanonical_env_before_loading_or_writing(gate, monkeypatch, capsys):
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=str(ROOT / ".git") + "\n"),
    )
    monkeypatch.setattr(gate, "canonical_config", lambda *_: pytest.fail("credentials loaded"))
    monkeypatch.setattr(
        sys,
        "argv",
        ["gate", "--env-file", str(ROOT / "wrong.env"), "--execute", "--evidence", str(ROOT / "evidence.json")],
    )

    assert gate.main() == 1
    rendered = capsys.readouterr().out
    assert '"failure": "noncanonical_env_file"' in rendered
    assert "wrong.env" not in rendered


def test_main_rejects_overwrite_or_wrong_evidence_target_before_config(gate, monkeypatch, capsys):
    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=str(ROOT / ".git") + "\n"),
    )
    monkeypatch.setattr(gate, "canonical_config", lambda *_: pytest.fail("config loaded"))
    monkeypatch.setattr(
        sys,
        "argv",
        ["gate", "--env-file", str(ROOT / ".env"), "--execute", "--evidence", str(ROOT / "wrong.json")],
    )

    assert gate.main() == 1
    assert '"failure": "invalid_evidence_target"' in capsys.readouterr().out


def test_required_check_labels_are_unique_and_exact(gate):
    from kb_rag_isolated_dev_gate import assert_sanitized_evidence

    expected = {
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
    }
    assert gate.REQUIRED_CHECKS == frozenset(expected)
    assert len(gate.REQUIRED_CHECKS) == len(expected)
    assert_sanitized_evidence({"status": "PASS", "checks": sorted(expected), "production": "UNCHANGED"})
    with pytest.raises(gate.GateBlocked, match="evidence_contains_forbidden_material"):
        assert_sanitized_evidence({"status": "PASS", "secret": "must-not-appear"})


def test_gate_wires_shared_application_callback_and_exact_migration_identity(gate):
    import inspect

    parameters = inspect.signature(gate.run_gate).parameters
    assert {"extra_migration", "verifier", "required_checks"} <= set(parameters)
    migration = _migration()
    assert migration.revision == "0178"
    assert migration.down_revision == "0177"


def test_migration_interpolates_owned_trigger_and_never_public_lifecycle_target(monkeypatch):
    migration = _migration()
    statements = []
    monkeypatch.setattr(
        migration.op,
        "get_context",
        lambda: SimpleNamespace(opts={"version_table_schema": "workbench_123456789abc"}),
    )
    monkeypatch.setattr(migration.op, "execute", statements.append)
    migration.upgrade()
    combined = "\n".join(statements)
    assert "CREATE TRIGGER lesson_correction_accounting_guard" in combined
    assert '"workbench_123456789abc".workbench_lesson_correction_accounting' in combined
    assert "public.workbench_lesson_correction_accounting" not in combined
    assert '"workbench_123456789abc".guard_lesson_correction_accounting()' in combined
