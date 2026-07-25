"""Durable document reindex and hash maintenance behavior."""

from __future__ import annotations

import hashlib
from uuid import uuid4

from sqlalchemy import select


async def test_document_reindex_worker_completes_and_is_idempotent(
    db_session,
    monkeypatch,
    make_tenant,
    make_user,
    make_document,
):
    from app.models.ai_job import AIJob
    from app.models.document import Document
    from app.modules.ai import ingestion
    from app.modules.documents import operations

    class SessionContext:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class StorageStub:
        def get_bytes(self, key):
            return b"approved source text"

    class IngestionStub:
        async def ingest_file(self, file_path, doc_id, tenant_id):
            return {"chunks": 3, "embeddings_written": 3}

    monkeypatch.setattr(operations, "async_session_factory", lambda: SessionContext())
    monkeypatch.setattr(operations, "get_storage", lambda: StorageStub())
    monkeypatch.setattr(ingestion, "DocumentIngestion", IngestionStub)

    tenant = await make_tenant()
    methodologist = await make_user(tenant, role="methodologist")
    document = await make_document(
        tenant,
        methodologist,
        embedding_status="pending",
        index_status="processing",
        index_revision=2,
    )
    job = AIJob(
        id=f"reindex-{uuid4()}",
        tenant_id=tenant.id,
        user_id=methodologist.id,
        status="pending",
        stage="queued",
        params={
            "action": "document_reindex",
            "document_id": str(document.id),
            "revision": 2,
        },
    )
    db_session.add(job)
    await db_session.flush()

    first = await operations.run_document_reindex(
        job.id,
        document.id,
        tenant.id,
        2,
    )
    second = await operations.run_document_reindex(
        job.id,
        document.id,
        tenant.id,
        2,
    )

    stored = await db_session.scalar(
        select(Document).where(Document.id == document.id)
    )
    stored_job = await db_session.scalar(select(AIJob).where(AIJob.id == job.id))
    assert first["index_status"] == "ready"
    assert second == first
    assert stored.index_status == "ready"
    assert stored.embedding_status == "success"
    assert stored.index_chunks_total == 3
    assert stored.index_chunks_indexed == 3
    assert stored_job.status == "completed"


async def test_document_hash_backfill_hashes_available_blobs_and_reports_missing(
    db_session,
    monkeypatch,
    make_tenant,
    make_user,
    make_document,
):
    from app.models.ai_job import AIJob
    from app.models.document import Document
    from app.modules.documents import operations

    class SessionContext:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    tenant = await make_tenant()
    methodologist = await make_user(tenant, role="methodologist")
    available = await make_document(
        tenant,
        methodologist,
        name="available.txt",
        content_sha256=None,
    )
    missing = await make_document(
        tenant,
        methodologist,
        name="missing.txt",
        content_sha256=None,
    )
    blobs = {available.s3_key: b"legacy approved source"}

    class StorageStub:
        def get_bytes(self, key):
            return blobs.get(key)

    job = AIJob(
        id=f"backfill-{uuid4()}",
        tenant_id=tenant.id,
        user_id=methodologist.id,
        status="pending",
        stage="queued",
        params={"action": "document_hash_backfill"},
    )
    db_session.add(job)
    await db_session.flush()
    monkeypatch.setattr(operations, "async_session_factory", lambda: SessionContext())
    monkeypatch.setattr(operations, "get_storage", lambda: StorageStub())

    result = await operations.run_document_hash_backfill(job.id, tenant.id)

    stored_available = await db_session.scalar(
        select(Document).where(Document.id == available.id)
    )
    stored_missing = await db_session.scalar(
        select(Document).where(Document.id == missing.id)
    )
    stored_job = await db_session.scalar(select(AIJob).where(AIJob.id == job.id))
    assert stored_available.content_sha256 == hashlib.sha256(
        b"legacy approved source"
    ).hexdigest()
    assert stored_missing.content_sha256 is None
    assert stored_missing.embedding_status == "failed"
    assert stored_missing.embedding_error == "Source file is unavailable"
    assert stored_missing.index_status == "failed"
    assert stored_missing.index_error_code == "source_blob_missing"
    assert stored_missing.index_message == (
        "Source file is unavailable. Upload a new version."
    )
    assert result["updated"] == 1
    assert result["failed"] == 1
    assert stored_job.status == "failed"
    assert stored_job.stage == "failed"
    assert stored_job.errors == result["failures"]
