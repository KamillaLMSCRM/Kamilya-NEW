"""Bounded catalog reads and sanitized output; no DB required."""

import importlib.util
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def catalog(monkeypatch):
    path = ROOT / "scripts/ops/workbench_neighbor_catalog.py"
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("neighbor_catalog_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_rows(*, unscoped=True, missing=False, invalid_name=False):
    from workbench_assignment_dev_gate import TABLES

    tables = [
        {
            "relname": name,
            "relrowsecurity": True,
            "relforcerowsecurity": name != "tenants",
            "can_select": True,
            "can_insert": True,
            "can_update": True,
            "can_delete": False,
            "can_truncate": False,
            "can_references": False,
            "can_trigger": False,
        }
        for name in TABLES
    ]
    next(row for row in tables if row["relname"] == "users")["can_update"] = False
    if missing:
        tables.pop()
    policies = [
        {
            "relname": "user_invitations",
            "polname": "user_invitations_public_pending_lookup",
            "command": "r",
            "polpermissive": True,
            "roles": ["public"],
            "app_applies": True,
            "using_expr": "status='pending'" if unscoped else "tenant_id=current_tenant()",
            "check_expr": None,
        }
    ]
    fks = [
        {
            "relname": "enrollments",
            "conname": "fk_enrollments_recurring",
            "target_schema": "public",
            "target_table": "recurring_learning_assignments",
            "columns": ["recurring_assignment_id"],
            "target_columns": ["id"],
            "condeferrable": False,
            "condeferred": False,
            "convalidated": True,
            "on_update": "a",
            "on_delete": "r",
            "definition": "FOREIGN KEY (recurring_assignment_id) REFERENCES recurring_learning_assignments(id) ON DELETE RESTRICT",
        }
    ]
    triggers = [
        {
            "relname": "enrollments",
            "tgname": "unsafe;sql" if invalid_name else "enrollments_bind_content_release",
            "enabled": "O",
            "tgdeferrable": False,
            "tginitdeferred": False,
            "function_schema": "public",
            "function_name": "bind_enrollment_content_release",
            "prosecdef": False,
            "proconfig": ["search_path=public"],
            "function_owner": "postgres",
            "rolsuper": False,
            "rolbypassrls": True,
            "definition": "CREATE TRIGGER raw_marker",
            "function_definition": "FUNCTION raw_marker",
            "function_body": "BEGIN raw_marker; END",
        }
    ]
    columns = [
        {
            "relname": "users",
            "attname": "password_hash",
            "can_select": True,
            "can_insert": True,
            "can_update": True,
            "can_references": True,
        }
    ]
    return [tables, policies, fks, triggers, columns]


def configure(catalog, monkeypatch, data, *, fail=False):
    def result(rows):
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))

    owner_connection = SimpleNamespace(execute=AsyncMock(side_effect=[None, *[result(rows) for rows in data]]))
    runtime_connection = SimpleNamespace()
    if fail:
        owner_connection.execute.side_effect = RuntimeError("synthetic read failure")

    @asynccontextmanager
    async def owner_context():
        yield owner_connection

    @asynccontextmanager
    async def runtime_context():
        yield runtime_connection

    owner = SimpleNamespace(begin=owner_context, dispose=AsyncMock())
    runtime = SimpleNamespace(connect=runtime_context, dispose=AsyncMock())
    engines = iter((runtime, owner))
    monkeypatch.setattr(catalog, "create_async_engine", lambda *args, **kwargs: next(engines))
    import kb_rag_isolated_dev_gate
    import source_actuality_dev_gate

    monkeypatch.setattr(kb_rag_isolated_dev_gate, "same_supabase_project", lambda *args: True)
    verify = AsyncMock()
    monkeypatch.setattr(source_actuality_dev_gate, "verify_runtime_role", verify)
    return owner_connection, runtime_connection, owner, runtime, verify


async def execute(catalog):
    return await catalog.inspect_neighbor_catalog(
        "postgresql+asyncpg://postgres@synthetic.invalid/postgres",
        "postgresql+asyncpg://lms_app@synthetic.invalid/postgres",
        "https://synthetic.invalid",
    )


