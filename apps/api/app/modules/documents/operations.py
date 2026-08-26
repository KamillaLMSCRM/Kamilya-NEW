"""Durable document indexing and maintenance operations."""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text

from app.core.db import async_session_factory
from app.core.storage import get_storage
from app.models.ai_job import AIJob
from app.models.document import Document
from app.modules.ai.ingestion import DocumentIndexingTerminalError

logger = logging.getLogger(__name__)


class DocumentSourceMissingError(RuntimeError):
    """The persisted source blob no longer exists."""


async def _set_tenant(session, tenant_id: UUID) -> None:
    await session.execute(
        text("SELECT set_current_tenant(:tenant_id)"),
        {"tenant_id": str(tenant_id)},
    )


def apply_ingestion_result(document: Document, result: dict) -> None:
    """Apply one ingestion result to both legacy and catalog status fields."""

    chunks = int(result.get("chunks", 0))
    embeddings_written = int(result.get("embeddings_written", 0))
    document.index_error_code = None
    if chunks == 0:
        message = "Ingestion produced 0 chunks (file may be empty or unsupported)"
        document.embedding_status = "failed"
        document.embedding_error = message
        document.index_status = "failed"
        document.index_error_code = "no_chunks"
        document.index_message = message
    elif embeddings_written == 0:
        message = (
            f"All {chunks} embeddings were malformed and dropped; "
            "document is not usable for AI generation."
        )
        document.embedding_status = "failed"
        document.embedding_error = message
        document.index_status = "failed"
        document.index_error_code = "no_embeddings"
        document.index_message = message
    elif embeddings_written < chunks:
        message = (
            f"Partial: {embeddings_written}/{chunks} chunks embedded; "
            "the rest were malformed and dropped."
        )
        document.embedding_status = "success"
        document.embedding_error = message
        document.index_status = "partial"
        document.index_error_code = "partial_embeddings"
        document.index_message = message
    else:
        document.embedding_status = "success"
        document.embedding_error = None
        document.index_status = "ready"
        document.index_message = None
    document.index_chunks_total = chunks
    document.index_chunks_indexed = embeddings_written
    document.indexed_at = datetime.now(UTC)


