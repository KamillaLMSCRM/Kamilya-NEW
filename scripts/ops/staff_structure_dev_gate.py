"""Real migration/transaction/RLS proof in one disposable Supabase DEV schema.

No public writes, no customer fixtures, no local database, no provider changes.
Clones table definitions only through the existing isolated DEV procedure.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import re
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from dotenv import load_dotenv
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from kb_rag_isolated_dev_gate import GateBlocked  # noqa: E402
from source_actuality_dev_gate import public_snapshot, verify_runtime_role  # noqa: E402
from workbench_document_dev_gate import canonical_config  # noqa: E402

TABLES = ("tenants", "users", "user_roles", "departments", "positions", "courses", "enrollments", "content_releases",
          "department_courses", "position_courses", "organization_course_rules", "cohorts", "cohort_members", "staff_sync_identities")


def candidate_hashes():
    paths = [ROOT / "scripts/ops/staff_structure_dev_gate.py", ROOT / "scripts/ops/staff_structure_dev_checks.py",
             ROOT / "apps/api/alembic/versions/0183_staff_structure_changes.py",
             ROOT / "apps/api/app/modules/positions/assignment_service.py"]
    paths.extend((ROOT / "apps/api/app/modules/organization_units").glob("*.py"))
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def quoted_schema(value):
    if not re.fullmatch(r"staff_change_[0-9a-f]{12}", value):
        raise GateBlocked("unsafe_schema")
    return f'"{value}"'


async def migrate(connection, schema, action):
    spec = importlib.util.spec_from_file_location("staff_changes_0183", ROOT / "apps/api/alembic/versions/0183_staff_structure_changes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def apply(sync):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        with Operations.context(MigrationContext.configure(sync, opts={"version_table_schema": schema})):
            getattr(module, action)()
    await connection.run_sync(apply)


async def context(db, schema, tenant=None, actor=None):
    await db.execute(text(f"SET LOCAL search_path TO {quoted_schema(schema)},pg_catalog"))
    await db.execute(text("SELECT set_config('app.tenant_id',:t,true),set_config('app.user_id',:a,true),set_config('app.is_superadmin','false',true)"),
                     {"t": str(tenant) if tenant else "", "a": str(actor) if actor else ""})


async def run(config):
    hashes = candidate_hashes()
    schema = "staff_change_" + uuid4().hex[:12]
    qs = quoted_schema(schema)
    owner = create_async_engine(config["owner_url"], poolclass=NullPool, hide_parameters=True)
    runtime = create_async_engine(config["runtime_url"], poolclass=NullPool, hide_parameters=True, isolation_level="SERIALIZABLE")
    @event.listens_for(runtime.sync_engine, "begin")
    def isolate(connection):
        connection.exec_driver_sql(f"SET LOCAL search_path TO {qs},pg_catalog")
    created = cleaned = neutral = False
    checks, stage, failure = [], "identity", None
    ids = {key: uuid4() for key in ("ta", "tb", "ma", "mb", "sa", "sb", "ua", "ub", "pa", "pb", "c1", "c2", "r1", "r2", "e1", "e2")}
    try:
        async with runtime.connect() as db:
            await verify_runtime_role(db)
        async with owner.begin() as db:
            before = await public_snapshot(db)
            if await db.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:s)"), {"s": schema}):
                raise GateBlocked("schema_collision")
            stage = "clone_metadata"
            await db.execute(text(f"CREATE SCHEMA {qs}"))
            created = True
            await db.execute(text(f"REVOKE ALL ON SCHEMA {qs} FROM PUBLIC"))
            await db.execute(text(f"GRANT USAGE ON SCHEMA {qs} TO lms_app"))
            for table in TABLES:
                await db.execute(text(f"CREATE TABLE {qs}.{table} (LIKE public.{table} INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES)"))
                await db.execute(text(f"REVOKE ALL ON {qs}.{table} FROM PUBLIC,lms_app"))
                await db.execute(text(f"GRANT SELECT,INSERT,UPDATE,DELETE ON {qs}.{table} TO lms_app"))
                await db.execute(text(f"ALTER TABLE {qs}.{table} ENABLE ROW LEVEL SECURITY"))
                await db.execute(text(f"ALTER TABLE {qs}.{table} FORCE ROW LEVEL SECURITY"))
                tenant = "id" if table == "tenants" else "tenant_id"
                predicate = f"{tenant}=nullif(current_setting('app.tenant_id',true),'')::uuid"
                await db.execute(text(f"CREATE POLICY gate_tenant ON {qs}.{table} FOR ALL TO lms_app USING({predicate}) WITH CHECK({predicate})"))
            # LIKE INCLUDING INDEXES assigns generated names. Preserve the exact
            # known conflict index identity so transport tests exercise production
            # error mapping, not an invented clone-only constraint name.
            conflict_indexes = (await db.execute(text("""SELECT c.relname FROM pg_index i
                JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace
                JOIN pg_index original ON original.indexrelid=to_regclass('public.uq_enrollments_current_occurrence')
                WHERE n.nspname=:schema AND i.indrelid=to_regclass(:table)
                AND i.indisunique=original.indisunique AND i.indkey=original.indkey
                AND pg_get_expr(i.indexprs,i.indrelid) IS NOT DISTINCT FROM pg_get_expr(original.indexprs,original.indrelid)
                AND pg_get_expr(i.indpred,i.indrelid) IS NOT DISTINCT FROM pg_get_expr(original.indpred,original.indrelid)"""),
                {"schema": schema, "table": f"{schema}.enrollments"})).scalars().all()
            if len(conflict_indexes) != 1 or not re.fullmatch(r"[a-z_0-9]+", conflict_indexes[0]):
                raise GateBlocked("canonical_occurrence_index_clone_mismatch")
            if conflict_indexes[0] != "uq_enrollments_current_occurrence":
                await db.execute(text(f'ALTER INDEX {qs}."{conflict_indexes[0]}" RENAME TO uq_enrollments_current_occurrence'))
            stage = "migration"
            await migrate(db, schema, "upgrade")
            await migrate(db, schema, "downgrade")
            await migrate(db, schema, "upgrade")
            checks.append("0183_empty_upgrade_downgrade_reupgrade")
        stage = "synthetic_seed"
        async with owner.begin() as db:
            await context(db, schema)
            await db.execute(text("INSERT INTO tenants(id,name,slug,status,plan) VALUES (:ta,'Synthetic A',:tsa,'active','free'),(:tb,'Synthetic B',:tsb,'active','free')"), ids | {"tsa": "a-"+schema, "tsb": "b-"+schema})
            await db.execute(text("INSERT INTO users(id,tenant_id,first_name,last_name,role,is_active,status) VALUES (:ma,:ta,'Method','A','methodologist',true,'active'),(:mb,:tb,'Method','B','methodologist',true,'active')"), ids)
            await db.execute(text("INSERT INTO departments(id,tenant_id,name,slug,unit_type,normalized_name,legacy_root,head_user_id) VALUES (:ua,:ta,'Unit A','unit-a','branch','unit a',false,:ma),(:ub,:ta,'Unit B','unit-b','branch','unit b',false,NULL)"), ids)
            await db.execute(text("INSERT INTO positions(id,tenant_id,name,normalized_name,department,department_id,is_active) VALUES (:pa,:ta,'Shared','shared','Unit A',:ua,true),(:pb,:tb,'Foreign','foreign','',NULL,true)"), ids)
            await db.execute(text("INSERT INTO users(id,tenant_id,first_name,last_name,personnel_number,role,is_active,status,position_id) VALUES (:sa,:ta,'Student','A','QA-A','student',true,'active',:pa),(:sb,:tb,'Student','B','QA-B','student',true,'active',:pb)"), ids)
            await db.execute(text("INSERT INTO courses(id,tenant_id,title,description,status,review_status,delivery_type,current_release_id) VALUES (:c1,:ta,'Old synthetic','','published','approved','native',:r1),(:c2,:ta,'New synthetic','','published','approved','native',:r2)"), ids)
            await db.execute(text("INSERT INTO content_releases(id,tenant_id,course_id,version,snapshot,snapshot_sha256) VALUES (:r1,:ta,:c1,1,'{}',:hash),(:r2,:ta,:c2,1,'{}',:hash)"), ids | {"hash": "a"*64})
            await db.execute(text("INSERT INTO department_courses(id,tenant_id,department_id,course_id) VALUES (:dc1,:ta,:ua,:c1),(:dc2,:ta,:ub,:c2)"), ids | {"dc1": uuid4(), "dc2": uuid4()})
            await db.execute(text("INSERT INTO enrollments(id,tenant_id,user_id,course_id,status,source,content_release_id) VALUES (:e1,:ta,:sa,:c1,'enrolled','department',:r1)"), ids)
        from app.modules.organization_units.change_service import confirm_change, preview_change
        from app.models.tenants import Tenant  # noqa: F401 - register FK targets for direct service execution
        from app.modules.courses.release_models import ContentRelease  # noqa: F401
        from app.modules.learning_cycles.models import RecurringLearningAssignment  # noqa: F401
        from app.modules.learning_paths.models import LearningPathAssignment  # noqa: F401
        from app.modules.organization_units.change_models import OrganizationChangePlan
        from app.modules.organization_units.workspace_read import employee_roster, workspace_overview
        from app.modules.positions.assignment_service import recompute_enrollments
        command = {"kind": "employee", "target_id": str(ids["sa"]), "organization_unit_id": str(ids["ub"]), "position_id": str(ids["pa"]), "reason": "Synthetic transfer"}
        async def make_preview():
            async with AsyncSession(runtime, expire_on_commit=False) as db:
                await context(db, schema, ids["ta"], ids["ma"])
                preview = await preview_change(db, tenant_id=ids["ta"], actor_id=ids["ma"], command=command)
                await db.commit()
                return preview
        stage = "read_model"
        async with AsyncSession(runtime) as db:
            await context(db, schema, ids["ta"], ids["ma"])
            overview = await workspace_overview(db, ids["ta"], "all")
            assert overview["total"] == 1
            assert next(u for u in overview["units"] if u["id"] == str(ids["ua"]))["direct_count"] == 1
            roster = await employee_roster(db, ids["ta"], unit_id=ids["ua"], unplaced=False, scope="subtree", access="all", q="", position_id=None, missing_position=False, page=1, page_size=20)
            assert roster["items"][0]["placement_source"] == "position_fallback"
            checks.append("server_roster_fallback_and_tenant_counts")
        stage = "preview_confirm"
        preview = await make_preview()
        assert preview["training"]["added"] == 1 and preview["reporting"][0]["lost"] == 1
        async with AsyncSession(runtime) as db:
            await context(db, schema, ids["tb"], ids["mb"])
            assert await db.scalar(select(OrganizationChangePlan).where(OrganizationChangePlan.id == UUID(preview["id"]))) is None
            try:
                await confirm_change(db, tenant_id=ids["tb"], actor_id=ids["mb"], plan_id=UUID(preview["id"]))
            except LookupError:
                checks.append("foreign_tenant_plan_hidden")
            else:
                raise GateBlocked("foreign_plan_visible")
        async with AsyncSession(runtime) as db:
            await context(db, schema, ids["ta"], ids["sa"])
            assert await db.scalar(select(OrganizationChangePlan).where(OrganizationChangePlan.id == UUID(preview["id"]))) is None
            checks.append("student_plan_hidden")
        async with AsyncSession(runtime) as db:
            await context(db, schema, ids["ta"], ids["ma"])
            receipt = await confirm_change(db, tenant_id=ids["ta"], actor_id=ids["ma"], plan_id=UUID(preview["id"]))
            await db.commit()
            assert receipt["added"] == 1
        async with AsyncSession(runtime) as db:
            await context(db, schema, ids["ta"], ids["ma"])
            assert await confirm_change(db, tenant_id=ids["ta"], actor_id=ids["ma"], plan_id=UUID(preview["id"])) == receipt
            assert await db.scalar(text("SELECT count(*) FROM enrollments WHERE user_id=:u"), {"u": ids["sa"]}) == 2
            outcome = await recompute_enrollments(db, ids["sa"])
            assert outcome.removed == 0 and outcome.skipped_protected == 1
            assert await db.scalar(text("SELECT source FROM enrollments WHERE id=:e"), {"e": ids["e1"]}) == "department"
            await db.commit()
            checks.extend(["atomic_employee_transfer_and_training_addition", "same_receipt_replay_no_duplicate", "retained_enrollment_survives_generic_recompute_without_source_rewrite"])
        stage = "stale"
        stale = await make_preview()
        async with owner.begin() as db:
            await context(db, schema)
            await db.execute(text("UPDATE departments SET name='Unit B changed' WHERE id=:u"), {"u": ids["ub"]})
        async with AsyncSession(runtime) as db:
            await context(db, schema, ids["ta"], ids["ma"])
            try:
                await confirm_change(db, tenant_id=ids["ta"], actor_id=ids["ma"], plan_id=UUID(stale["id"]))
            except ValueError as exc:
                assert str(exc) == "preview_stale"
                await db.rollback()
                checks.append("stale_preview_rejected_before_writes")
            else:
                raise GateBlocked("stale_preview_accepted")
        stage = "cross_tenant_position_trigger"
        async with AsyncSession(runtime) as db:
            await context(db, schema, ids["ta"], ids["ma"])
            try:
                await db.execute(text("UPDATE users SET position_id=:p WHERE id=:u"), {"p": ids["pb"], "u": ids["sa"]})
            except Exception as exc:
                assert getattr(exc.orig, "sqlstate", None) == "23514"
                await db.rollback()
                checks.append("database_cross_tenant_position_rejected")
            else:
                raise GateBlocked("foreign_position_accepted")
        stage = "extended_transactions_retention"
        from staff_structure_dev_checks import verify_changes
        await verify_changes(owner, runtime, schema, ids, context, checks)
        stage = "new_table_rls"
        async with owner.connect() as db:
            rows = (await db.execute(text("SELECT relrowsecurity,relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:s AND c.relname IN ('organization_change_plans','organization_transfer_retained_enrollments')"), {"s": schema})).all()
            assert len(rows) == 2 and all(a and b for a, b in rows)
            checks.append("both_new_tables_rls_force_rls")
            neutral = await public_snapshot(db) == before
            if not neutral:
                raise GateBlocked("public_catalog_changed")
        if candidate_hashes() != hashes:
            raise GateBlocked("candidate_changed_during_gate")
    except Exception as exc:
        failure = {"stage": stage, "class": type(exc).__name__, "reason": str(exc) if isinstance(exc, GateBlocked) else "sanitized"}
        frames = [f for f in traceback.extract_tb(exc.__traceback__) if Path(f.filename).name == Path(__file__).name]
        failure["gate_line"] = frames[-1].lineno if frames else None
        owned_frames = [f for f in traceback.extract_tb(exc.__traceback__) if Path(f.filename).name == "staff_structure_dev_checks.py"]
        if owned_frames:
            failure["check_line"] = owned_frames[-1].lineno
        original = getattr(exc, "orig", None)
        cause = getattr(original, "__cause__", None)
        failure["sqlstate"] = getattr(original, "sqlstate", None)
        missing_column = re.search(r'column "([a-zA-Z_][a-zA-Z0-9_]{0,119})"', str(cause)) if cause else None
        if missing_column:
            failure["column_name"] = missing_column.group(1)
        for attr in ("column_name", "constraint_name"):
            value = getattr(cause, attr, None)
            if value and re.fullmatch(r"[a-zA-Z0-9_]{1,120}", value):
                failure[attr] = value
    finally:
        if created:
            async with owner.begin() as db:
                await db.execute(text(f"DROP SCHEMA IF EXISTS {qs} CASCADE"))
            async with owner.connect() as db:
                cleaned = not await db.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:s)"), {"s": schema})
                neutral = await public_snapshot(db) == before
        await runtime.dispose()
        await owner.dispose()
    return {"at": datetime.now(UTC).isoformat(), "result": "PASS" if not failure and cleaned and neutral else "NOT_READY",
            "checks": checks, "failure": failure, "cleanup": cleaned, "public_catalog_neutral": neutral,
            "source_sha256": hashes,
            "scope": "Owned synthetic Supabase DEV schema; real0183 and service; neighbor RLS policies are synthetic, not copied production policies"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("execute_flag_required")
    config = canonical_config(args.env_file)
    load_dotenv(args.env_file, override=True)
    os.environ["APP_ENV"] = "test"
    os.environ["STAFF_STRUCTURE_V3_ENABLED"] = "true"
    result = asyncio.run(run(config))
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
