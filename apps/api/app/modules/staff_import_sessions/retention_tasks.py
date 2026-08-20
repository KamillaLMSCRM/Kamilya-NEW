"""Scheduled retry for short-lived staff import source workbooks."""

from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy import select, text

from app.core.celery_app import celery_app
from app.core.db import async_session_factory
from app.core.storage import get_storage
from app.models.staff_import_session import StaffImportSession

from .persistence import cleanup_expired_import_sources


async def cleanup_expired_import_session_source(*, tenant_id: UUID, session_id: UUID) -> dict[str, int | str]:
    async with async_session_factory() as db:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        result = await db.execute(
            select(StaffImportSession).where(
                StaffImportSession.id == session_id,
                StaffImportSession.tenant_id == tenant_id,
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            return {"status": "not_found", "deleted": 0}
        deleted = await cleanup_expired_import_sources(
            db,
            tenant_id=tenant_id,
            storage=get_storage(),
            limit=20,
            raise_on_storage_error=True,
        )
        await db.commit()
        return {"status": "complete", "deleted": deleted}


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="staff_import.cleanup_expired_sources",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=3600,
    retry_jitter=True,
    max_retries=8,
)
def cleanup_expired_import_sources_task(self, tenant_id: str, session_id: str) -> dict[str, int | str]:
    return asyncio.run(
        cleanup_expired_import_session_source(
            tenant_id=UUID(tenant_id),
            session_id=UUID(session_id),
        )
    )
