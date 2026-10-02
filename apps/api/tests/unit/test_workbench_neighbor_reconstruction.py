"""Owned source-binding contracts; no database or application mutations."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts/ops"))
    spec = importlib.util.spec_from_file_location(
        "neighbor_reconstruction_contract", ROOT / "scripts/ops/workbench_neighbor_reconstruction.py"
    )
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.mark.parametrize(
    "schema", ["public", "workbench_abc", "workbench_123456789abc;DROP", "workbench_123456789abcd"]
)
def test_schema_is_exact_owned_only(module, schema):
    with pytest.raises(module.GateBlocked, match="neighbor_schema_invalid"):
        module.owned_schema(schema)


def test_all_26_known_policy_sources_resolve_without_runtime_ddl(module):
    # Independent declared source identities; no ignored runtime artifact required.
    groups = {
        "content_releases": ["privileged_tenant_purge_delete", "privileged_tenant_purge_select", "tenant_isolation"],
        "course_assignment_notification_outbox": [
            "course_notification_owner_select",
            "course_notification_owner_insert",
            "course_notification_owner_update",
        ],
        "courses": ["tenant_isolation", "courses_superadmin_session"],
        "departments": [
            "privileged_tenant_purge_delete",
            "privileged_tenant_purge_select",
            "tenant_organization_units_isolation",
        ],
        "enrollment_access_policies": ["enrollment_access_policies_tenant"],
        "enrollments": ["tenant_isolation", "enrollments_superadmin_session"],
        "positions": ["tenant_isolation"],
        "tenant_settings": ["tenant_isolation"],
        "tenants": ["service_access", "tenants_superadmin_session"],
        "user_invitations": ["tenant_isolation", "user_invitations_public_pending_lookup"],
        "user_roles": ["tenant_isolation"],
        "users": [
            "tenant_isolation",
            "users_auth_email_lookup",
            "users_auth_email_lookup_function_owner",
            "users_platform_superadmin_login",
            "users_superadmin_session",
        ],
    }
    assert sum(len(names) for names in groups.values()) == 26
    for table, name in [(table, name) for table, names in groups.items() for name in names]:
        sql = module.policy_sql({"relname": table, "polname": name, "roles": ["postgres"]}, "postgres")
        assert sql.lstrip().startswith("CREATE POLICY")
        assert name in sql


def test_all_nine_full_function_and_trigger_sources_resolve(module):
    assert len(module.TRIGGER_SOURCES) == len(module.TRIGGER_DEFINITIONS) == 9
    for name, source in module.TRIGGER_SOURCES.items():
        sql = module.select_source(*source, "FUNCTION", name)
        assert "RETURNS trigger" in sql and "$$" in sql
    for name, source in module.TRIGGER_DEFINITIONS.items():
        sql = module.select_source(*source, "TRIGGER", name)
        assert "FOR EACH ROW" in sql and "EXECUTE FUNCTION" in sql


@pytest.mark.parametrize("table", ["documents", "learning_paths", "learning_path_courses", "learning_path_assignments", "recurring_learning_assignments"])
def test_target_select_policy_sources_are_exact_and_bounded(module, table):
    sql = module.policy_sql({"relname": table, "polname": "tenant_isolation"}, "postgres")
    assert f"ON {table}" in sql
    assert "app.tenant_id" in sql


def test_current_purge_dependency_uses_latest_0141_source(module):
    sql = module.select_source("0141_superadmin_content_release_purge.py", "upgrade", "FUNCTION", "privileged_tenant_purge_authorized")
    assert "AND current_user = database_owner" in sql
    assert "session_user = database_owner" not in sql


def test_source_rebase_changes_only_controlled_namespace(module):
    schema = "workbench_123456789abc"
    ddl = module.select_source(
        "0161_organization_hierarchy_v2.py", "_unit_trigger_sql", "FUNCTION", "validate_organization_unit_v2"
    )
    owned = module.rebase(ddl, schema, kind="FUNCTION")
    assert 'SET search_path="workbench_123456789abc",pg_temp' in owned
    assert '"public".' not in owned and '"public",' not in owned
    assert module.normalize(owned, schema) == module.normalize(ddl, "public")


def test_unknown_policy_or_source_name_is_fail_closed(module):
    with pytest.raises(module.GateBlocked, match="neighbor_policy_source_unknown"):
        module.policy_sql({"relname": "users", "polname": "unexpected", "roles": ["public"]}, "postgres")
    with pytest.raises(module.GateBlocked, match="neighbor_source_definition_ambiguous"):
        module.select_source("0045_rls_superadmin_session_scope.py", "upgrade", "POLICY", "unexpected", table="users")


@pytest.mark.asyncio
async def test_catalog_runs_only_five_parameterized_local_selects(module):
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(mappings=lambda: [])))
    assert await module.catalog(db, "workbench_123456789abc", ["users"]) == [[], [], [], [], []]
    assert db.execute.await_count == 6
    assert str(db.execute.await_args_list[0].args[0]) == 'SET LOCAL search_path TO "workbench_123456789abc", pg_catalog'
    for call in db.execute.await_args_list[1:]:
        sql, params = str(call.args[0]), call.args[1]
        assert sql.lstrip().startswith("SELECT")
        assert "n.nspname=:schema" in sql and ":tables" in sql
        assert params == {"schema": "workbench_123456789abc", "tables": ["users"]}


def test_literal_does_not_eval_calls(module):
    import ast

    with pytest.raises(ValueError, match="unsupported_source_expression"):
        module.literal(ast.parse("dangerous()", mode="eval").body, {})


def test_owned_function_config_normalization_preserves_semantics(module):
    assert (
        module.normalize('search_path="workbench_123456789abc", pg_temp', "workbench_123456789abc")
        == "search_path=public, pg_temp"
    )
    assert (
        module.normalize("SET search_path TO '\"workbench_123456789abc\"', 'pg_temp'", "workbench_123456789abc")
        == "SET search_path TO 'public', 'pg_temp'"
    )


def test_diagnostic_state_never_uses_error_messages(module):
    exc = RuntimeError("postgresql://secret/fixture")
    cause = RuntimeError("private driver details")
    cause.sqlstate = "23503"
    exc.__cause__ = cause
    assert module.error_state(exc) == "23503"
    assert module.error_state(RuntimeError("23503 in raw text")) is None


def test_predicate_comparison_only_ignores_postgres_printing(module):
    assert module.predicate_tokens(
        "(id = NULLIF(current_setting('app.tenant_id'::text, true), ''::text)::uuid)"
    ) == module.predicate_tokens("id = NULLIF(current_setting('app.tenant_id', true), '')::uuid")
    assert module.predicate_tokens("id = 'x' OR true") != module.predicate_tokens("id = 'x' AND true")


@pytest.mark.asyncio
async def test_upgrade_nonpolicy_drift_is_fail_closed(module, monkeypatch):
    baseline = [[{"relname": "tenants", "relrowsecurity": True, "relforcerowsecurity": False}], [], [], [], []]
    actual = [
        [{"relname": "tenants", "relrowsecurity": True, "relforcerowsecurity": True}],
        [],
        [{"target_schema": "workbench_123456789abc", "definition": "FOREIGN KEY (unexpected) REFERENCES users(id)"}],
        [],
        [],
    ]
    monkeypatch.setattr(module, "catalog", AsyncMock(return_value=actual))
    with pytest.raises(module.GateBlocked, match="neighbor_upgrade_unexpected_nonpolicy_delta"):
        await module.verify_deliberate_deltas(None, "workbench_123456789abc", [], baseline, "postgres")


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", [False, True])
async def test_expansion_readback_uses_exact_catalog_fields_and_preserves_baseline(module, monkeypatch, drift):
    baseline = [[{"relname": "tenants", "relforcerowsecurity": False}], [], [], [], []]
    actual = [[{"relname": "tenants", "relforcerowsecurity": drift}], [{
        "relname": "tenants", "polname": "tenants_bootstrap_function_owner",
        "command": "r", "roles": ["postgres"], "app_applies": False,
        "using_expr": "true", "check_expr": None,
    }], [], [], []]
    monkeypatch.setattr(module, "catalog", AsyncMock(side_effect=[baseline, actual]))
    db = SimpleNamespace(scalar=AsyncMock(return_value="postgres"))
    if drift:
        with pytest.raises(module.GateBlocked, match="expansion_changed_neighbor_controls"):
            await module.verify_compatibility_expansion(db, "workbench_123456789abc", [])
    else:
        assert await module.verify_compatibility_expansion(db, "workbench_123456789abc", []) == [
            "compatibility169_expansion_preserves_legacy_neighbor_controls"
        ]
