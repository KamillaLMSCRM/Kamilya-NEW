"""Explicit owner-only, bounded DEV maintenance. Default dry-run; no production."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from uuid import UUID

from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/api"))
from kb_rag_isolated_dev_gate import supabase_project_ref  # noqa: E402
from workbench_document_dev_gate import canonical_config  # noqa: E402

DEV_PROJECT_REF_SHA256 = "5b535773cb7222384bbb54ad3f8c2e741fa6176bec4ce586abcd82d17ee0062e"


def dev_config(env_file):
    values = dotenv_values(env_file)
    if str(values.get("APP_ENV", "")).strip().lower() not in {"development", "dev", "test"}:
        raise ValueError("dev_environment_required")
    config = canonical_config(env_file)
    identity = hashlib.sha256(supabase_project_ref(config["supabase_url"]).encode("ascii")).hexdigest()
    if identity != DEV_PROJECT_REF_SHA256:
        raise ValueError("canonical_dev_project_required")
    return config


async def run(config, tenant_id, batch_size, execute):
    from app.modules.organization_units.change_service import purge_change_plans

    owner = create_async_engine(config["owner_url"], poolclass=NullPool, hide_parameters=True)
    try:
        async with AsyncSession(owner) as db:
            await db.execute(text("SET LOCAL search_path TO public,pg_catalog"))
            revisions = (await db.execute(text("SELECT version_num FROM public.alembic_version"))).scalars().all()
            if revisions != ["0182"]:
                raise ValueError("expected_dev_schema_0182")
            if not await db.scalar(text("SELECT EXISTS(SELECT 1 FROM public.tenants WHERE id=:id)"), {"id": tenant_id}):
                raise ValueError("tenant_not_found")
            count = await purge_change_plans(db, tenant_id, dry_run=not execute, batch_size=batch_size)
            if execute:
                await db.commit()
            else:
                await db.rollback()
            return {"result": "PASS", "environment": "DEV", "tenant_id": str(tenant_id),
                    "mode": "execute" if execute else "dry_run", "count": count, "batch_size": batch_size}
    finally:
        await owner.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 500:
        parser.error("batch-size must be1..500")
    # Required by model imports; credential values remain process-local.
    from dotenv import load_dotenv

    try:
        config = dev_config(args.env_file)
        load_dotenv(args.env_file, override=True)
        result = asyncio.run(run(config, args.tenant_id, args.batch_size, args.execute))
    except Exception:
        print(json.dumps({"result": "NOT_READY", "reason": "dev_retention_gate_failed"}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