@pytest.mark.parametrize("unscoped", [True, False])
@pytest.mark.asyncio
async def test_read_only_bounded_inventory_never_claims_equivalence(catalog, monkeypatch, unscoped):
    data = fixture_rows(unscoped=unscoped)
    connection, runtime_connection, owner, runtime, verify = configure(catalog, monkeypatch, data)
    outcome = await execute(catalog)
    assert outcome["status"] == "BLOCKED" and outcome["catalog_collection"] == "PASS"
    assert outcome["neighbor_equivalence"] == "NOT_VERIFIED" and outcome["functional_gate"] == "NOT_RUN"
    assert outcome["unscoped_pending_invitation_policy"] is unscoped
    assert outcome["force_rls_missing"] == ["tenants"]
    assert outcome["external_fk_targets"] == ["public.recurring_learning_assignments"]
    assert not outcome["business_rows_read"] and not outcome["mutations"]
    assert "raw_marker" not in repr(outcome) and "status='pending'" not in repr(outcome)
    assert "password" not in repr(outcome)
    user_acl = next(row for row in outcome["column_acl"] if row["table"] == "users")
    assert user_acl["column_count"] == 1
    assert user_acl["overrides"][0]["column_sha256"] == catalog.digest("password_hash")
    assert len(user_acl["effective_acl_sha256"]) == 64
    assert user_acl["overrides"][0]["can_references"] is True
    assert all(outcome["tables"][0][key] is False for key in ("can_truncate", "can_references", "can_trigger"))
    assert outcome["triggers"][0]["function_body_sha256"] == catalog.digest(data[3][0]["function_body"])
    statements = [str(call.args[0]).strip() for call in connection.execute.call_args_list]
    assert statements[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
    assert all(
        item.startswith("SELECT") and "n.nspname='public' AND c.relname=ANY(:tables)" in item for item in statements[1:]
    )
    assert (
        "p.polcmd::text" in statements[2]
        and "k.confdeltype::text" in statements[3]
        and "t.tgenabled::text" in statements[4]
    )
    assert "NOT t.tgisinternal" in statements[4]
    assert all(f"'{privilege}'" in statements[1] for privilege in ("TRUNCATE", "REFERENCES", "TRIGGER"))
    assert "'REFERENCES'" in statements[5]
    from workbench_assignment_dev_gate import TABLES

    assert all(call.args[1] == {"tables": list(TABLES)} for call in connection.execute.call_args_list[1:])
    verify.assert_awaited_once_with(runtime_connection)
    owner.dispose.assert_awaited_once()
    runtime.dispose.assert_awaited_once()


@pytest.mark.parametrize(
    "missing,invalid_name,reason", [(True, False, "table_missing"), (False, True, "identifier_invalid")]
)
@pytest.mark.asyncio
async def test_missing_or_unsafe_catalog_fails_closed(catalog, monkeypatch, missing, invalid_name, reason):
    from kb_rag_isolated_dev_gate import GateBlocked

    _, _, owner, runtime, _ = configure(catalog, monkeypatch, fixture_rows(missing=missing, invalid_name=invalid_name))
    with pytest.raises(GateBlocked, match=reason):
        await execute(catalog)
    owner.dispose.assert_awaited_once()
    runtime.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_disposes_both_connections_after_read_failure(catalog, monkeypatch):
    _, _, owner, runtime, _ = configure(catalog, monkeypatch, [], fail=True)
    with pytest.raises(RuntimeError, match="synthetic read failure"):
        await execute(catalog)
    owner.dispose.assert_awaited_once()
    runtime.dispose.assert_awaited_once()


@pytest.mark.parametrize("value", ["public;DROP", 'x"', "pg.name", "../public", None])
def test_identifier_rejects_unsafe_metadata(catalog, value):
    from kb_rag_isolated_dev_gate import GateBlocked

    with pytest.raises(GateBlocked, match="identifier_invalid"):
        catalog.identifier(value)


def test_detailed_cli_requires_read_only_mode_before_env_access():
    source = (ROOT / "scripts/ops/workbench_assignment_dev_gate.py").read_text(encoding="utf-8")
    assert source.index("if args.catalog_details and not args.metadata_only:") < source.index(
        "config = dotenv_values(args.env_file)"
    )
    assert "operation = inspect_neighbor_catalog" in source


@pytest.mark.parametrize(
    "name",
    [
        "prevent_content_release_mutation",
        "validate_course_current_release",
        "validate_organization_unit_v2",
        "validate_enrollment_access_policy_ownership",
        "bind_enrollment_content_release",
        "validate_manual_reassignment_identity",
        "validate_recurring_enrollment_identity",
        "validate_position_import_identity",
        "validate_user_organization_unit_ownership",
    ],
)
def test_all_nine_trigger_bodies_bind_to_one_reviewed_source(catalog, name):
    result = catalog.accepted_trigger_source(name)
    assert result["path"].startswith("apps/api/alembic/versions/")
    assert len(result["body_sha256"]) == len(result["source_sha256"]) == 64


def test_unknown_trigger_is_not_guessed(catalog):
    assert catalog.accepted_trigger_source("new_unknown_trigger") is None


@pytest.mark.parametrize(
    "command,permissive,applies,expression,expected",
    [
        ("*", True, True, "(true)", "unscoped_true_policy"),
        ("r", True, True, "true", "unscoped_true_policy"),
        ("*", False, True, "true", "not_classified"),
        ("*", True, False, "true", "not_classified"),
        ("*", True, True, "true AND tenant_id=current_tenant()", "not_classified"),
        ("r", True, True, "status='pending'", "unscoped_pending_select"),
    ],
)
def test_only_exact_permissive_true_predicate_is_classified(
    catalog, command, permissive, applies, expression, expected
):
    assert catalog.classify_policy(command, permissive, applies, expression) == expected
