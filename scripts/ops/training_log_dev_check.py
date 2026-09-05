"""Canonical DEV read-only preflight; optional rollback-isolated reporting tests."""

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from kb_rag_isolated_dev_gate import normalize_database_url, same_supabase_project

TEST_TENANT_SLUGS = [
    "acme",
    "admin-report",
    "acmea",
    "acmeb",
    "acme-c",
    "acme-s",
    "acme-x",
    "acme-search",
    "acme-summary",
    "acme-p",
    "acme-assigned",
    "acme-inprog",
    "acme-aonly",
    "acme-sip",
    "acme-od",
    "acme-nol",
    "deadline-eligibility",
    "completed-state",
    "stable-deadline-page",
    "training-log-rls-a",
    "training-log-rls-b",
]


async def fixture_count(engine) -> int:
    async with engine.connect() as connection:
        async with connection.begin():
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            return int(
                await connection.scalar(
                    text("SELECT count(*) FROM tenants WHERE slug = ANY(:slugs)"),
                    {"slugs": TEST_TENANT_SLUGS},
                )
                or 0
            )


async def main() -> int:
    values = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
    runtime_rls = "--runtime-rls" in sys.argv
    database_url = normalize_database_url(values.get("MIGRATION_DATABASE_URL") or "")
    runtime_url = normalize_database_url(values.get("DATABASE_URL") or "")
    if not same_supabase_project(database_url, values.get("SUPABASE_URL") or ""):
        print(json.dumps({"status": "BLOCKED", "reason": "canonical_dev_identity_mismatch"}))
        return 2
    url = make_url(database_url)
    if url.database != "postgres" or not url.host or "supabase" not in url.host:
        print(json.dumps({"status": "BLOCKED", "reason": "unexpected_dev_target"}))
        return 2
    engine = create_async_engine(
        database_url, connect_args={"timeout": 12, "command_timeout": 15}, echo=False, hide_parameters=True
    )
    tests_started = False
    try:
        async with engine.connect() as connection:
            async with connection.begin():
                await connection.execute(text("SET TRANSACTION READ ONLY"))
                revision = (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
                roles = (
                    (
                        await connection.execute(
                            text(
                                "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname IN (current_user, 'lms_app')"
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                columns = (
                    await connection.execute(
                        text(
                            "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='public' AND ((table_name='learning_path_assignments' AND column_name='recurrence_instance_id') OR (table_name='enrollments' AND column_name='learning_path_assignment_id'))"
                        )
                    )
                ).all()
                runtime = next((row for row in roles if row["rolname"] == "lms_app"), None)
                if len(columns) != 2 or runtime is None or runtime["rolsuper"] or runtime["rolbypassrls"]:
                    print(json.dumps({"status": "BLOCKED", "reason": "schema_or_runtime_role_preflight", "writes": 0}))
                    return 2
                print(
                    json.dumps(
                        {
                            "status": "PASS",
                            "target": "canonical_supabase_dev",
                            "revision": revision,
                            "roles": [dict(row) for row in roles],
                            "required_columns": len(columns),
                            "writes": 0,
                        }
                    )
                )
        if "--execute-tests" in sys.argv or runtime_rls:
            if (
                not same_supabase_project(runtime_url, values.get("SUPABASE_URL") or "")
                or (make_url(runtime_url).username or "").split(".")[0] != "lms_app"
            ):
                print(json.dumps({"status": "BLOCKED", "reason": "canonical_runtime_role_not_configured"}))
                return 2
            if await fixture_count(engine):
                print(json.dumps({"status": "BLOCKED", "reason": "test_fixture_name_collision", "writes": 0}))
                return 2
            # Existing tests/conftest.py owns isolation via an outer transaction
            # and savepoints; only this fixed synthetic reporting suite runs.
            test_env = dict(os.environ)
            test_env["DATABASE_URL"] = runtime_url
            test_env["APP_ENV"] = "test"
            test_env["RESEND_API_KEY"] = ""
            test_env["REDIS_URL"] = "redis://localhost:6379/15"
            tests_started = True
            target = "tests/integration/test_training_log.py"
            if runtime_rls:
                target += "::test_training_log_repository_lms_app_rls_hides_other_tenant_rows_and_counts"
            result = subprocess.run(
                [sys.executable, "-m", "pytest", target, "-q", "--tb=line", "-ra"],
                cwd=Path(__file__).resolve().parents[2] / "apps" / "api",
                env=test_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=360,
            )
            output = result.stdout + result.stderr
            output = re.sub(r"(?:postgres(?:ql)?(?:\+asyncpg)?|redis)://[^\s'\"]+", "[redacted-connection]", output)
            print(output[-10000:])
            residue = await fixture_count(engine)
            print(json.dumps({"cleanup": "PASS" if residue == 0 else "BLOCKED", "remaining_test_tenants": residue}))
            if residue:
                return 4
            if result.returncode == 0 and re.search(r"\b[1-9]\d* skipped\b", output):
                print(json.dumps({"status": "PARTIAL", "reason": "required_integration_gate_skipped"}))
                return 3
            return result.returncode
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "reason": type(exc).__name__,
                    "tests_started": tests_started,
                    "cleanup": "NOT_VERIFIED" if tests_started else "no_writes",
                }
            )
        )
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
