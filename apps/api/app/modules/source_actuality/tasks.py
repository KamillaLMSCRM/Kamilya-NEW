"""Durable Celery adapter for source-change analysis."""

from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy import text

from app.core.celery_app import celery_app
from app.core.db import async_session_factory
from app.modules.source_actuality.models import DocumentChangeReview
from app.modules.source_actuality.service import SourceActualityTransientError, process_review


async def run_review(*, tenant_id: UUID, review_id: UUID) -> dict[str, str]:
    async with async_session_factory() as db:
        try:
            await db.execute(text("SELECT set_current_tenant(:tenant_id)"), {"tenant_id": str(tenant_id)})
            review = await process_review(db, tenant_id=tenant_id, review_id=review_id)
            await db.commit()
            return {"review_id": str(review.id), "status": review.status}
        except Exception:
            await db.rollback()
            raise


async def mark_review_failed(*, tenant_id: UUID, review_id: UUID) -> dict[str, str]:
    async with async_session_factory() as db:
        await db.execute(text("SELECT set_current_tenant(:tenant_id)"), {"tenant_id": str(tenant_id)})
        review = await db.get(DocumentChangeReview, review_id, with_for_update=True)
        if review is None or review.tenant_id != tenant_id:
            await db.rollback()
            return {"review_id": str(review_id), "status": "not_found"}
        if review.status not in {"ready", "resolved"}:
            review.status = "failed"
            review.analysis_error_code = "source_analysis_retry_exhausted"
            review.analysis_error_message = "Source analysis could not be completed after bounded retries."
        await db.commit()
        return {"review_id": str(review.id), "status": review.status}


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="source_actuality.analyze_review",
    max_retries=3,
    default_retry_delay=30,
)
def analyze_review_task(self, tenant_id: str, review_id: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    tenant_uuid = UUID(tenant_id)
    review_uuid = UUID(review_id)
    try:
        return asyncio.run(run_review(tenant_id=tenant_uuid, review_id=review_uuid))
    except SourceActualityTransientError as exc:
        if self.request.retries >= self.max_retries:
            return asyncio.run(mark_review_failed(tenant_id=tenant_uuid, review_id=review_uuid))
        raise self.retry(exc=exc) from exc
