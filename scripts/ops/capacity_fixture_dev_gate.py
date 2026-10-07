"""Real post-commit/RLS proof in one disposable canonical Supabase DEV schema.

No public DML, providers, Redis I/O or full privileged tenant purge. The latter
is qualified by separate helper contracts and the production ordinary API smoke.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
for item in (ROOT / "apps/api", ROOT / "scripts/ops"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from kb_rag_isolated_dev_gate import file_sha256, supabase_project_ref  # noqa: E402
from source_actuality_dev_gate import public_snapshot, verify_runtime_role  # noqa: E402
from workbench_document_dev_gate import canonical_config  # noqa: E402

PROJECT_HASH = "5b535773cb7222384bbb54ad3f8c2e741fa6176bec4ce586abcd82d17ee0062e"
TRIGGERS = (
    ("departments", "validate_organization_unit_v2",
     "4bc443d12bb16a56acf041960cbcbf3237074db5b5473ac1ae6ec68f81668568"),
    ("positions", "validate_position_import_identity",
     "9c9ff06ba8856325da9e2ff97a1753fc88f34cabceae2e2ac7d6151f12c035d8"),
)
TABLES = ("tenants", "users", "departments", "positions", "position_courses",
          "department_courses", "courses", "modules", "lessons", "enrollments",
          "quiz_attempts", "progress", "certificates", "user_roles", "organization_course_rules")
SOURCE_FILES = (
    "apps/api/app/modules/users/staff_import_service.py",
    "apps/api/app/modules/positions/batch_service.py",
    "apps/api/app/modules/positions/assignment_service.py",
    "apps/api/app/modules/organization_scope/resolver.py",
    "apps/api/app/modules/admin/superadmin/service.py",
    "scripts/ops/capacity_fixture_dev_gate.py",
)
REQUIRED = frozenset({
    "actual_commit_clears_context", "real_import_rules_success",
    "no_commit_rules_control_rollback", "two_tenant_read_write_negatives",
    "owned_fk_catalog", "actual_delete_list_position_order",
    "owned_rows_zero_foreign_fixture_unchanged",
})


class GateBlocked(RuntimeError):
    """Code-owned labels only."""


def require(value, label):
    if not value:
        raise GateBlocked(label)


def safe_schema(value):
    require(bool(re.fullmatch(r"capacity_[0-9a-f]{12}", value)), "owned_schema_refused")
    return f'"{value}"'


def source_hashes():
    return {item: file_sha256(ROOT / item) for item in SOURCE_FILES}


def owned_trigger_definition(definition, expected_hash, schema):
    qualified = safe_schema(schema)
    require(hashlib.sha256(definition.encode()).hexdigest() == expected_hash,
            "public_trigger_definition_changed")
    converted = definition.replace('"public".', qualified + ".").replace("public.", qualified + ".")
    converted = converted.replace("SET search_path TO 'public', 'pg_temp'",
                                  f"SET search_path TO '{schema}', 'pg_catalog'")
    require("public" not in converted and "SECURITY DEFINER" not in converted,
            "owned_trigger_resolution_refused")
    return converted


def prepare(env_file, evidence_file):
    common = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    require(env_file.resolve() == (Path(common).parent / ".env").resolve(), "canonical_env_required")
    target = evidence_file.resolve()
    require(target.parent == (ROOT / ".release-evidence/CAPACITY-HOTFIX-20261007").resolve()
            and target.suffix == ".json" and not target.exists(), "exclusive_evidence_target_required")
    config = canonical_config(env_file)
    require(hashlib.sha256(supabase_project_ref(config["supabase_url"]).encode()).hexdigest()
            == PROJECT_HASH, "canonical_dev_project_required")
    # Existing canonical_config already pins project sameness/database/runtime.
    from sqlalchemy.engine import make_url
    require((make_url(config["owner_url"]).username or "").split(".")[0] == "postgres",
            "migration_owner_required")
    frozen = source_hashes()  # All source dependencies must exist before network.
    return config, target, frozen


async def metadata(connection):
    snapshot = await public_snapshot(connection)
    columns = (await connection.execute(text(
        "SELECT table_name,column_name,udt_name,is_nullable,coalesce(column_default,'') "
        "FROM information_schema.columns WHERE table_schema='public' AND table_name=ANY(:tables) "
        "ORDER BY table_name,ordinal_position"
    ), {"tables": list(TABLES)})).all()
    constraints = (await connection.execute(text(
        "SELECT c.relname,k.conname,k.contype,pg_get_constraintdef(k.oid),"
        "c.relrowsecurity,c.relforcerowsecurity FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace LEFT JOIN pg_constraint k ON k.conrelid=c.oid "
        "WHERE n.nspname='public' AND c.relname=ANY(:tables) ORDER BY c.relname,k.conname"
    ), {"tables": list(TABLES)})).all()
    triggers = (await connection.execute(text(
        "SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid),pg_get_functiondef(p.oid) "
        "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_proc p ON p.oid=t.tgfoid "
        "WHERE n.nspname='public' AND c.relname=ANY(:tables) AND NOT t.tgisinternal "
        "ORDER BY c.relname,t.tgname"
    ), {"tables": list(TABLES)})).all()
    return hashlib.sha256(repr((snapshot, columns, constraints, triggers)).encode()).hexdigest()


async def clone(owner, schema):
    qualified = safe_schema(schema)
    await owner.execute(text(f"CREATE SCHEMA {qualified}"))
    await owner.execute(text(f"REVOKE ALL ON SCHEMA {qualified} FROM PUBLIC"))
    await owner.execute(text(f"GRANT USAGE ON SCHEMA {qualified} TO lms_app"))
    for table in TABLES:
        await owner.execute(text(
            f"CREATE TABLE {qualified}.{table} (LIKE public.{table} INCLUDING DEFAULTS "
            "INCLUDING CONSTRAINTS INCLUDING INDEXES)"
        ))
        await owner.execute(text(f"REVOKE ALL ON {qualified}.{table} FROM PUBLIC"))
        await owner.execute(text(f"GRANT SELECT,INSERT,UPDATE,DELETE ON {qualified}.{table} TO lms_app"))
        await owner.execute(text(f"ALTER TABLE {qualified}.{table} ENABLE ROW LEVEL SECURITY"))
        await owner.execute(text(f"ALTER TABLE {qualified}.{table} FORCE ROW LEVEL SECURITY"))
        key = "id" if table == "tenants" else "tenant_id"
        await owner.execute(text(
            f"CREATE POLICY exact_tenant ON {qualified}.{table} FOR ALL TO lms_app "
            f"USING ({key}=nullif(current_setting('app.tenant_id',true),'')::uuid) "
            f"WITH CHECK ({key}=nullif(current_setting('app.tenant_id',true),'')::uuid)"
        ))
    # LIKE never copies FKs. Require actual public catalog identities/actions,
    # then recreate only these exact constraints within the disposable schema.
    fks = (await owner.execute(text(
        "SELECT c.relname,a.attname,ref.relname,fk.confdeltype::text,fk.confupdtype::text "
        "FROM pg_constraint fk JOIN pg_class c ON c.oid=fk.conrelid "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=fk.conkey[1] "
        "JOIN pg_class ref ON ref.oid=fk.confrelid "
        "WHERE n.nspname='public' AND fk.contype='f' AND "
        "((c.relname='users' AND a.attname='position_id') OR "
        "(c.relname='positions' AND a.attname='department_id')) ORDER BY c.relname"
    ))).all()
    require([tuple(row) for row in fks] == [
        ("positions", "department_id", "departments", "n", "a"),
        ("users", "position_id", "positions", "a", "a"),
    ], "public_fk_identity_or_actions_changed")
    for table, column, parent, delete_action, _update in fks:
        deletion = "SET NULL" if delete_action == "n" else "NO ACTION"
        await owner.execute(text(
            f"ALTER TABLE {qualified}.{table} ADD CONSTRAINT owned_{column}_fk "
            f"FOREIGN KEY({column}) REFERENCES {qualified}.{parent}(id) ON DELETE {deletion}"
        ))
    await owner.execute(text(f"""CREATE FUNCTION {qualified}.set_current_tenant(tid uuid)
        RETURNS void LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
        BEGIN PERFORM set_config('app.tenant_id',tid::text,true); END $$"""))
    await owner.execute(text(f"REVOKE ALL ON FUNCTION {qualified}.set_current_tenant(uuid) FROM PUBLIC"))
    await owner.execute(text(f"GRANT EXECUTE ON FUNCTION {qualified}.set_current_tenant(uuid) TO lms_app"))
    # LIKE also omits triggers. Clone only the two independently reviewed,
    # hash-pinned identity functions; all reads resolve to owned tables.
    for table, function, expected_hash in TRIGGERS:
        definition = await owner.scalar(text(
            "SELECT pg_get_functiondef(to_regprocedure(:identity))"
        ), {"identity": f"public.{function}()"})
        require(isinstance(definition, str), "public_trigger_function_missing")
        await owner.execute(text(owned_trigger_definition(definition, expected_hash, schema)))
        await owner.execute(text(f"REVOKE ALL ON FUNCTION {qualified}.{function}() FROM PUBLIC"))
        await owner.execute(text(f"GRANT EXECUTE ON FUNCTION {qualified}.{function}() TO lms_app"))
        await owner.execute(text(
            f"CREATE TRIGGER trg_{function} BEFORE INSERT OR UPDATE ON {qualified}.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION {qualified}.{function}()"
        ))


async def context(session, tenant):
    await session.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant)})


async def counts(session, tenant):
    await context(session, tenant)
    return {table: int(await session.scalar(text(
        f"SELECT count(*) FROM {table} WHERE {'id' if table == 'tenants' else 'tenant_id'}=:tid"
    ), {"tid": tenant})) for table in TABLES}


async def foreign_fingerprint(session, tenant):
    await context(session, tenant)
    rows = []
    for table in ("tenants", "users", "positions", "departments"):
        rows.extend((table, row[0]) for row in (await session.execute(text(
            f"SELECT row_to_json(t)::text FROM {table} t "
            f"WHERE {'id' if table == 'tenants' else 'tenant_id'}=:tid ORDER BY id"
        ), {"tid": tenant})).all())
    return hashlib.sha256(repr(rows).encode()).hexdigest()


def parsed(number):
    from app.modules.users.staff_import_service import ParsedFile, ParsedRow
    return ParsedFile(
        rows=[ParsedRow(row_number=2, personnel_number=f"CAP-DEV-{number}",
                       first_name="Synthetic", last_name=f"Learner{number}",
                       department="Synthetic department", position="Synthetic position")],
        total_rows_in_file=1, invalid_rows=[], detected_columns={}, missing_required_columns=[],
    )


async def service_proof(engine, schema, checks):
    from app.models.registry import load_all_models
    from app.models.tenants import Tenant
    from app.modules.admin.superadmin.service import SuperadminService
    from app.modules.users.staff_import_service import commit_import
    load_all_models()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    a, b = uuid4(), uuid4()
    # Verify real, engine-owned commit expires SET LOCAL before the actual test.
    async with factory() as session:
        await context(session, a)
        require(await session.scalar(text("SELECT current_setting('app.tenant_id',true)")) == str(a),
                "context_not_established")
        await session.commit()
        require(await session.scalar(text("SELECT nullif(current_setting('app.tenant_id',true),'')"))
                is None, "real_commit_did_not_clear_context")
        require(await session.scalar(text("SELECT current_schema()")) == schema, "owned_path_not_retained")
    checks.append("actual_commit_clears_context")
    for tid in (a, b):
        async with factory() as session:
            await context(session, tid)
            session.add(Tenant(id=tid, name="Synthetic", slug=f"capacity-{tid.hex}",
                               plan="enterprise", status="active", settings={}))
            await session.commit()

    # Only Redis progress is stubbed. Real import/batch/kernel/resolver execute.
    success, failure = AsyncMock(), AsyncMock()
    names = ("init_task", "mark_started", "increment_done", "increment_failed",
             "mark_success", "mark_failure")
    with patch.multiple("app.core.redis_progress",
                        new_task_id=lambda: f"owned-{uuid4()}",
                        **{name: (success if name == "mark_success" else failure
                                  if name == "mark_failure" else AsyncMock()) for name in names}):
        for tid, number in ((a, 1), (b, 2)):
            async with factory() as session:
                await context(session, tid)
                result = await commit_import(session, tid, parsed(number), commit_changes=True)
                require(result["created"] == 1 and result["positions_created"] == 1,
                        "actual_import_counts_refused")
                require(await session.scalar(text("SELECT current_setting('app.tenant_id',true)")) == str(tid),
                        "same_tenant_not_restored")
                await session.commit()  # rules transaction explicitly persisted.
        require(success.await_count == 2 and failure.await_count == 0, "actual_inline_rules_failed")
        for call in success.await_args_list:
            value = call.args[1]
            require(value["users_processed"] == 1 and value["added"] == value["removed"] == value["failed_chunks"] == 0,
                    "actual_rule_result_refused")
        checks.append("real_import_rules_success")
        async with factory() as session:
            await context(session, a)
            control = await commit_import(session, a, parsed(3), commit_changes=False, apply_rules=True)
            require(control["created"] == 1 and session.in_transaction(), "caller_transaction_lost")
            require(await session.scalar(text("SELECT current_setting('app.tenant_id',true)")) == str(a),
                    "no_commit_context_lost")
            require(success.await_count == 3 and failure.await_count == 0, "no_commit_rules_failed")
            await session.rollback()
        async with factory() as session:
            await context(session, a)
            require(await session.scalar(text("SELECT count(*) FROM users WHERE personnel_number='CAP-DEV-3'"))
                    == 0, "no_commit_control_persisted")
        checks.append("no_commit_rules_control_rollback")

    async with factory() as session:
        await context(session, b)
        require(await session.scalar(text("SELECT count(*) FROM users WHERE tenant_id=:tid"), {"tid": a}) == 0,
                "foreign_read_leaked")
        changed = await session.execute(text("UPDATE positions SET name='Forbidden' WHERE tenant_id=:tid"), {"tid": a})
        deleted = await session.execute(text("DELETE FROM departments WHERE tenant_id=:tid"), {"tid": a})
        require(changed.rowcount == deleted.rowcount == 0, "foreign_write_leaked")
        await session.rollback()
        foreign_before = await foreign_fingerprint(session, b)
    checks.append("two_tenant_read_write_negatives")
    async with factory() as session:
        catalog = (await session.execute(text(
            "SELECT count(*) FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "JOIN pg_class r ON r.oid=k.confrelid JOIN pg_namespace rn ON rn.oid=r.relnamespace "
            "WHERE n.nspname=:schema AND rn.nspname=:schema AND k.contype='f' "
            "AND ((k.conname='owned_position_id_fk' AND k.confdeltype='a') OR "
            "(k.conname='owned_department_id_fk' AND k.confdeltype='n'))"
        ), {"schema": schema})).scalar_one()
        require(catalog == 2, "owned_fk_catalog_refused")
        checks.append("owned_fk_catalog")
        await context(session, a)
        # The application default list, not hard-coded copies of desired SQL.
        statements = await SuperadminService(session)._tenant_delete_statements()
        order = [statement.strip().split()[2] for statement in statements]
        require("positions" in order and order.index("users") < order.index("positions")
                < order.index("departments") < order.index("tenants"), "actual_purge_order_refused")
        checks.append("actual_delete_list_position_order")
        for statement in statements:
            await session.execute(text(statement), {"tenant_id": str(a)})
        await session.commit()
        require(not any((await counts(session, a)).values()), "owned_rows_remain")
        await session.rollback()
        require(await foreign_fingerprint(session, b) == foreign_before, "foreign_fixture_changed")
        require((await counts(session, b))["positions"] == 1, "foreign_position_missing")
        checks.append("owned_rows_zero_foreign_fixture_unchanged")
    return checks


async def run_gate(config, frozen):
    schema = "capacity_" + uuid4().hex[:12]
    qualified = safe_schema(schema)
    owner = create_async_engine(config["owner_url"], poolclass=NullPool, hide_parameters=True)
    runtime = create_async_engine(config["runtime_url"], poolclass=NullPool, hide_parameters=True)

    @event.listens_for(runtime.sync_engine, "begin")
    def owned_path(connection):
        # Schema resolution only; never restore caller tenant implicitly.
        connection.exec_driver_sql(f"SET LOCAL search_path TO {qualified}, pg_catalog")

    owned, cleanup_ok, neutral = False, False, False
    before, checks, failure = None, [], None
    try:
        async with runtime.connect() as connection:
            await verify_runtime_role(connection)
        async with owner.begin() as connection:
            before = await metadata(connection)
            await clone(connection, schema)
        owned = True
        await service_proof(runtime, schema, checks)
        require(set(checks) == REQUIRED, "required_service_proofs_incomplete")
    except Exception as exc:
        failure = str(exc) if isinstance(exc, GateBlocked) else type(exc).__name__
        cause = exc
        for _ in range(4):
            for field in ("sqlstate", "constraint_name", "table_name", "column_name"):
                value = getattr(cause, field, None)
                if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_]{1,100}", value):
                    failure += f"|{field}={value}"
            cause = getattr(cause, "__cause__", None)
            if cause is None:
                break
    finally:
        if owned:
            try:
                async with owner.begin() as connection:
                    await connection.execute(text(f"DROP SCHEMA {qualified} CASCADE"))
                async with owner.connect() as connection:
                    cleanup_ok = not await connection.scalar(text(
                        "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:schema)"
                    ), {"schema": schema})
                    neutral = before == await metadata(connection)
            except Exception as exc:
                failure = failure or type(exc).__name__
        elif before is not None:
            async with owner.connect() as connection:
                cleanup_ok = not await connection.scalar(text(
                    "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:schema)"
                ), {"schema": schema})
                neutral = before == await metadata(connection)
        await runtime.dispose()
        await owner.dispose()
    unchanged = frozen == source_hashes()
    return {"status": "PASS" if not failure and cleanup_ok and neutral and unchanged else "BLOCKED",
            "scope": "isolated_supabase_dev_import_and_ordinary_purge_statement_plan",
            "checks": checks, "failure": failure, "cleanup": cleanup_ok,
            "public_catalog_neutral": neutral, "source_unchanged": unchanged,
            "source_sha256": frozen, "full_privileged_delete": "NOT_EXECUTED",
            "redis_io": "STUBBED_PROGRESS_ONLY", "project_ref_sha256": PROJECT_HASH}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--evidence-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "BLOCKED", "failure": "execute_flag_required"}))
        return 2
    try:
        config, target, frozen = prepare(args.env_file, args.evidence_file)
        load_dotenv(args.env_file, override=True)
        logging.disable(logging.CRITICAL)  # Never expose SQL/settings/fixture exception bodies.
        result = asyncio.run(run_gate(config, frozen))
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
            handle.write("\n")
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "failure": str(exc) if isinstance(exc, GateBlocked) else type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
