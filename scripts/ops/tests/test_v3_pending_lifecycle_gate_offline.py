"""Offline only: candidate remains fail-closed without exact execution inputs."""
import asyncio
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "scripts/ops/v3_pending_lifecycle_dev_gate.py"


def test_callable_paths_block_before_access():
    gate = runpy.run_path(str(PATH))
    assert gate["EXECUTION_ENABLED"] is False
    with pytest.raises(RuntimeError, match="unreviewed"):
        asyncio.run(gate["exercise"](None, None, "public", None, None, "job", "job2", []))
    with pytest.raises(RuntimeError, match="unreviewed"):
        asyncio.run(gate["execute_candidate"](expected_source="x", expected_base_source="x", custody_path=Path("x")))
    with pytest.raises(RuntimeError, match="unreviewed"):
        asyncio.run(gate["_exercise_budget_period"](None, None, "public", None, None))
    with pytest.raises(RuntimeError, match="unreviewed"):
        asyncio.run(gate["_exercise_revision_policy"](None, None, "public", None, None))


@pytest.mark.parametrize("arguments", [["--execute"], ["--execute", "--confirm", "RUN_SYNTHETIC_PENDING_LIFECYCLE_DEV"]])
def test_incomplete_execution_is_blocked(arguments):
    gate = runpy.run_path(str(PATH))
    assert gate["main"](arguments) == 2


def test_source_contains_real_checks_and_explicit_refund_limitation():
    source = PATH.read_text(encoding="utf-8")
    for token in ("sql_null_absent_json_null_truth", "owned_sequential_duplicate_finalize", "foreign_tenant_user_denied",
                  "pending_duplicate_claim_accepted", "public cancellation endpoint and provider billing refund are not tested"):
        assert token in source


def test_appended_checks_match_expected_gate_checks():
    import ast
    tree = ast.parse(PATH.read_text(encoding="utf-8"))
    exercise = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "exercise")
    execute = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "execute_candidate")
    names = set()
    for node in ast.walk(exercise):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "checks":
            if node.func.attr == "append":
                names.add(ast.literal_eval(node.args[0]))
            elif node.func.attr == "extend":
                names.update(ast.literal_eval(node.args[0]))
    assignment = next(node for node in execute.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "expected" for target in node.targets))
    assert names | {"runtime_role_restricted", "migration_upgrade_downgrade_reupgrade", "rls_force_and_acl"} == ast.literal_eval(assignment.value)


def test_direct_gate_installs_fake_transport_and_checks_all_boundaries():
    source = PATH.read_text(encoding="utf-8")
    for token in ("client._post = fake_post", "direct_gate_unexpected_endpoint", "direct_count_after_claim",
                  "direct_generation_without_claim", "direct_replay_called_transport",
                  "direct_count_failure_claimed", "direct_count_failure_plan_exists", "direct_unknown_retried", "direct_call_count_invalid",
                  "direct_fake_count_claim_replay_unknown"):
        assert token in source
