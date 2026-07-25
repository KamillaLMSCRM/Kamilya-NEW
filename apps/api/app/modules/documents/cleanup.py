"""Idempotent document cleanup executed by a durable Celery job."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text

from app.core.db import async_session_factory
from app.core.storage import get_storage
from app.models.ai_job import AIJob
from app.models.document import Document
from app.modules.documents.service import list_document_usages

logger = logging.getLogger(__name__)
SUMMARIES_DIR = Path("./summaries")


async def _set_tenant(session, tenant_id: UUID) -> None:
    await session.execute(
        text("SELECT set_current_tenant(:tenant_id)"),
        {"tenant_id": str(tenant_id)},
    )


async def _mark_cleanup_failed(
    tenant_id: UUID,
    document_id: UUID,
    job_id: str,
    *,
    code: str,
    message: str,
) -> None:
    async with async_session_factory() as session:
        await _set_tenant(session, tenant_id)
        document = await session.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
            ).with_for_update()
        )
        job = await session.scalar(
            select(AIJob).where(
                AIJob.id == job_id,
                AIJob.tenant_id == tenant_id,
            ).with_for_update()
        )
        if document and document.deletion_job_id == job_id:
            document.lifecycle_status = "delete_failed"
            document.deletion_error_code = code
            document.deletion_error_message = message[:1000]
        if job and job.status != "completed":
            now = datetime.now(UTC)
            job.status = "failed"
            job.stage = "failed"
            job.message = message[:1000]
            job.errors = [{"code": code, "message": message[:1000]}]
            job.updated_at = now
            job.completed_at = now
        await session.commit()


async def run_document_cleanup(job_id: str, document_id: UUID, tenant_id: UUID) -> dict:
    """Delete document artifacts and metadata, safely resumable after a retry."""

    try:
        async with async_session_factory() as session:
            await _set_tenant(session, tenant_id)
            job = await session.scalar(
                select(AIJob).where(
                    AIJob.id == job_id,
                    AIJob.tenant_id == tenant_id,
                ).with_for_update()
            )
            if not job:
                raise RuntimeError("Document cleanup job not found")
            if job.status == "completed":
                return job.result or {"document_id": str(document_id), "deleted": True}

            document = await session.scalar(
                select(Document).where(
                    Document.id == document_id,
                    Document.tenant_id == tenant_id,
                ).with_for_update()
            )
            if not document:
                now = datetime.now(UTC)
                job.status = "completed"
                job.stage = "completed"
                job.progress = 100
                job.message = "Document already deleted"
                job.result = {"document_id": str(document_id), "deleted": True, "already_missing": True}
                job.updated_at = now
                job.completed_at = now
                await session.commit()
                return job.result

            if document.deletion_job_id != job_id:
                raise RuntimeError("Cleanup job no longer owns this document")
            if document.lifecycle_status not in {"deletion_pending", "delete_failed"}:
                raise RuntimeError("Document is not pending deletion")

            usages = await list_document_usages(session, tenant_id, document_id, limit=1)
            if usages.summary.total:
                raise RuntimeError("Document acquired a blocking usage before cleanup")

            now = datetime.now(UTC)
            document.lifecycle_status = "deletion_pending"
            document.deletion_error_code = None
            document.deletion_error_message = None
            job.status = "running"
            job.stage = "cleanup"
            job.progress = 20
            job.message = "Removing document artifacts"
            job.started_at = job.started_at or now
            job.updated_at = now
            await session.flush()

            await session.execute(
                text(
                    "DELETE FROM document_embeddings "
                    "WHERE tenant_id = :tenant_id AND doc_id = :document_id"
                ),
                {
                    "tenant_id": str(tenant_id),
                    "document_id": str(document_id),
                },
            )
            get_storage().delete_bytes(document.s3_key)
            try:
                (SUMMARIES_DIR / f"{document_id}.json").unlink()
            except FileNotFoundError:
                pass

            job.progress = 90
            job.message = "Removing document metadata"
            await session.delete(document)
            now = datetime.now(UTC)
            job.status = "completed"
            job.stage = "completed"
            job.progress = 100
            job.message = "Document deleted"
            job.result = {"document_id": str(document_id), "deleted": True}
            job.updated_at = now
            job.completed_at = now
            await session.commit()
            return job.result
    except Exception as exc:
        logger.exception("Document cleanup failed for document_id=%s job_id=%s", document_id, job_id)
        await _mark_cleanup_failed(
            tenant_id,
            document_id,
            job_id,
            code="document_cleanup_failed",
            message=str(exc),
        )
        raise
