#!/usr/bin/env python3
"""RLS-hidden-parent regression for the 0183 staff migration in isolated DEV."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool


ROOT = Path(__file__).resolve().parents[2]
API_ROOT = ROOT / "apps" / "api"
OPS_ROOT = ROOT / "scripts" / "ops"
MIGRATION = API_ROOT / "alembic" / "versions" / "0183_staff_structure_changes.py"
EVIDENCE_ROOT = ROOT / ".release-evidence" / "four-blocks64"
SCHEMA_RE = re.compile(r"^staff_owner_[0-9a-f]{12}$")
ROLE_RE = re.compile(r"^staff_migrator_[0-9a-f]{12}$")
ERROR_CODE_RE = re.compile(r"^[a-zA-Z0-9_:.-]{1,200}$")
CLONE_TABLES = (
    "tenants",
    "users",
    "user_roles",
    "departments",
    "positions",
    "enrollments",
)
LEGACY_TABLES_SQL = "'users','positions','departments'"
CASES = (
    "valid",
    "user_wrong_tenant",
    "user_missing_position",
    "position_wrong_tenant",
    "position_missing_department",
)
ORACLE_EXPECTED = {
    "valid": (0, 0),
    "user_wrong_tenant": (1, 0),
    "user_missing_position": (1, 0),
    "position_wrong_tenant": (0, 1),
    "position_missing_department": (0, 1),
}

for path in (API_ROOT, OPS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from kb_rag_isolated_dev_gate import GateBlocked, assert_sanitized_evidence  # noqa: E402
from source_actuality_dev_gate import public_snapshot  # noqa: E402
from workbench_document_dev_gate import canonical_config  # noqa: E402


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise GateBlocked(reason)


def quote_schema(value: str) -> str:
    require(bool(SCHEMA_RE.fullmatch(value)), "unsafe_schema")
    return f'"{value}"'


def quote_role(value: str) -> str:
    require(bool(ROLE_RE.fullmatch(value)), "unsafe_role")
    return f'"{value}"'


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sqlstate(exc: BaseException) -> str | None:
    original = getattr(exc, "orig", exc)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


def guard_named(exc: BaseException) -> bool:
    original = getattr(exc, "orig", exc)
    return "existing_staff_tenant_reference_mismatch" in str(original)


def safe_error_code(exc: BaseException) -> str:
    candidate = str(exc) if isinstance(exc, GateBlocked) else type(exc).__name__
    return candidate if ERROR_CODE_RE.fullmatch(candidate) else type(exc).__name__


async def apply_0183(connection: AsyncConnection, schema: str) -> None:
    quote_schema(schema)
    spec = importlib.util.spec_from_file_location("staff_visibility_0183", MIGRATION)
    require(spec is not None and spec.loader is not None, "migration_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def apply(sync_connection: Any) -> None:
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        with Operations.context(
            MigrationContext.configure(
                sync_connection, opts={"version_table_schema": schema}
            )
        ):
            module.upgrade()

    await connection.run_sync(apply)


async def role_snapshot(connection: AsyncConnection) -> tuple[tuple[Any, ...], ...]:
    rows = await connection.execute(
        text(
            "SELECT r.rolname,r.rolsuper,r.rolinherit,r.rolcreaterole,"
            "r.rolcreatedb,r.rolcanlogin,r.rolreplication,r.rolbypassrls,"
            "coalesce((SELECT array_agg(m.rolname::text ORDER BY m.rolname::text) "
            "FROM pg_auth_members am JOIN pg_roles m ON m.oid=am.roleid "
            "WHERE am.member=r.oid),ARRAY[]::text[]) "
            "FROM pg_roles r ORDER BY r.rolname"
        )
    )
    return tuple(tuple(row) for row in rows)


async def public_policy_snapshot(
    connection: AsyncConnection,
) -> tuple[tuple[Any, ...], ...]:
    rows = await connection.execute(
        text(
            "SELECT tablename,policyname,roles::text,cmd,coalesce(qual,''),"
            "coalesce(with_check,'') FROM pg_policies "
            "WHERE schemaname='public' ORDER BY tablename,policyname"
        )
    )
    return tuple(tuple(row) for row in rows)


async def legacy_policy_snapshot(
    connection: AsyncConnection, schema: str
) -> tuple[tuple[Any, ...], ...]:
    rows = await connection.execute(
        text(
            "SELECT tablename,policyname,roles::text,cmd,coalesce(qual,''),"
            "coalesce(with_check,'') FROM pg_policies WHERE schemaname=:schema "
            f"AND tablename IN ({LEGACY_TABLES_SQL}) ORDER BY tablename,policyname"
        ),
        {"schema": schema},
    )
    return tuple(tuple(row) for row in rows)


async def legacy_catalog_snapshot(
    connection: AsyncConnection, schema: str
) -> tuple[tuple[Any, ...], ...]:
    constraints = await connection.execute(
        text(
            "SELECT 'constraint',c.relname,con.conname,con.contype::text,"
            "pg_get_constraintdef(con.oid,true) FROM pg_constraint con "
            "JOIN pg_class c ON c.oid=con.conrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:schema "
            f"AND c.relname IN ({LEGACY_TABLES_SQL}) ORDER BY c.relname,con.conname"
        ),
        {"schema": schema},
    )
    indexes = await connection.execute(
        text(
            "SELECT 'index',tablename,indexname,'i',indexdef FROM pg_indexes "
            "WHERE schemaname=:schema "
            f"AND tablename IN ({LEGACY_TABLES_SQL}) ORDER BY tablename,indexname"
        ),
        {"schema": schema},
    )
    return tuple(tuple(row) for row in constraints) + tuple(
        tuple(row) for row in indexes
    )


async def legacy_row_snapshot(
    connection: AsyncConnection, schema: str
) -> tuple[tuple[Any, ...], ...]:
    q = quote_schema(schema)
    rows: list[tuple[Any, ...]] = []
    for table, columns in (
        ("users", "id::text,tenant_id::text,position_id::text"),
        ("positions", "id::text,tenant_id::text,department_id::text"),
        ("departments", "id::text,tenant_id::text,parent_id::text"),
    ):
        result = await connection.execute(
            text(f"SELECT '{table}',{columns} FROM {q}.{table} ORDER BY id")
        )
        rows.extend(tuple(row) for row in result)
    return tuple(rows)


async def create_fixture(
    connection: AsyncConnection, schema: str, role: str, case: str
) -> dict[str, int]:
    require(case in CASES, "unsupported_case")
    q, qr = quote_schema(schema), quote_role(role)
    stage = "timeouts"
    try:
        await connection.execute(text("SET LOCAL lock_timeout='5s'"))
        await connection.execute(text("SET LOCAL statement_timeout='60s'"))
        stage = "create_role"
        await connection.execute(
            text(f"CREATE ROLE {qr} NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT")
        )
        stage = "grant_role"
        await connection.execute(text(f"GRANT {qr} TO CURRENT_USER"))
        stage = "create_schema"
        await connection.execute(text(f"CREATE SCHEMA {q}"))
        await connection.execute(text(f"REVOKE ALL ON SCHEMA {q} FROM PUBLIC"))
        stage = "clone_tables"
        for table in CLONE_TABLES:
            require(bool(re.fullmatch(r"[a-z_]+", table)), "unsafe_table")
            await connection.execute(
                text(
                    f"CREATE TABLE {q}.{table} "
                    f"(LIKE public.{table} INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES)"
                )
            )

        ids = {name: uuid4() for name in ("ta", "tb", "ua", "ub", "pa", "pb", "user", "missing")}
        stage = "seed_tenants"
        await connection.execute(
            text(
                f"INSERT INTO {q}.tenants(id,name,slug,status,plan) VALUES "
                "(:ta,'Synthetic A',:sa,'active','free'),"
                "(:tb,'Synthetic B',:sb,'active','free')"
            ),
            {**ids, "sa": "staff-a-" + schema[-12:], "sb": "staff-b-" + schema[-12:]},
        )
        stage = "seed_departments"
        await connection.execute(
            text(
                f"INSERT INTO {q}.departments"
                "(id,tenant_id,name,slug,unit_type,normalized_name,legacy_root) VALUES "
                "(:ua,:ta,'Unit A','unit-a','branch','unit a',false),"
                "(:ub,:tb,'Unit B','unit-b','branch','unit b',false)"
            ),
            ids,
        )
        position_a_tenant = ids["ta"]
        position_a_department = ids["missing"] if case == "position_missing_department" else (
            ids["ub"] if case == "position_wrong_tenant" else ids["ua"]
        )
        stage = "seed_positions"
        await connection.execute(
            text(
                f"INSERT INTO {q}.positions"
                "(id,tenant_id,name,normalized_name,department,department_id,is_active) VALUES "
                "(:pa,:pat,'Position A','position a','Unit A',:pad,true),"
                "(:pb,:tb,'Position B','position b','Unit B',:ub,true)"
            ),
            {**ids, "pat": position_a_tenant, "pad": position_a_department},
        )
        user_position = ids["missing"] if case == "user_missing_position" else (
            ids["pb"] if case == "user_wrong_tenant" else ids["pa"]
        )
        stage = "seed_user"
        await connection.execute(
            text(
                f"INSERT INTO {q}.users"
                "(id,tenant_id,first_name,last_name,personnel_number,role,is_active,status,position_id) "
                "VALUES (:user,:ta,'Synthetic','Learner',:pn,'student',true,'active',:position)"
            ),
            {**ids, "pn": "VIS-" + schema[-12:], "position": user_position},
        )

        stage = "privileged_oracle"
        user_bad = int(
            await connection.scalar(
                text(
                    f"SELECT count(*) FROM {q}.users u LEFT JOIN {q}.positions p "
                    "ON p.id=u.position_id WHERE u.position_id IS NOT NULL "
                    "AND (p.id IS NULL OR u.tenant_id IS DISTINCT FROM p.tenant_id)"
                )
            )
            or 0
        )
        position_bad = int(
            await connection.scalar(
                text(
                    f"SELECT count(*) FROM {q}.positions p LEFT JOIN {q}.departments d "
                    "ON d.id=p.department_id WHERE p.department_id IS NOT NULL "
                    "AND (d.id IS NULL OR p.tenant_id IS DISTINCT FROM d.tenant_id)"
                )
            )
            or 0
        )
        expected = ORACLE_EXPECTED[case]
        require((user_bad, position_bad) == expected, "fixture_oracle_mismatch")

        stage = "configure_rls"
        for table in ("users", "positions", "departments"):
            await connection.execute(text(f"ALTER TABLE {q}.{table} ENABLE ROW LEVEL SECURITY"))
            await connection.execute(text(f"ALTER TABLE {q}.{table} FORCE ROW LEVEL SECURITY"))
        await connection.execute(
            text(f"CREATE POLICY migration_visible_users ON {q}.users FOR SELECT TO {qr} USING (true)")
        )
        stage = "transfer_owner_schema"
        await connection.execute(text(f"ALTER SCHEMA {q} OWNER TO {qr}"))
        for table in CLONE_TABLES:
            stage = f"transfer_owner_{table}"
            await connection.execute(text(f"ALTER TABLE {q}.{table} OWNER TO {qr}"))
        return {
            "user_reference_mismatches": user_bad,
            "position_reference_mismatches": position_bad,
        }
    except Exception as exc:
        raise GateBlocked(
            f"fixture_failed:{stage}:{type(exc).__name__}:{sqlstate(exc) or 'nostate'}"
        ) from None


async def legacy_rls_snapshot(
    connection: AsyncConnection, schema: str
) -> tuple[tuple[Any, ...], ...]:
    rows = await connection.execute(
        text(
            "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity FROM pg_class c "
            "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:schema "
            f"AND c.relname IN ({LEGACY_TABLES_SQL}) ORDER BY c.relname"
        ),
        {"schema": schema},
    )
    return tuple(tuple(row) for row in rows)


async def access_exclusive_legacy_locks(
    connection: AsyncConnection, schema: str
) -> tuple[str, ...]:
    rows = await connection.execute(
        text(
            "SELECT DISTINCT c.relname FROM pg_locks l "
            "JOIN pg_class c ON c.oid=l.relation "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE l.pid=pg_backend_pid() AND l.granted IS TRUE "
            "AND l.mode='AccessExclusiveLock' AND n.nspname=:schema "
            f"AND c.relname IN ({LEGACY_TABLES_SQL}) ORDER BY c.relname"
        ),
        {"schema": schema},
    )
    return tuple(str(row[0]) for row in rows)


async def verify_owner_seam(
    connection: AsyncConnection, schema: str, role: str
) -> dict[str, Any]:
    q, qr = quote_schema(schema), quote_role(role)
    await connection.execute(text(f"SET LOCAL ROLE {qr}"))
    identity = (
        await connection.execute(
            text(
                "SELECT current_user,rolsuper,rolbypassrls FROM pg_roles "
                "WHERE rolname=current_user"
            )
        )
    ).one()
    owners = (
        await connection.execute(
            text(
                "SELECT c.relname,r.rolname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "JOIN pg_roles r ON r.oid=c.relowner WHERE n.nspname=:schema "
                f"AND c.relname IN ({LEGACY_TABLES_SQL}) ORDER BY c.relname"
            ),
            {"schema": schema},
        )
    ).all()
    counts = {
        table: int(
            await connection.scalar(text(f"SELECT count(*) FROM {q}.{table}")) or 0
        )
        for table in ("users", "positions", "departments")
    }
    privileges = (
        await connection.scalar(
            text(
                "SELECT has_schema_privilege(current_user,:schema,'CREATE') "
                "AND has_schema_privilege(current_user,:schema,'USAGE')"
            ),
            {"schema": schema},
        )
    )
    require(identity == (role, False, False), "migration_owner_identity_mismatch")
    require(
        [tuple(row) for row in owners]
        == [("departments", role), ("positions", role), ("users", role)],
        "migration_owner_table_ownership_mismatch",
    )
    require(counts == {"users": 1, "positions": 0, "departments": 0}, "rls_visibility_not_reproduced")
    require(bool(privileges), "migration_owner_schema_privileges_missing")
    return {
        "rolsuper": False,
        "rolbypassrls": False,
        "owns_users_positions_departments": True,
        "visible_users": counts["users"],
        "visible_positions": counts["positions"],
        "visible_departments": counts["departments"],
        "schema_create": True,
        "schema_usage": True,
    }


async def absent(connection: AsyncConnection, schema: str, role: str) -> bool:
    return not bool(
        await connection.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:schema) "
                "OR EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:role)"
            ),
            {"schema": schema, "role": role},
        )
    )


async def run_case(engine: Any, case: str) -> dict[str, Any]:
    suffix = uuid4().hex[:12]
    schema, role = "staff_owner_" + suffix, "staff_migrator_" + suffix
    result: dict[str, Any] = {"case": case, "expected": "pass" if case == "valid" else "23514_named_guard"}
    case_error: BaseException | None = None
    stage = "connect"
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            try:
                stage = "collision_check"
                require(await absent(connection, schema, role), "case_identity_collision")
                stage = "create_fixture"
                result["privileged_fixture_oracle"] = await create_fixture(
                    connection, schema, role, case
                )
                stage = "baseline_snapshots"
                rows_before = await legacy_row_snapshot(connection, schema)
                policies_before = await legacy_policy_snapshot(connection, schema)
                catalog_before = await legacy_catalog_snapshot(connection, schema)
                rls_before = await legacy_rls_snapshot(connection, schema)
                require(
                    rls_before
                    == (
                        ("departments", True, True),
                        ("positions", True, True),
                        ("users", True, True),
                    ),
                    "fixture_force_rls_not_enabled",
                )
                nested = await connection.begin_nested()
                try:
                    stage = "verify_owner_seam"
                    seam = await verify_owner_seam(connection, schema, role)
                    result["owner_seam"] = seam
                    try:
                        stage = "apply_0183"
                        await apply_0183(connection, schema)
                    except Exception as exc:
                        result["migration_passed"] = False
                        result["sqlstate"] = sqlstate(exc)
                        result["named_guard"] = guard_named(exc)
                        await nested.rollback()
                        await connection.execute(text("RESET ROLE"))
                    else:
                        result["migration_passed"] = True
                        result["sqlstate"] = None
                        result["named_guard"] = False
                        stage = "valid_postchecks"
                        await connection.execute(text("RESET ROLE"))
                        locks = await access_exclusive_legacy_locks(connection, schema)
                        result["access_exclusive_legacy_locks"] = list(locks)
                        require(
                            locks == ("departments", "positions", "users"),
                            "migration_legacy_lock_set_mismatch",
                        )
                        require(
                            await legacy_rls_snapshot(connection, schema) == rls_before,
                            "valid_migration_changed_force_rls",
                        )
                        require(
                            await legacy_row_snapshot(connection, schema) == rows_before,
                            "valid_migration_changed_legacy_rows",
                        )
                        require(
                            await legacy_policy_snapshot(connection, schema) == policies_before,
                            "valid_migration_changed_legacy_policies",
                        )
                        require(
                            await legacy_catalog_snapshot(connection, schema) == catalog_before,
                            "transient_validation_catalog_retained",
                        )
                        await nested.rollback()
                finally:
                    if nested.is_active:
                        await nested.rollback()
                stage = "rollback_postchecks"
                require(
                    await legacy_row_snapshot(connection, schema) == rows_before,
                    "case_changed_legacy_rows",
                )
                require(
                    await legacy_policy_snapshot(connection, schema) == policies_before,
                    "case_changed_legacy_policies",
                )
                require(
                    await legacy_catalog_snapshot(connection, schema) == catalog_before,
                    "case_changed_legacy_catalog",
                )
                require(
                    await legacy_rls_snapshot(connection, schema) == rls_before,
                    "case_changed_force_rls",
                )
            finally:
                if outer.is_active:
                    await outer.rollback()
    except Exception as exc:
        case_error = exc
    async with engine.connect() as fresh:
        result["cleanup"] = await absent(fresh, schema, role)
    require(result["cleanup"] is True, "case_cleanup_failed")
    if case_error is not None:
        state = sqlstate(case_error) or "nostate"
        raise GateBlocked(
            f"case_execution_failed:{case}:{stage}:{safe_error_code(case_error)}:{state}"
        ) from None
    if case == "valid":
        result["accepted"] = result.get("migration_passed") is True
    else:
        result["accepted"] = (
            result.get("migration_passed") is False
            and result.get("sqlstate") == "23514"
            and result.get("named_guard") is True
        )
    return result


async def run(config: dict[str, str]) -> dict[str, Any]:
    hashes_before = {
        "gate": file_sha256(Path(__file__)),
        "migration_0183": file_sha256(MIGRATION),
    }
    engine = create_async_engine(
        config["owner_url"], poolclass=NullPool, hide_parameters=True
    )
    try:
        async with engine.connect() as connection:
            public_before = await public_snapshot(connection)
            policies_before = await public_policy_snapshot(connection)
            roles_before = await role_snapshot(connection)
        try:
            cases = [await run_case(engine, case) for case in CASES]
        except Exception as exc:
            async with engine.connect() as connection:
                public_after = await public_snapshot(connection)
                policies_after = await public_policy_snapshot(connection)
                roles_after = await role_snapshot(connection)
            require(public_after == public_before, "public_snapshot_changed_after_failure")
            require(policies_after == policies_before, "public_policies_changed_after_failure")
            require(roles_after == roles_before, "roles_or_memberships_changed_after_failure")
            require(
                {
                    "gate": file_sha256(Path(__file__)),
                    "migration_0183": file_sha256(MIGRATION),
                }
                == hashes_before,
                "source_changed_during_failed_gate",
            )
            raise GateBlocked(f"isolated_gate_failed:{safe_error_code(exc)}") from None
        async with engine.connect() as connection:
            public_after = await public_snapshot(connection)
            policies_after = await public_policy_snapshot(connection)
            roles_after = await role_snapshot(connection)
        require(public_after == public_before, "public_snapshot_changed")
        require(policies_after == policies_before, "public_policies_changed")
        require(roles_after == roles_before, "roles_or_memberships_changed")
        require(
            {
                "gate": file_sha256(Path(__file__)),
                "migration_0183": file_sha256(MIGRATION),
            }
            == hashes_before,
            "source_changed_during_gate",
        )
        valid = next(item for item in cases if item["case"] == "valid")
        invalid = [item for item in cases if item["case"] != "valid"]
        invalid_passed = all(item["accepted"] for item in invalid)
        status = "PASS" if valid["accepted"] and invalid_passed else "RED"
        return {
            "at": datetime.now(UTC).isoformat(),
            "result": status,
            "expected_current_result": "RED" if not valid["accepted"] else "PASS",
            "cases": cases,
            "checks": {
                "invalid_cases_all_rejected": invalid_passed,
                "public_snapshot_unchanged": True,
                "public_policies_unchanged": True,
                "roles_memberships_unchanged": True,
                "all_case_cleanup": all(item["cleanup"] for item in cases),
            },
            "source_sha256": hashes_before,
            "scope": "Owned synthetic Supabase DEV schemas and transactional NOLOGIN NOSUPERUSER NOBYPASSRLS roles only",
        }
    finally:
        await engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    require(args.execute, "execute_flag_required")
    git_common_dir = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    canonical_env = (Path(git_common_dir).resolve().parent / ".env").resolve()
    require(args.env_file.resolve() == canonical_env, "canonical_env_required")
    evidence = args.evidence.resolve()
    require(evidence.parent == EVIDENCE_ROOT.resolve(), "evidence_parent_invalid")
    require(
        evidence.name
        in {
            "migration-owner-red.json",
            "migration-owner-green.json",
            "migration-owner-green-r2.json",
        },
        "evidence_name_invalid",
    )
    require(not evidence.exists(), "evidence_already_exists")
    return args


def main() -> int:
    args = parse_args()
    try:
        config = canonical_config(args.env_file)
        result = asyncio.run(run(config))
    except Exception as exc:
        failure = {
            "at": datetime.now(UTC).isoformat(),
            "result": "BLOCKED",
            "error_class": type(exc).__name__,
            "error_code": safe_error_code(exc),
        }
        assert_sanitized_evidence(failure)
        print(json.dumps(failure))
        return 2
    else:
        assert_sanitized_evidence(result)
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result))
        return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
