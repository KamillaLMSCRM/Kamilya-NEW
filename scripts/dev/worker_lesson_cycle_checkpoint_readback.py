"""Read-only DEV QA checkpoint evidence for one exact ordinary generation job."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "apps/api"), str(ROOT / "scripts/ops")]
from kb_rag_isolated_dev_gate import normalize_database_url, same_supabase_project  # noqa: E402

TENANT = "a7a2c055-fb0b-4f38-b17c-3ee47dd6cfb0"


async def run(args):
    env = dotenv_values("C:/Kamilya New/Kamilya-NEW/.env")
    assert same_supabase_project(env["DATABASE_URL"], env["SUPABASE_URL"])
    assert not args.output.exists()
    engine = create_async_engine(normalize_database_url(env["DATABASE_URL"]), poolclass=NullPool,
                                 connect_args={"statement_cache_size": 0})
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            role = (await conn.execute(text("SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"))).one()
            assert role == ("lms_app", False, False)
            await conn.execute(text("SELECT set_current_tenant(:tenant)"), {"tenant": TENANT})
            job = (await conn.execute(text("SELECT id,status,stage,course_id FROM ai_jobs WHERE tenant_id=CAST(:tenant AS uuid) AND id=:job"),
                                      {"tenant": TENANT, "job": str(UUID(args.job))})).mappings().one()
            rows = (await conn.execute(text("""
                SELECT run.generation_key, run.plan_revision, run.plan_payload,
                       checkpoint.content_status, checkpoint.review_status,
                       checkpoint.assessment_status, checkpoint.assessment_payload
                FROM ai_generation_runs AS run
                JOIN ai_generation_lesson_checkpoints AS checkpoint
                  ON checkpoint.generation_run_id=run.id AND checkpoint.tenant_id=run.tenant_id
                WHERE run.tenant_id=CAST(:tenant AS uuid) AND run.source_job_id=:job
                ORDER BY run.created_at,run.generation_key
            """), {"tenant": TENANT, "job": str(UUID(args.job))})).mappings().all()
            result = {"scope": "DEV QA READ ONLY", "tenant_id": TENANT, "job": dict(job),
                      "at": datetime.now(UTC).isoformat(), "checkpoints": [dict(row) for row in rows]}
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print(json.dumps({"job_id": args.job, "status": job["status"], "checkpoints": len(rows),
                              "completed": sum(row["assessment_status"] == "completed" for row in rows),
                              "rejected_plans": sum(bool((row["assessment_payload"] or {}).get("rejected")) for row in rows)}))
    finally:
        await engine.dispose()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--job", required=True)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
