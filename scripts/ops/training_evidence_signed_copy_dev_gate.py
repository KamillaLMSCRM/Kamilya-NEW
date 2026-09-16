"""Exercise migration 0160 and signed-copy RLS in one disposable Supabase DEV schema."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from kb_rag_isolated_dev_gate import normalize_database_url, same_supabase_project

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "apps" / "api"
SCHEMA_PATTERN = re.compile(r"^tesc_dev_[0-9a-f]{12}$")


def _validated_schema(schema: str) -> str:
    if not SCHEMA_PATTERN.fullmatch(schema):
        raise ValueError("unsafe_schema")
    return schema


def _load_migration():
    path = API / "alembic" / "versions" / "0160_training_evidence_signed_scan_reviews.py"
    spec = importlib.util.spec_from_file_location("training_evidence_signed_copy_0160", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("migration_loader_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migrate(sync_connection, schema: str) -> None:
    context = MigrationContext.configure(sync_connection, opts={"version_table_schema": schema})
    migration = _load_migration()
    with Operations.context(context):
        migration.upgrade()


async def _create_baseline(owner, schema: str):
    tenant_a, tenant_b = uuid4(), uuid4()
    learner_a, learner_b, reviewer_a = uuid4(), uuid4(), uuid4()
    enrollment_a, enrollment_b = uuid4(), uuid4()
    event_a, event_b = uuid4(), uuid4()
    scan_a, scan_b = uuid4(), uuid4()
    qschema = f'"{schema}"'
    async with owner.begin() as connection:
        await connection.execute(text(f"CREATE SCHEMA {qschema}"))
        await connection.execute(text(f"REVOKE ALL ON SCHEMA {qschema} FROM PUBLIC"))
        await connection.execute(text(f"GRANT USAGE ON SCHEMA {qschema} TO lms_app"))
        await connection.execute(text(f"CREATE TABLE {qschema}.tenants (id uuid PRIMARY KEY, name text NOT NULL)"))
        await connection.execute(
            text(
                f"CREATE TABLE {qschema}.users ("
                "id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES "
                f"{qschema}.tenants(id), first_name text NOT NULL, last_name text NOT NULL)"
            )
        )
        await connection.execute(
            text(
                f"CREATE TABLE {qschema}.enrollments ("
                "id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES "
                f"{qschema}.tenants(id), user_id uuid NOT NULL REFERENCES {qschema}.users(id))"
            )
        )
        await connection.execute(
            text(
                f"CREATE TABLE {qschema}.training_evidence_events ("
                "id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES "
                f"{qschema}.tenants(id), user_id uuid NOT NULL REFERENCES {qschema}.users(id), "
                f"enrollment_id uuid NOT NULL REFERENCES {qschema}.enrollments(id))"
            )
        )
        await connection.execute(
            text(
                f"CREATE TABLE {qschema}.training_evidence_signed_scans ("
                "id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES "
                f"{qschema}.tenants(id), event_id uuid NOT NULL REFERENCES {qschema}.training_evidence_events(id) ON DELETE CASCADE, "
                f"enrollment_id uuid NOT NULL REFERENCES {qschema}.enrollments(id), "
                f"user_id uuid NOT NULL REFERENCES {qschema}.users(id), status text NOT NULL DEFAULT 'received', "
                "original_filename text NOT NULL, content_type text NOT NULL, size_bytes integer NOT NULL, "
                "sha256 text NOT NULL, storage_key text NOT NULL UNIQUE, uploaded_by_user_id uuid NOT NULL REFERENCES "
                f"{qschema}.users(id), uploaded_at timestamptz NOT NULL DEFAULT now(), created_at timestamptz NOT NULL DEFAULT now(), "
                "CONSTRAINT ck_training_evidence_signed_scans_received CHECK (status = 'received'))"
            )
        )
        await connection.execute(
            text(
                f"CREATE FUNCTION {qschema}.training_evidence_retention_purge_authorized() RETURNS boolean "
                "LANGUAGE sql STABLE AS $$ SELECT current_setting('app.retention_purge', true) = 'on' $$"
            )
        )
        await connection.execute(
            text(
                f"CREATE FUNCTION {qschema}.prevent_training_evidence_signed_scan_mutation() RETURNS trigger "
                f"LANGUAGE plpgsql SET search_path={qschema},pg_temp AS $$ BEGIN "
                "IF TG_OP='DELETE' AND training_evidence_retention_purge_authorized() THEN RETURN OLD; END IF; "
                "RAISE EXCEPTION 'append only' USING ERRCODE='check_violation'; END $$"
            )
        )
        await connection.execute(
            text(
                "CREATE TRIGGER trg_prevent_training_evidence_signed_scan_mutation BEFORE UPDATE OR DELETE ON "
                f"{qschema}.training_evidence_signed_scans FOR EACH ROW EXECUTE FUNCTION "
                f"{qschema}.prevent_training_evidence_signed_scan_mutation()"
            )
        )
        await connection.execute(
            text(f"INSERT INTO {qschema}.tenants (id,name) VALUES (:a,'A'),(:b,'B')"),
            {"a": tenant_a, "b": tenant_b},
        )
        await connection.execute(
            text(
                f"INSERT INTO {qschema}.users (id,tenant_id,first_name,last_name) VALUES "
                "(:la,:ta,'Learner','A'),(:ra,:ta,'Reviewer','A'),(:lb,:tb,'Learner','B')"
            ),
            {"la": learner_a, "ra": reviewer_a, "lb": learner_b, "ta": tenant_a, "tb": tenant_b},
        )
        await connection.execute(
            text(
                f"INSERT INTO {qschema}.enrollments (id,tenant_id,user_id) VALUES "
                "(:ea,:ta,:la),(:eb,:tb,:lb)"
            ),
            {"ea": enrollment_a, "eb": enrollment_b, "ta": tenant_a, "tb": tenant_b, "la": learner_a, "lb": learner_b},
        )
        await connection.execute(
            text(
                f"INSERT INTO {qschema}.training_evidence_events (id,tenant_id,user_id,enrollment_id) VALUES "
                "(:va,:ta,:la,:ea),(:vb,:tb,:lb,:eb)"
            ),
            {"va": event_a, "vb": event_b, "ta": tenant_a, "tb": tenant_b, "la": learner_a, "lb": learner_b, "ea": enrollment_a, "eb": enrollment_b},
        )
        await connection.execute(
            text(
                f"INSERT INTO {qschema}.training_evidence_signed_scans "
                "(id,tenant_id,event_id,enrollment_id,user_id,original_filename,content_type,size_bytes,sha256,storage_key,uploaded_by_user_id) VALUES "
                "(:sa,:ta,:va,:ea,:la,'a.pdf','application/pdf',8,:hash,'a.pdf',:la),"
                "(:sb,:tb,:vb,:eb,:lb,'b.pdf','application/pdf',8,:hash,'b.pdf',:lb)"
            ),
            {"sa": scan_a, "sb": scan_b, "ta": tenant_a, "tb": tenant_b, "va": event_a, "vb": event_b, "ea": enrollment_a, "eb": enrollment_b, "la": learner_a, "lb": learner_b, "hash": "a" * 64},
        )
        await connection.run_sync(_migrate, schema)
        for table in (
            "tenants",
            "users",
            "enrollments",
            "training_evidence_events",
            "training_evidence_signed_scans",
        ):
            await connection.execute(text(f"ALTER TABLE {qschema}.{table} ENABLE ROW LEVEL SECURITY"))
            await connection.execute(text(f"ALTER TABLE {qschema}.{table} FORCE ROW LEVEL SECURITY"))
            tenant_column = "id" if table == "tenants" else "tenant_id"
            await connection.execute(
                text(
                    f"CREATE POLICY fixture_{table}_tenant ON {qschema}.{table} FOR ALL TO lms_app "
                    f"USING ({tenant_column}=nullif(current_setting('app.tenant_id',true),'')::uuid) "
                    f"WITH CHECK ({tenant_column}=nullif(current_setting('app.tenant_id',true),'')::uuid)"
                )
            )
            await connection.execute(text(f"GRANT SELECT, INSERT ON {qschema}.{table} TO lms_app"))
    return (
        tenant_a,
        tenant_b,
        learner_a,
        reviewer_a,
        enrollment_a,
        event_a,
        event_b,
        scan_a,
        scan_b,
    )


async def _exercise_runtime(runtime, schema: str, fixture) -> list[str]:
    (
        tenant_a,
        _tenant_b,
        learner_a,
        reviewer_a,
        enrollment_a,
        event_a,
        event_b,
        scan_a,
        scan_b,
    ) = fixture
    checks: list[str] = []
    qschema = f'"{schema}"'
    async with runtime.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(text(f"SET LOCAL search_path TO {qschema}, public"))
            await connection.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_a)})
            own_scan_count = await connection.scalar(text("SELECT count(*) FROM training_evidence_signed_scans"))
            assert own_scan_count == 1, "scan_rls_isolation_failed"
            checks.append("scan_rls_isolation")

            legacy_status = await connection.scalar(
                text("SELECT status FROM training_evidence_signed_scans WHERE id=:scan"),
                {"scan": scan_a},
            )
            assert legacy_status == "received", "legacy_status_not_preserved"
            checks.append("legacy_status_preserved")

            for status in ("received", "uploaded_pending_review"):
                await connection.execute(
                    text(
                        "INSERT INTO training_evidence_signed_scans "
                        "(id,tenant_id,event_id,enrollment_id,user_id,status,original_filename,content_type,"
                        "size_bytes,sha256,storage_key,uploaded_by_user_id) VALUES "
                        "(:id,:tenant,:event,:enrollment,:user,:status,:filename,'application/pdf',8,:hash,:key,:user)"
                    ),
                    {
                        "id": uuid4(),
                        "tenant": tenant_a,
                        "event": event_a,
                        "enrollment": enrollment_a,
                        "user": learner_a,
                        "status": status,
                        "filename": f"{status}.pdf",
                        "hash": "b" * 64,
                        "key": f"{status}-{uuid4()}.pdf",
                    },
                )
                checks.append(f"scan_status_{status}_accepted")

            await connection.execute(
                text(
                    "INSERT INTO training_evidence_signed_scan_reviews "
                    "(id,tenant_id,event_id,signed_scan_id,action,reviewed_by_user_id) "
                    "VALUES (:id,:tenant,:event,:scan,'accept',:reviewer)"
                ),
                {"id": uuid4(), "tenant": tenant_a, "event": event_a, "scan": scan_a, "reviewer": reviewer_a},
            )
            checks.append("accepted_review_insert")

            try:
                await connection.execute(
                    text(
                        "INSERT INTO training_evidence_signed_scan_reviews "
                        "(id,tenant_id,event_id,signed_scan_id,action,reviewed_by_user_id) "
                        "VALUES (:id,:tenant,:event,:scan,'accept',:reviewer)"
                    ),
                    {"id": uuid4(), "tenant": tenant_a, "event": event_b, "scan": scan_b, "reviewer": reviewer_a},
                )
            except Exception:
                await transaction.rollback()
                transaction = await connection.begin()
                await connection.execute(text(f"SET LOCAL search_path TO {qschema}, public"))
                await connection.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_a)})
                checks.append("cross_tenant_review_rejected")
            else:
                raise AssertionError("cross_tenant_review_was_accepted")

            accepted = await connection.scalar(
                text("SELECT count(*) FROM training_evidence_signed_scan_reviews WHERE action='accept'")
            )
            assert accepted == 0, "rolled_back_review_visibility_unexpected"
        finally:
            if transaction.is_active:
                await transaction.rollback()
    return checks


async def main() -> int:
    env_path = Path(os.environ.get("KAMILYA_DEV_ENV_FILE", ROOT / ".env"))
    values = dotenv_values(env_path)
    owner_url = normalize_database_url(values.get("MIGRATION_DATABASE_URL") or "")
    runtime_url = normalize_database_url(values.get("DATABASE_URL") or "")
    if not same_supabase_project(owner_url, values.get("SUPABASE_URL") or ""):
        print(json.dumps({"status": "BLOCKED", "reason": "canonical_dev_identity_mismatch"}))
        return 2
    if not same_supabase_project(runtime_url, values.get("SUPABASE_URL") or ""):
        print(json.dumps({"status": "BLOCKED", "reason": "runtime_dev_identity_mismatch"}))
        return 2
    if (make_url(runtime_url).username or "").split(".")[0] != "lms_app":
        print(json.dumps({"status": "BLOCKED", "reason": "runtime_role_not_lms_app"}))
        return 2

    schema = _validated_schema(f"tesc_dev_{uuid4().hex[:12]}")
    owner = create_async_engine(owner_url, poolclass=NullPool, hide_parameters=True)
    runtime = create_async_engine(runtime_url, poolclass=NullPool, hide_parameters=True)
    cleanup = "NOT_VERIFIED"
    try:
        fixture = await _create_baseline(owner, schema)
        checks = await _exercise_runtime(runtime, schema, fixture)
        print(json.dumps({"status": "PASS", "target": "isolated_supabase_dev_schema", "checks": checks}))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": type(exc).__name__}))
        return 1
    finally:
        try:
            async with owner.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            cleanup = "PASS"
        except Exception:
            cleanup = "BLOCKED"
        print(json.dumps({"cleanup": cleanup, "schema": "disposable"}))
        await runtime.dispose()
        await owner.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
