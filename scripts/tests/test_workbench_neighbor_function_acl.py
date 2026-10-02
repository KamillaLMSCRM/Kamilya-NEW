"""Database-free contract tests for neighbor function ACL readback."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops"))
from workbench_neighbor_function_acl import (  # noqa: E402
    EXPECTED_FUNCTIONS,
    FUNCTION_ACL_QUERY,
    inspect_function_acl,
)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _DB:
    def __init__(self, rows):
        self.rows = rows
        self.statement = None
        self.params = None

    async def execute(self, statement, params):
        self.statement = str(statement)
        self.params = params
        return _Result(self.rows)


def rows_for(schema="workbench_0123456789ab"):
    return [
        {
            "function_schema": schema,
            "function_name": spec.name,
            "identity_arguments": spec.identity_arguments,
            "function_owner": "postgres",
            "owner_superuser": True,
            "owner_bypassrls": True,
            "security_definer": spec.security_definer if spec.security_definer is not None else False,
            "language": spec.language or "plpgsql",
            "proconfig": ["search_path=pg_catalog, pg_temp"],
            "public_execute_acl": spec.public_execute,
            "app_execute": spec.app_execute,
            "app_execute_acl": spec.app_execute_acl,
            "owner_execute_acl": True,
            "definition": f'CREATE FUNCTION "{schema}".{spec.name}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$',
        }
        for spec in EXPECTED_FUNCTIONS
    ]


def test_query_is_parameterized_and_catalog_acl_complete():
    assert ":schema" in FUNCTION_ACL_QUERY and ":function_names" in FUNCTION_ACL_QUERY
    assert "oidvectortypes" in FUNCTION_ACL_QUERY
    assert "has_function_privilege('lms_app'" in FUNCTION_ACL_QUERY
    assert "aclexplode" in FUNCTION_ACL_QUERY and "acldefault('f'" in FUNCTION_ACL_QUERY
    assert "pg_get_functiondef" in FUNCTION_ACL_QUERY


def test_owned_acl_readback_is_sanitized_and_exact():
    db = _DB(rows_for())
    result = asyncio.run(inspect_function_acl(db, "workbench_0123456789ab"))
    assert result["status"] == "PASS" and result["function_count"] == 11
    assert db.params["schema"] == "workbench_0123456789ab"
    assert "public" not in result["functions"][0]["definition_sha256"]
    assert all("definition" not in item for item in result["functions"])


@pytest.mark.parametrize("schema", ["workbench_0123456789abc", "workbench_deadbeef12;", "other"])
def test_schema_is_fail_closed(schema):
    with pytest.raises(Exception, match="schema_invalid"):
        asyncio.run(inspect_function_acl(_DB([]), schema))


def test_missing_function_is_drift():
    db = _DB(rows_for()[:-1])
    with pytest.raises(Exception, match="set_drift"):
        asyncio.run(inspect_function_acl(db, "workbench_0123456789ab"))


def test_public_acl_drift_is_rejected():
    rows = rows_for()
    rows[0]["public_execute_acl"] = not rows[0]["public_execute_acl"]
    with pytest.raises(Exception, match="public_drift"):
        asyncio.run(inspect_function_acl(_DB(rows), "workbench_0123456789ab"))


def test_owned_public_project_callee_is_rejected():
    rows = rows_for()
    rows[0]["definition"] += " SELECT public.users(id);"
    with pytest.raises(Exception, match="public_callee"):
        asyncio.run(inspect_function_acl(_DB(rows), "workbench_0123456789ab"))


def test_default_public_is_effective_but_not_direct_lms_grant():
    rows = rows_for()
    trigger = rows[0]
    assert trigger["public_execute_acl"] is True
    assert trigger["app_execute"] is True
    assert trigger["app_execute_acl"] is False
    asyncio.run(inspect_function_acl(_DB(rows), "workbench_0123456789ab", owner="postgres"))


def test_unexpected_direct_lms_grant_is_rejected():
    rows = rows_for()
    rows[0]["app_execute_acl"] = True
    with pytest.raises(Exception, match="explicit_app_drift"):
        asyncio.run(inspect_function_acl(_DB(rows), "workbench_0123456789ab"))


def test_named_argument_fixture_matches_type_only_signature():
    rows = rows_for()
    rows[-2]["identity_arguments"] = "uuid"
    rows[-1]["identity_arguments"] = "text"
    asyncio.run(inspect_function_acl(_DB(rows), "workbench_0123456789ab"))


def test_owner_identity_is_enforced():
    with pytest.raises(Exception, match="owner_identity_drift"):
        asyncio.run(inspect_function_acl(_DB(rows_for()), "workbench_0123456789ab", owner="migration"))
