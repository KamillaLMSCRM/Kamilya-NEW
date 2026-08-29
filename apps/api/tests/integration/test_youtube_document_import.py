"""PostgreSQL integration for YouTube transcript -> ordinary Document."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models.ai_job import AIJob
from app.models.document import Document
from app.modules.youtube_transcript import operations
from app.modules.youtube_transcript.provider import TranscriptResult, TranscriptSegment


class FakeProvider:
    async def get_transcript(self, video_ref, preferred_languages):
        text = "Правила безопасной работы и последовательность действий сотрудника. " * 5
        return TranscriptResult(
            source_type="youtube",
            video_id=video_ref.video_id,
            source_url=video_ref.source_url,
            canonical_url=video_ref.canonical_url,
            title="Учебное видео",
            channel="Kamilya test",
            language=preferred_languages[0],
            is_auto_generated=True,
            segments=[TranscriptSegment(0.0, 20.0, text)],
            retrieved_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
            provider="fake",
            duration_seconds=20.0,
        )


class FakeStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_bytes(self, key, content, *, content_type):
        assert content_type == "text/markdown"
        self.objects[key] = content

    def delete_bytes(self, key):
        self.objects.pop(key, None)


@pytest.mark.asyncio
async def test_import_persists_one_document_and_reuses_identical_source(
    db_session,
    make_tenant,
    make_user,
    monkeypatch,
):
    tenant = await make_tenant(name="YouTube integration", slug=f"youtube-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")

    @asynccontextmanager
    async def shared_session_factory():
        yield db_session

    monkeypatch.setattr(operations, "async_session_factory", shared_session_factory)
    storage = FakeStorage()
    dispatched: list[tuple[str, str, str]] = []

    def dispatch_index(job_id, document_id, tenant_id):
        dispatched.append((job_id, str(document_id), str(tenant_id)))

    async def run(job_id: str):
        db_session.add(
            AIJob(
                id=job_id,
                tenant_id=tenant.id,
                user_id=methodologist.id,
                status="pending",
                stage="queued",
                progress=0,
                params={"action": "youtube_import"},
            )
        )
        await db_session.flush()
        return await operations.run_youtube_import(
            job_id=job_id,
            tenant_id=tenant.id,
            user_id=methodologist.id,
            url="https://youtu.be/dQw4w9WgXcQ",
            preferred_languages=["ru"],
            provider=FakeProvider(),
            storage=storage,
            index_dispatcher=dispatch_index,
        )

    first = await run(f"youtube-{uuid4().hex}")
    assert first["idempotent_reuse"] is False
    assert len(dispatched) == 1
    assert len(storage.objects) == 1
    document = await db_session.scalar(
        select(Document).where(Document.id == first["document_id"], Document.tenant_id == tenant.id)
    )
    assert document is not None
    assert document.file_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert document.index_status == "processing"
    assert "Автоматические субтитры: да" in document.description
    assert await db_session.scalar(
        select(func.count()).select_from(Document).where(Document.tenant_id == tenant.id)
    ) == 1

    second = await run(f"youtube-{uuid4().hex}")
    assert second["idempotent_reuse"] is True
    assert second["document_id"] == first["document_id"]
    assert len(dispatched) == 1
    assert len(storage.objects) == 1
    assert await db_session.scalar(
        select(func.count()).select_from(Document).where(Document.tenant_id == tenant.id)
    ) == 1
