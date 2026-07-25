"""Document cleanup worker behavior against PostgreSQL."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select


async def test_document_cleanup_removes_metadata_and_is_idempotent(
    db_session,
    monkeypatch,
    tmp_path,
    make_tenant,
    make_user,
    make_document,
):
    from app.models.ai_job import AIJob
    from app.models.document import Document
    from app.modules.documents import cleanup

    class SessionContext:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class StorageStub:
        def __init__(self):
            self.deleted = []

        def delete_bytes(self, key):
            self.deleted.append(key)
            return True

    storage = StorageStub()
    monkeypatch.setattr(cleanup, "async_session_factory", lambda: SessionContext())
    monkeypatch.setattr(cleanup, "get_storage", lambda: storage)
    monkeypatch.setattr(cleanup, "SUMMARIES_DIR", tmp_path)

    tenant = await make_tenant()
    methodologist = await make_user(tenant, role="methodologist")
    document = await make_document(
        tenant,
        methodologist,
        embedding_status="success",
        index_status="ready",
        lifecycle_status="deletion_pending",
    )
    job = AIJob(
        id=f"cleanup-{uuid4()}",
        tenant_id=tenant.id,
        user_id=methodologist.id,
        status="pending",
        stage="queued",
        params={"action": "document_cleanup", "document_id": str(document.id)},
    )
    db_session.add(job)
    document.deletion_job_id = job.id
    await db_session.flush()

    first = await cleanup.run_document_cleanup(job.id, document.id, tenant.id)
    second = await cleanup.run_document_cleanup(job.id, document.id, tenant.id)

    assert first["deleted"] is True
    assert second["deleted"] is True
    assert storage.deleted == [document.s3_key]
    assert await db_session.scalar(select(Document).where(Document.id == document.id)) is None
    stored_job = await db_session.scalar(select(AIJob).where(AIJob.id == job.id))
    assert stored_job.status == "completed"
    assert stored_job.progress == 100
