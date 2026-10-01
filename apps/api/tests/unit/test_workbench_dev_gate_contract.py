"""Database-free guard checks; actual queue atomicity uses the isolated DEV gate."""

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def gate(monkeypatch):
    path = ROOT / "scripts" / "ops" / "workbench_assignment_dev_gate.py"
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("workbench_gate_contract_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "name", ["public", "workbench_abc", "workbench_123456789abc;DROP", "../workbench_123456789abc"]
)
def test_gate_rejects_nonowned_schema_names(gate, name):
    with pytest.raises(gate.GateBlocked, match="unsafe_schema_name"):
        gate.safe_schema(name)


def accepted_body():
    path = ROOT / "apps" / "api" / "alembic" / "versions" / "0097_course_assignment_notification_outbox.py"
    statements = [
        node.value
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "CREATE FUNCTION enqueue_course_assignment_notification(" in node.value
    ]
    body = statements[0].split("AS $$", 1)[1].rsplit("$$", 1)[0]
    return body.replace(
        "IF NOT EXISTS (SELECT 1 FROM users WHERE id=p_assigned_by AND tenant_id=p_tenant_id) THEN",
        "IF p_assigned_by IS NOT NULL AND NOT EXISTS (SELECT 1 FROM users WHERE id=p_assigned_by AND tenant_id=p_tenant_id) THEN",
    )


@pytest.mark.asyncio
async def test_enqueue_fixture_shadows_only_owned_schema_and_revokes_direct_access(gate):
    schema = "workbench_123456789abc"
    live = SimpleNamespace(prosrc=accepted_body(), prosecdef=True, lanname="plpgsql")
    connection = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(one=lambda: live)), scalar=AsyncMock(return_value=schema)
    )
    await gate.install_isolated_enqueue(connection, schema)
    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    ddl = next(statement for statement in statements if "CREATE FUNCTION" in statement)
    assert f'CREATE FUNCTION "{schema}".enqueue_course_assignment_notification(' in ddl
    assert f'SET search_path = "{schema}", pg_temp' in ddl
    assert "SET search_path = public" not in ddl
    assert "ON CONFLICT(enrollment_id)" in ddl
    assert any(
        f'REVOKE ALL ON "{schema}".course_assignment_notification_outbox FROM PUBLIC,lms_app,lms_recovery' in statement
        for statement in statements
    )
    assert any("FORCE ROW LEVEL SECURITY" in statement for statement in statements)
    assert not any(
        "CREATE FUNCTION" in statement and ("deliver" in statement or "due_course" in statement)
        for statement in statements
    )
    assert all("GRANT" not in statement or "ON FUNCTION" in statement for statement in statements)


@pytest.mark.asyncio
async def test_live_enqueue_drift_stops_before_fixture_ddl(gate):
    live = SimpleNamespace(prosrc="different or unsafe body", prosecdef=True, lanname="plpgsql")
    connection = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(one=lambda: live)))
    with pytest.raises(gate.GateBlocked, match="live_enqueue_body_not_accepted_source"):
        await gate.install_isolated_enqueue(connection, "workbench_123456789abc")
    assert connection.execute.await_count == 1
    assert str(connection.execute.call_args.args[0]).lstrip().startswith("SELECT")


def test_failure_diagnostics_never_echo_sql_or_credentials(gate):
    error = RuntimeError("postgresql://secret-user:private-value@private-host/db with payload")
    assert gate.safe_failure(error) == "RuntimeError"
