"""Bounded candidate-retention enforcement through a dedicated DB role."""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.celery_app import celery_app
from app.core.config import get_settings

DEFAULT_RETENTION_BATCH_SIZE = 50
MAX_RETENTION_BATCH_SIZE = 100


async def enforce_candidate_retention(limit: int = DEFAULT_RETENTION_BATCH_SIZE) -> dict[str, int]:
    bounded = max(1, min(limit, MAX_RETENTION_BATCH_SIZE))
    database_url = get_settings().CANDIDATE_RETENTION_DATABASE_URL
    if not database_url:
        raise RuntimeError("CANDIDATE_RETENTION_DATABASE_URL is required for candidate retention enforcement")
    engine = create_async_engine(database_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            processed = await db.scalar(
                text("SELECT enforce_expired_candidate_retention(:limit)"),
                {"limit": bounded},
            )
            await db.commit()
    finally:
        await engine.dispose()
    return {"processed": int(processed or 0), "limit": bounded}


@celery_app.task(  # type: ignore[untyped-decorator]
    name="candidate_assessments.enforce_retention"
)
def enforce_candidate_retention_task() -> dict[str, int]:
    return asyncio.run(enforce_candidate_retention())
