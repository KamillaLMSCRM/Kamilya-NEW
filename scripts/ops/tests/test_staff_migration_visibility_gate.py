from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


OPS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "staff_migration_visibility_dev_gate",
    OPS / "staff_migration_visibility_dev_gate.py",
)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def test_case_matrix_separates_each_reference_failure() -> None:
    assert gate.CASES == (
        "valid",
        "user_wrong_tenant",
        "user_missing_position",
        "position_wrong_tenant",
        "position_missing_department",
    )
    assert gate.ORACLE_EXPECTED == {
        "valid": (0, 0),
        "user_wrong_tenant": (1, 0),
        "user_missing_position": (1, 0),
        "position_wrong_tenant": (0, 1),
        "position_missing_department": (0, 1),
    }


def test_generated_identifiers_are_strictly_bounded() -> None:
    assert gate.quote_schema("staff_owner_012345abcdef") == '"staff_owner_012345abcdef"'
    assert gate.quote_role("staff_migrator_012345abcdef") == '"staff_migrator_012345abcdef"'
    for unsafe in (
        "public",
        "staff_owner_012345ABCDEF",
        "staff_owner_012345abcdef;drop_schema",
    ):
        with pytest.raises(gate.GateBlocked):
            gate.quote_schema(unsafe)


def test_failure_output_does_not_expose_exception_values(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "migration-owner-red.json"
    monkeypatch.setattr(
        gate,
        "parse_args",
        lambda: SimpleNamespace(env_file=tmp_path / ".env", evidence=evidence),
    )
    monkeypatch.setattr(gate, "canonical_config", lambda _path: {"owner_url": "not-emitted"})

    async def fail(_config: dict[str, str]) -> dict[str, object]:
        raise RuntimeError("postgresql://secret-user:secret-value@secret-host/db")

    monkeypatch.setattr(gate, "run", fail)
    assert gate.main() == 2
    output = json.loads(capsys.readouterr().out)
    assert output["result"] == "BLOCKED"
    assert output["error_class"] == "RuntimeError"
    assert output["error_code"] == "RuntimeError"
    assert "secret" not in json.dumps(output)
    assert not evidence.exists()


def test_allowlisted_gate_codes_survive_but_raw_messages_do_not() -> None:
    assert gate.safe_error_code(gate.GateBlocked("case_cleanup_failed")) == "case_cleanup_failed"
    assert gate.safe_error_code(gate.GateBlocked("dsn=user:password@example.test")) == "GateBlocked"


def test_source_keeps_transactional_cleanup_and_global_neutrality_guards() -> None:
    source = (OPS / "staff_migration_visibility_dev_gate.py").read_text(encoding="utf-8")
    ast.parse(source)
    for required in (
        "await outer.rollback()",
        'require(result["cleanup"] is True, "case_cleanup_failed")',
        '"public_snapshot_changed"',
        '"public_policies_changed"',
        '"roles_or_memberships_changed"',
        '"source_changed_during_gate"',
        '"--git-common-dir"',
        "NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT",
        "migration_legacy_lock_set_mismatch",
        "valid_migration_changed_force_rls",
        '"migration-owner-green-r2.json"',
    ):
        assert required in source
    assert "DROP SCHEMA" not in source
    assert "DROP ROLE" not in source