async def _mark_reindex_failed(
    tenant_id: UUID,
    document_id: UUID,
    job_id: str,
    revision: int,
    message: str,
    error_code: str = "reindex_failed",
) -> None:
    async with async_session_factory() as session:
        await _set_tenant(session, tenant_id)
        document = await session.scalar(
            select(Document)
            .where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        job = await session.scalar(
            select(AIJob)
            .where(
                AIJob.id == job_id,
                AIJob.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        if job and job.status == "cancelled":
            await session.rollback()
            return
        now = datetime.now(UTC)
        if document and document.index_revision == revision:
            document.embedding_status = "failed"
            document.embedding_error = message[:1000]
            document.index_status = "failed"
            document.index_error_code = error_code
            document.index_message = message[:1000]
            document.index_chunks_total = None
            document.index_chunks_indexed = None
        if job and job.status not in {"completed", "cancelled"}:
            job.status = "failed"
            job.stage = "failed"
            job.message = message[:1000]
            job.errors = [{"code": error_code, "message": message[:1000]}]
            job.updated_at = now
            job.completed_at = now
        await session.commit()


async def run_document_reindex(
    job_id: str,
    document_id: UUID,
    tenant_id: UUID,
    revision: int,
) -> dict:
    """Rebuild one document's embeddings and summary, safely retryable."""

    temp_path: str | None = None
    try:
        async with async_session_factory() as session:
            await _set_tenant(session, tenant_id)
            job = await session.scalar(
                select(AIJob)
                .where(AIJob.id == job_id, AIJob.tenant_id == tenant_id)
                .with_for_update()
            )
            document = await session.scalar(
                select(Document)
                .where(
                    Document.id == document_id,
                    Document.tenant_id == tenant_id,
                )
                .with_for_update()
            )
            if not job:
                raise RuntimeError("Document reindex job not found")
            if job.status == "cancelled":
                return {"job_id": job_id, "status": "cancelled"}
            if job.status == "completed":
                return job.result or {
                    "document_id": str(document_id),
                    "revision": revision,
                    "indexed": True,
                }
            if not document:
                raise RuntimeError("Document not found")
            if document.lifecycle_status != "active":
                raise RuntimeError("Only active documents can be reindexed")
            if document.index_revision != revision:
                now = datetime.now(UTC)
                job.status = "completed"
                job.stage = "superseded"
                job.progress = 100
                job.message = "Reindex superseded by a newer revision"
                job.result = {
                    "document_id": str(document_id),
                    "revision": revision,
                    "superseded": True,
                }
                job.updated_at = now
                job.completed_at = now
                await session.commit()
                return job.result

            now = datetime.now(UTC)
            document.index_status = "processing"
            document.embedding_status = "pending"
            document.index_error_code = None
            document.index_message = None
            job.status = "running"
            job.stage = "download"
            job.progress = 10
            job.message = "Reading source file"
            job.started_at = job.started_at or now
            job.updated_at = now
            storage_key = document.s3_key
            filename = document.filename
            await session.commit()

        blob = get_storage().get_bytes(storage_key)
        if blob is None:
            raise DocumentSourceMissingError(
                "Source file is unavailable. Upload a new version."
            )

        suffix = Path(filename or "").suffix
        with tempfile.NamedTemporaryFile(
            prefix=f"kamilya-reindex-{document_id}-",
            suffix=suffix,
            delete=False,
        ) as temp_file:
            temp_file.write(blob)
            temp_path = temp_file.name

        async with async_session_factory() as session:
            await _set_tenant(session, tenant_id)
            document = await session.scalar(
                select(Document)
                .where(
                    Document.id == document_id,
                    Document.tenant_id == tenant_id,
                )
                .with_for_update()
            )
            job = await session.scalar(
                select(AIJob)
                .where(AIJob.id == job_id, AIJob.tenant_id == tenant_id)
                .with_for_update()
            )
            if job and job.status == "cancelled":
                await session.rollback()
                return {"job_id": job_id, "status": "cancelled"}
            if not document or document.index_revision != revision:
                raise RuntimeError("Document reindex revision changed")
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
            if job:
                job.stage = "index"
                job.progress = 30
                job.message = "Rebuilding document index"
                job.updated_at = datetime.now(UTC)
            await session.commit()

        from app.modules.ai.ingestion import DocumentIngestion

        result = await DocumentIngestion().ingest_file(
            temp_path,
            doc_id=str(document_id),
            tenant_id=str(tenant_id),
        )

        async with async_session_factory() as session:
            await _set_tenant(session, tenant_id)
            document = await session.scalar(
                select(Document)
                .where(
                    Document.id == document_id,
                    Document.tenant_id == tenant_id,
                )
                .with_for_update()
            )
            job = await session.scalar(
                select(AIJob)
                .where(AIJob.id == job_id, AIJob.tenant_id == tenant_id)
                .with_for_update()
            )
            if not document or document.index_revision != revision:
                raise RuntimeError("Document reindex revision changed before completion")
            if not job:
                raise RuntimeError("Document reindex job not found before completion")
            if job.status == "cancelled":
                await session.rollback()
                return {"job_id": job_id, "status": "cancelled"}
            apply_ingestion_result(document, result)
            now = datetime.now(UTC)
            job.status = "completed"
            job.stage = "completed"
            job.progress = 100
            job.message = "Document index rebuilt"
            job.result = {
                "document_id": str(document_id),
                "revision": revision,
                "chunks": document.index_chunks_total,
                "embeddings_written": document.index_chunks_indexed,
                "index_status": document.index_status,
                "conversion": result.get("conversion", {}),
            }
            job.updated_at = now
            job.completed_at = now
            await session.commit()
            return job.result
    except DocumentSourceMissingError as exc:
        logger.warning(
            "Document source is missing document_id=%s revision=%s job_id=%s",
            document_id,
            revision,
            job_id,
        )
        await _mark_reindex_failed(
            tenant_id,
            document_id,
            job_id,
            revision,
            str(exc),
            error_code="source_blob_missing",
        )
        raise
    except DocumentIndexingTerminalError as exc:
        logger.warning(
            "Document content is not indexable document_id=%s revision=%s "
            "job_id=%s error_code=%s",
            document_id,
            revision,
            job_id,
            exc.error_code,
        )
        await _mark_reindex_failed(
            tenant_id,
            document_id,
            job_id,
            revision,
            str(exc),
            error_code=exc.error_code,
        )
        raise
    except Exception as exc:
        logger.exception(
            "Document reindex failed document_id=%s revision=%s job_id=%s",
            document_id,
            revision,
            job_id,
        )
        await _mark_reindex_failed(
            tenant_id,
            document_id,
            job_id,
            revision,
            str(exc),
        )
        raise
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


async def run_document_hash_backfill(job_id: str, tenant_id: UUID) -> dict:
    """Populate missing SHA-256 hashes from persisted source blobs."""

    async with async_session_factory() as session:
        await _set_tenant(session, tenant_id)
        job = await session.scalar(
            select(AIJob)
            .where(AIJob.id == job_id, AIJob.tenant_id == tenant_id)
            .with_for_update()
        )
        if not job:
            raise RuntimeError("Document hash backfill job not found")
        if job.status == "cancelled":
            return {"job_id": job_id, "status": "cancelled"}
        if job.status == "completed":
            return job.result or {"updated": 0, "failed": 0}
        document_ids = list(
            (
                await session.scalars(
                    select(Document.id).where(
                        Document.tenant_id == tenant_id,
                        Document.lifecycle_status == "active",
                        Document.content_sha256.is_(None),
                    )
                )
            ).all()
        )
        now = datetime.now(UTC)
        job.status = "running"
        job.stage = "hash_backfill"
        job.progress = 5
        job.message = f"Hashing {len(document_ids)} document(s)"
        job.started_at = job.started_at or now
        job.updated_at = now
        await session.commit()

    updated = 0
    failures: list[dict[str, str]] = []
    total = len(document_ids)
    for index, document_id in enumerate(document_ids, start=1):
        try:
            async with async_session_factory() as session:
                await _set_tenant(session, tenant_id)
                document = await session.scalar(
                    select(Document)
                    .where(
                        Document.id == document_id,
                        Document.tenant_id == tenant_id,
                    )
                    .with_for_update()
                )
                if not document or document.content_sha256:
                    continue
                blob = get_storage().get_bytes(document.s3_key)
                if blob is None:
                    document.embedding_status = "failed"
                    document.embedding_error = "Source file is unavailable"
                    document.index_status = "failed"
                    document.index_error_code = "source_blob_missing"
                    document.index_message = (
                        "Source file is unavailable. Upload a new version."
                    )
                    document.updated_at = datetime.now(UTC)
                    await session.commit()
                    raise RuntimeError("Source file is unavailable")
                document.content_sha256 = hashlib.sha256(blob).hexdigest()
                await session.commit()
                updated += 1
        except Exception as exc:
            logger.warning("Could not hash document_id=%s: %s", document_id, exc)
            failures.append({"document_id": str(document_id), "message": str(exc)[:500]})

        async with async_session_factory() as session:
            await _set_tenant(session, tenant_id)
            job = await session.scalar(
                select(AIJob)
                .where(AIJob.id == job_id, AIJob.tenant_id == tenant_id)
                .with_for_update()
            )
            if job:
                if job.status == "cancelled":
                    await session.rollback()
                    return {"job_id": job_id, "status": "cancelled"}
                job.progress = 5 + int(90 * index / max(total, 1))
                job.message = f"Hashed {index}/{total} document(s)"
                job.updated_at = datetime.now(UTC)
                await session.commit()

    async with async_session_factory() as session:
        await _set_tenant(session, tenant_id)
        job = await session.scalar(
            select(AIJob)
            .where(AIJob.id == job_id, AIJob.tenant_id == tenant_id)
            .with_for_update()
        )
        if not job:
            raise RuntimeError("Document hash backfill job disappeared")
        if job.status == "cancelled":
            return {"job_id": job_id, "status": "cancelled"}
        now = datetime.now(UTC)
        has_failures = bool(failures)
        job.status = "failed" if has_failures else "completed"
        job.stage = "failed" if has_failures else "completed"
        job.progress = 100
        job.message = (
            f"Document hash backfill completed with {len(failures)} failure(s)"
            if has_failures
            else "Document hash backfill completed"
        )
        job.result = {
            "scanned": total,
            "updated": updated,
            "failed": len(failures),
            "failures": failures,
        }
        job.errors = failures or None
        job.updated_at = now
        job.completed_at = now
        await session.commit()
        return job.result
