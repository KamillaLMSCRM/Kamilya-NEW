"""Read-only inspection for production AI smoke tenants."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_env() -> None:
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value)
    if os.getenv("MIGRATION_DATABASE_URL"):
        os.environ["DATABASE_URL"] = os.environ["MIGRATION_DATABASE_URL"]


async def main() -> None:
    load_env()
    sys.path.insert(0, str(ROOT / "apps" / "api"))

    from sqlalchemy import text
    from app.core.db import async_session_factory

    async with async_session_factory() as session:
        tenants = (
            await session.execute(
                text(
                    """
                    select id, slug, status, created_at
                    from tenants
                    where slug like 'ai-smoke-%'
                    order by created_at desc
                    limit 10
                    """
                )
            )
        ).fetchall()
        print("tenants")
        for row in tenants:
            print(" | ".join(str(v) for v in row))

        docs = (
            await session.execute(
                text(
                    """
                    select id, tenant_id, embedding_status,
                           left(coalesce(embedding_error, ''), 500) as error
                    from documents
                    where tenant_id in (
                        select id from tenants where slug like 'ai-smoke-%'
                    )
                    order by created_at desc
                    limit 10
                    """
                )
            )
        ).fetchall()
        print("documents")
        for row in docs:
            print(" | ".join(str(v) for v in row))

        jobs = (
            await session.execute(
                text(
                    """
                    select id, tenant_id, status, stage, progress,
                           left(coalesce(message, ''), 500) as message,
                           created_at
                    from ai_jobs
                    where tenant_id in (
                        select id from tenants where slug like 'ai-smoke-%'
                    )
                    order by created_at desc
                    limit 10
                    """
                )
            )
        ).fetchall()
        print("jobs")
        for row in jobs:
            print(" | ".join(str(v) for v in row))


if __name__ == "__main__":
    asyncio.run(main())
