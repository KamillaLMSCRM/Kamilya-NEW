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
    calls = 0

    async def get_transcript(self, video_ref, preferred_languages):
        type(self).calls += 1
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
        self.content_types: dict[str, str] = {}

    def put_bytes(self, key, content, *, content_type):
        if "/youtube-analysis/" in key:
            assert key.startswith("tenants/") and key.endswith(".json")
            assert content_type == "application/json"
        elif "/documents/" in key:
            assert key.startswith("tenants/") and key.endswith(".md")
            assert content_type == "text/markdown"
        else:
            raise AssertionError(f"unexpected storage key: {key}")
        self.objects[key] = content
        self.content_types[key] = content_type

    def delete_bytes(self, key):
        self.objects.pop(key, None)
        self.content_types.pop(key, None)

    def get_bytes(self, key):
        return self.objects[key]


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

    async def run(job_id: str, *, analysis_job_id=None, provider=None):
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
            provider=provider or FakeProvider(),
            storage=storage,
            index_dispatcher=dispatch_index,
            analysis_job_id=analysis_job_id,
        )

    first = await run(f"youtube-{uuid4().hex}")
    assert first["idempotent_reuse"] is False
    assert len(dispatched) == 1
    assert len(storage.objects) == 1
    assert set(storage.content_types.values()) == {"text/markdown"}
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


@pytest.mark.asyncio
async def test_analysis_and_confirmed_import_fetch_once_and_delete_artifact(
    db_session,
    make_tenant,
    make_user,
    monkeypatch,
):
    tenant = await make_tenant(name="YouTube preview handoff", slug=f"youtube-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")

    @asynccontextmanager
    async def shared_session_factory():
        yield db_session

    monkeypatch.setattr(operations, "async_session_factory", shared_session_factory)
    storage = FakeStorage()
    monkeypatch.setattr(operations, "get_storage", lambda: storage)
    provider = FakeProvider()
    FakeProvider.calls = 0

    analysis_job_id = f"analysis-{uuid4().hex}"
    db_session.add(
        AIJob(
            id=analysis_job_id,
            tenant_id=tenant.id,
            user_id=methodologist.id,
            status="pending",
            stage="queued",
            progress=0,
            params={"action": "youtube_analysis"},
        )
    )
    await db_session.flush()
    await operations.run_youtube_analysis(
        job_id=analysis_job_id,
        tenant_id=tenant.id,
        url="https://youtu.be/dQw4w9WgXcQ",
        preferred_languages=["ru"],
        provider=provider,
    )
    analysis = await db_session.scalar(select(AIJob).where(AIJob.id == analysis_job_id))
    metadata = (analysis.result or {}).get("analysis_artifact")
    assert set(metadata) == {"key", "sha256", "expires_at"}
    assert metadata["key"] in storage.objects
    assert storage.content_types[metadata["key"]] == "application/json"
    assert "plain_text" not in metadata
    assert ("Правила безопасной работы и последовательность действий сотрудника. " * 2) not in str(analysis.result)

    failed_import_job_id = f"import-failed-{uuid4().hex}"
    db_session.add(
        AIJob(
            id=failed_import_job_id,
            tenant_id=tenant.id,
            user_id=methodologist.id,
            status="pending",
            stage="queued",
            progress=0,
            params={"action": "youtube_import"},
        )
    )
    await db_session.flush()

    def fail_index(*_args):
        raise RuntimeError("index unavailable")

    failed_result = await operations.run_youtube_import(
        job_id=failed_import_job_id,
        tenant_id=tenant.id,
        user_id=methodologist.id,
        url="https://youtu.be/dQw4w9WgXcQ",
        preferred_languages=["ru"],
        analysis_job_id=analysis_job_id,
        provider=provider,
        storage=storage,
        index_dispatcher=fail_index,
    )
    assert failed_result["status"] == "failed"
    assert metadata["key"] in storage.objects

    import_job_id = f"import-{uuid4().hex}"
    db_session.add(
        AIJob(
            id=import_job_id,
            tenant_id=tenant.id,
            user_id=methodologist.id,
            status="pending",
            stage="queued",
            progress=0,
            params={"action": "youtube_import"},
        )
    )
    await db_session.flush()
    result = await operations.run_youtube_import(
        job_id=import_job_id,
        tenant_id=tenant.id,
        user_id=methodologist.id,
        url="https://youtu.be/dQw4w9WgXcQ",
        preferred_languages=["ru"],
        analysis_job_id=analysis_job_id,
        provider=provider,
        storage=storage,
        index_dispatcher=lambda *_args: None,
    )
    assert result["idempotent_reuse"] is True
    assert await db_session.scalar(
        select(func.count()).select_from(Document).where(Document.tenant_id == tenant.id)
    ) == 1
    assert provider.calls == 1
    assert metadata["key"] not in storage.objects
    assert set(storage.content_types.values()) == {"text/markdown"}
