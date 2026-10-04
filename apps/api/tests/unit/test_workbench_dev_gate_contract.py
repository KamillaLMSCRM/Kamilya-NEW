"""Database-free guard checks; actual queue atomicity uses the isolated DEV gate."""

import ast
import importlib.util
from contextlib import asynccontextmanager
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


def test_organization_fixture_materializes_dependencies_before_users():
    tree = ast.parse((ROOT / "scripts/ops/workbench_assignment_dev_gate.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                    and node.name == "verify_organization_changes")
    session = next(node for node in function.body if isinstance(node, ast.AsyncWith))
    source = ast.unparse(session)
    department = source.index("Department(")
    position = source.index("Position(")
    user = source.index("User(")
    assert "await db.flush()" in source[department:position]
    assert "await db.flush()" in source[position:user]


@pytest.mark.asyncio
async def test_transaction_search_path_never_falls_back_to_public(gate):
    session = SimpleNamespace(execute=AsyncMock())
    await gate.context(session, "workbench_123456789abc", "tenant", "actor")
    path_sql = str(session.execute.call_args_list[0].args[0])
    assert path_sql == 'SET LOCAL search_path TO "workbench_123456789abc", pg_catalog'


def test_intent_fixture_reuses_settings_and_restores_only_its_owned_learner():
    source = (ROOT / "scripts/ops/workbench_intent_dev_checks.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                    and node.name == "verify_intent")
    owner_transaction = next(node for node in function.body if isinstance(node, ast.AsyncWith))
    fixture = ast.unparse(owner_transaction)
    assert "TenantSettings(" not in source
    assert ".tenant_settings SET monthly_llm_budget_usd_cents=1 WHERE tenant_id=:tenant" in fixture
    assert ".users SET status='active' WHERE id=:learner AND tenant_id=:tenant" in fixture
    assert "updated.rowcount != 1" in fixture and "restored.rowcount != 1" in fixture
    assert "learner_id" in {argument.arg for argument in function.args.args}


@pytest.mark.asyncio
async def test_required_invitation_tables_resolve_only_to_owned_schema(gate):
    schema = "workbench_123456789abc"
    connection = SimpleNamespace(scalar=AsyncMock(return_value=schema))
    await gate.verify_isolated_resolution(connection, schema)
    checked = {call.args[1]["table"] for call in connection.scalar.call_args_list}
    assert {"user_invitations", "tenant_settings", "workbench_assignment_plans"} <= checked
    assert checked == set(gate.TABLES) | {"workbench_assignment_plans"}


@pytest.mark.asyncio
async def test_missing_or_public_table_resolution_blocks_before_application(gate):
    connection = SimpleNamespace(scalar=AsyncMock(return_value="public"))
    with pytest.raises(gate.GateBlocked, match="isolated_table_resolution_mismatch"):
        await gate.verify_isolated_resolution(connection, "workbench_123456789abc")
    assert connection.scalar.await_count == 1


@pytest.mark.parametrize("expression", ["(status = 'pending'::text)", "status='pending'"])
def test_metadata_recognizes_only_exact_unscoped_pending_select(gate, expression):
    assert gate.classify_pending_policy("r", True, True, expression) == "unscoped_pending_select"


@pytest.mark.parametrize(
    "command,permissive,app,expression",
    [
        ("*", True, True, "status='pending'"),
        ("r", False, True, "status='pending'"),
        ("r", True, False, "status='pending'"),
        ("r", True, True, "status='pending' AND tenant_id=current_tenant()"),
    ],
)
def test_metadata_does_not_guess_unknown_or_restricted_policies(gate, command, permissive, app, expression):
    assert gate.classify_pending_policy(command, permissive, app, expression) == "not_classified"


@pytest.mark.asyncio
@pytest.mark.parametrize("unscoped", [True, False])
async def test_metadata_reads_catalogs_only_and_keeps_equivalence_unverified(gate, monkeypatch, unscoped):
    tables = [
        {
            "relname": name,
            "relrowsecurity": True,
            "relforcerowsecurity": True,
            "can_select": True,
            "can_insert": True,
            "can_update": True,
        }
        for name in gate.TABLES
    ]
    expression = "(status = 'pending'::text)" if unscoped else "tenant_id=current_tenant()"
    policies = [
        {
            "relname": "user_invitations",
            "polname": "user_invitations_public_pending_lookup",
            "polcmd": "r",
            "polpermissive": True,
            "app_applies": True,
            "expression": expression,
        }
    ]

    def result(rows):
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))

    owner_connection = SimpleNamespace(execute=AsyncMock(side_effect=[None, result(tables), result(policies)]))
    runtime_connection = SimpleNamespace()

    @asynccontextmanager
    async def owner_context():
        yield owner_connection

    @asynccontextmanager
    async def runtime_context():
        yield runtime_connection

    owner = SimpleNamespace(begin=owner_context, dispose=AsyncMock())
    runtime = SimpleNamespace(connect=runtime_context, dispose=AsyncMock())
    engines = iter((runtime, owner))
    monkeypatch.setattr(gate, "create_async_engine", lambda *args, **kwargs: next(engines))
    monkeypatch.setattr(gate, "same_supabase_project", lambda *args: True)
    verify = AsyncMock()
    monkeypatch.setattr(gate, "verify_runtime_role", verify)
    outcome = await gate.inspect_neighbor_metadata(
        "postgresql+asyncpg://postgres@synthetic.invalid/postgres",
        "postgresql+asyncpg://lms_app@synthetic.invalid/postgres",
        "https://synthetic.invalid",
    )
    assert outcome["status"] == ("BLOCKED" if unscoped else "PASS")
    assert outcome["unscoped_pending_invitation_policy"] is unscoped
    assert outcome["neighbor_equivalence"] == "NOT_VERIFIED"
    assert outcome["business_rows_read"] is False and outcome["mutations"] is False
    assert "expression" not in outcome["policies"][0]
    assert expression not in repr(outcome)
    statements = [str(call.args[0]) for call in owner_connection.execute.call_args_list]
    assert statements[0] == "SET TRANSACTION READ ONLY"
    assert all(sql.startswith("SELECT ") and "pg_class" in sql for sql in statements[1:])
    assert "p.polcmd::text AS polcmd" in statements[2]
    assert all(call.args[1] == {"tables": list(gate.TABLES)} for call in owner_connection.execute.call_args_list[1:])
    verify.assert_awaited_once_with(runtime_connection)
    runtime.dispose.assert_awaited_once()
    owner.dispose.assert_awaited_once()
