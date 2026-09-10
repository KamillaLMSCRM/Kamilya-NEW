"""Integration coverage for the v1 multi-document generation contract.

Covers: aggregate source budget derived from original-source chunking,
document-count cap, original-source admission,
cross-tenant isolation, duplicate normalization before job submission,
serialized admission (in-flight idempotency), and the mixed-language
preflight confirmation flow. Uses the same transactional API client fixtures
as the existing document compatibility tests.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from direct_source_fixtures import seed_direct_source_documents
from fastapi import Request
from sqlalchemy import text


def _source_text(title: str, chunk_count: int = 1) -> str:
    paragraph = "Operational training source content. " + ("Follow the documented procedure. " * 24)
    return f"# {title}\n\n" + "\n\n".join(
        f"{paragraph} Section {index + 1}." for index in range(chunk_count)
    )


@pytest.mark.asyncio
async def test_failed_index_document_is_accepted_when_original_source_is_valid(
    client, db_session, auth_headers, make_tenant, make_user, make_document, monkeypatch
):
    tenant = await make_tenant(name="Idx Gate", slug=f"idx-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    document = await make_document(
        tenant,
        methodologist,
        embedding_status="pending",
        index_status="failed",
    )
    await seed_direct_source_documents(db_session, monkeypatch, [document])

    class _StubJob:
        id = "stub-job"
        status = "pending"
        course_id = None
        created_at = updated_at = datetime.now(UTC)
        started_at = None
        progress = 0
        stage = "queued"
        message = ""
        errors = None

    async def _fake_submit(db, **kwargs):
        return _StubJob(), {"queue_position": 1, "estimated_wait_seconds": 0,
                            "tenant_active_jobs": 0, "tenant_active_limit": 2}

    from app.modules.ai import router as ai_router

    monkeypatch.setattr(ai_router, "submit_ai_job", _fake_submit)

    response = await client.post(
        "/api/v1/ai/generate-course",
        json={"documents": [str(document.id)]},
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 202, response.text


@pytest.mark.asyncio
async def test_cross_tenant_documents_are_not_resolvable(
    client, db_session, auth_headers, make_tenant, make_user, make_document
):
    owner_tenant = await make_tenant(name="Owner", slug=f"owner-{uuid4().hex[:8]}")
    other_tenant = await make_tenant(name="Other", slug=f"other-{uuid4().hex[:8]}")
    owner_user = await make_user(owner_tenant, role="methodologist")
    outsider = await make_user(other_tenant, role="methodologist")
    foreign_document = await make_document(
        owner_tenant,
        owner_user,
        embedding_status="success",
        index_status="ready",
    )

    response = await client.post(
        "/api/v1/ai/generate-course",
        json={"documents": [str(foreign_document.id)]},
        headers=auth_headers(outsider),
    )

    assert response.status_code == 404
    assert "documents_not_found" in response.text


@pytest.mark.asyncio
async def test_duplicate_ids_are_normalized_before_submission(
    client, db_session, auth_headers, make_tenant, make_user, make_document, monkeypatch
):
    tenant = await make_tenant(name="Dedup", slug=f"dedup-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    documents = [
        await make_document(tenant, methodologist, embedding_status="success", index_status="ready")
        for _ in range(2)
    ]
    await seed_direct_source_documents(db_session, monkeypatch, documents)

    captured: dict = {}

    class _StubJob:
        id = "stub-job"
        status = "pending"
        course_id = None
        created_at = updated_at = datetime.now(UTC)
        started_at = None
        progress = 0
        stage = "queued"
        message = ""
        errors = None

    async def _fake_submit(db, **kwargs):
        captured.update(kwargs)
        return _StubJob(), {"queue_position": 1, "estimated_wait_seconds": 0,
                            "tenant_active_jobs": 0, "tenant_active_limit": 2}

    from app.modules.ai import router as ai_router

    monkeypatch.setattr(ai_router, "submit_ai_job", _fake_submit)

    response = await client.post(
        "/api/v1/ai/generate-course",
        json={
            "documents": [str(documents[0].id), str(documents[1].id), str(documents[0].id)],
            "target_audience": "Сотрудники",
            "source_strategy": "intentional_combination",
            "combination_goal": "Объединить общие правила безопасной работы сотрудников.",
        },
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 202, response.text
    params = captured.get("params") or {}
    assert params.get("documents") == [str(documents[0].id), str(documents[1].id)]


@pytest.mark.asyncio
async def test_multiple_direct_sources_require_explicit_strategy_and_goal(
    client, db_session, auth_headers, make_tenant, make_user, make_document, monkeypatch
):
    tenant = await make_tenant(name="Mixed", slug=f"mixed-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    safety = await make_document(
        tenant, methodologist, name="fire.md", title="Пожарная безопасность",
        embedding_status="pending", index_status="processing",
    )
    marketing = await make_document(
        tenant, methodologist, name="brand.md", title="Стандарт рекламы бренда",
        embedding_status="pending", index_status="processing",
    )
    await seed_direct_source_documents(db_session, monkeypatch, [safety, marketing])

    response = await client.post(
        "/api/v1/ai/generate-course",
        json={"documents": [str(safety.id), str(marketing.id)]},
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 409
    detail = response.json()["details"]
    assert detail["code"] == "source_combination_goal_required"
    assert detail["analysis"]["analysis_mode"] == "direct_source"
    assert detail["analysis"]["score"] is None


# ── Aggregate budget �─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_multi_document_submission_above_budget_returns_422(
    client, db_session, auth_headers, make_tenant, make_user, make_document, monkeypatch
):
    from app.core.config import get_settings
    from app.modules.ai.ingestion import DocumentChunker

    tenant = await make_tenant(name="Budget", slug=f"budget-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    documents = [
        await make_document(tenant, methodologist, embedding_status="pending", index_status="processing")
        for _ in range(2)
    ]
    texts = {document.id: _source_text(f"{document.title} {document.id}") for document in documents}
    chunk_counts = {
        document.id: len(DocumentChunker().chunk_markdown(texts[document.id], str(document.id), f"{document.id}.md"))
        for document in documents
    }
    assert chunk_counts == {document.id: 1 for document in documents}
    monkeypatch.setattr(get_settings(), "AI_MULTI_DOC_MAX_TOTAL_CHUNKS", 1)
    await seed_direct_source_documents(
        db_session,
        monkeypatch,
        documents,
        texts=texts,
    )

    response = await client.post(
        "/api/v1/ai/generate-course",
        json={
            "documents": [str(documents[0].id), str(documents[1].id)],
            "source_strategy": "intentional_combination",
            "combination_goal": "Объединить общие правила безопасной работы сотрудников.",
        },
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 422
    assert response.json()["details"]["code"] == "aggregate_source_budget_exceeded"


@pytest.mark.asyncio
async def test_single_document_submission_is_exempt_from_multi_doc_budget(
    client, db_session, auth_headers, make_tenant, make_user, make_document, monkeypatch
):
    from app.core.config import get_settings
    from app.modules.ai.ingestion import DocumentChunker

    tenant = await make_tenant(name="Single", slug=f"single-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    document = await make_document(
        tenant, methodologist, embedding_status="pending", index_status="processing"
    )
    text_value = _source_text(document.title, 2)
    chunk_count = len(DocumentChunker().chunk_markdown(text_value, str(document.id), f"{document.id}.md"))
    assert chunk_count == 3
    monkeypatch.setattr(get_settings(), "AI_MULTI_DOC_MAX_TOTAL_CHUNKS", 1)
    await seed_direct_source_documents(
        db_session,
        monkeypatch,
        [document],
        texts={document.id: text_value},
    )

    captured: dict = {}

    class _StubJob:
        id = "stub-job"
        status = "pending"
        course_id = None
        created_at = updated_at = datetime.now(UTC)
        started_at = None
        progress = 0
        stage = "queued"
        message = ""
        errors = None

    async def _fake_submit(db, **kwargs):
        captured.update(kwargs)
        return _StubJob(), {"queue_position": 1, "estimated_wait_seconds": 0,
                            "tenant_active_jobs": 0, "tenant_active_limit": 2}

    from app.modules.ai import router as ai_router

    monkeypatch.setattr(ai_router, "submit_ai_job", _fake_submit)

    response = await client.post(
        "/api/v1/ai/generate-course",
        json={"documents": [str(document.id)]},
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 202, response.text
    assert (captured.get("params") or {}).get("documents") == [str(document.id)]


@pytest.mark.asyncio
async def test_multi_document_submission_at_budget_limit_is_allowed(
    client, db_session, auth_headers, make_tenant, make_user, make_document, monkeypatch
):
    from app.core.config import get_settings
    from app.modules.ai.ingestion import DocumentChunker

    tenant = await make_tenant(name="AtLimit", slug=f"atlimit-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    documents = [
        await make_document(tenant, methodologist, embedding_status="pending", index_status="processing")
        for _ in range(2)
    ]
    texts = {document.id: _source_text(f"{document.title} {document.id}") for document in documents}
    chunk_counts = {
        document.id: len(DocumentChunker().chunk_markdown(texts[document.id], str(document.id), f"{document.id}.md"))
        for document in documents
    }
    assert chunk_counts == {document.id: 1 for document in documents}
    monkeypatch.setattr(get_settings(), "AI_MULTI_DOC_MAX_TOTAL_CHUNKS", 2)
    await seed_direct_source_documents(
        db_session,
        monkeypatch,
        documents,
        texts=texts,
    )

    captured: dict = {}

    class _StubJob:
        id = "stub-job"
        status = "pending"
        course_id = None
        created_at = updated_at = datetime.now(UTC)
        started_at = None
        progress = 0
        stage = "queued"
        message = ""
        errors = None

    async def _fake_submit(db, **kwargs):
        captured.update(kwargs)
        return _StubJob(), {"queue_position": 1, "estimated_wait_seconds": 0,
                            "tenant_active_jobs": 0, "tenant_active_limit": 2}

    from app.modules.ai import router as ai_router

    monkeypatch.setattr(ai_router, "submit_ai_job", _fake_submit)

    response = await client.post(
        "/api/v1/ai/generate-course",
        json={
            "documents": [str(documents[0].id), str(documents[1].id)],
            "source_strategy": "intentional_combination",
            "combination_goal": "Объединить общие правила безопасной работы сотрудников.",
        },
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 202, response.text


@pytest.mark.asyncio
async def test_more_than_five_unique_documents_returns_stable_code(
    client, db_session, auth_headers, make_tenant, make_user, make_document
):
    tenant = await make_tenant(name="Cap", slug=f"cap-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    documents = [
        await make_document(tenant, methodologist, embedding_status="pending", index_status="processing")
        for _ in range(6)
    ]

    response = await client.post(
        "/api/v1/ai/generate-course",
        json={"documents": [str(document.id) for document in documents]},
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 422
    body = response.json()
    assert body["details"]["code"] == "too_many_documents"
    assert body["details"]["limit"] == 5


@pytest.mark.asyncio
async def test_twenty_one_documents_still_return_stable_code(
    client, db_session, auth_headers, make_tenant, make_user, make_document
):
    """Schema-level caps must not shadow the endpoint's stable
    `too_many_documents` code, so an arbitrarily large selection reaches
    the endpoint unchanged."""
    tenant = await make_tenant(name="Cap21", slug=f"cap21-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    documents = [
        await make_document(tenant, methodologist, embedding_status="pending", index_status="processing")
        for _ in range(21)
    ]

    response = await client.post(
        "/api/v1/ai/generate-course",
        json={"documents": [str(document.id) for document in documents]},
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 422
    body = response.json()
    assert body["details"]["code"] == "too_many_documents"
    assert body["details"]["limit"] == 5


# ── Lifecycle states �─────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("lifecycle_status", ["deletion_pending", "delete_failed"])
async def test_non_active_lifecycle_documents_cannot_enter_generation(
    client, db_session, auth_headers, make_tenant, make_user, make_document, lifecycle_status
):
    tenant = await make_tenant(name="Lifecycle", slug=f"lc-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    document = await make_document(
        tenant, methodologist, embedding_status="pending", index_status="processing",
        lifecycle_status=lifecycle_status,
    )

    response = await client.post(
        "/api/v1/ai/generate-course",
        json={"documents": [str(document.id)]},
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 404
    assert "documents_not_found" in response.text


@pytest.mark.asyncio
async def test_processing_index_document_is_accepted_when_original_source_is_valid(
    client, db_session, auth_headers, make_tenant, make_user, make_document, monkeypatch
):
    tenant = await make_tenant(name="Processing", slug=f"proc-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    document = await make_document(
        tenant, methodologist, embedding_status="pending", index_status="processing",
    )
    await seed_direct_source_documents(db_session, monkeypatch, [document])

    class _StubJob:
        id = "stub-job"
        status = "pending"
        course_id = None
        created_at = updated_at = datetime.now(UTC)
        started_at = None
        progress = 0
        stage = "queued"
        message = ""
        errors = None

    async def _fake_submit(db, **kwargs):
        return _StubJob(), {"queue_position": 1, "estimated_wait_seconds": 0,
                            "tenant_active_jobs": 0, "tenant_active_limit": 2}

    from app.modules.ai import router as ai_router

    monkeypatch.setattr(ai_router, "submit_ai_job", _fake_submit)

    response = await client.post(
        "/api/v1/ai/generate-course",
        json={"documents": [str(document.id)]},
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 202, response.text


# ── In-flight idempotency �────────────────────────────────────────────


@pytest.mark.asyncio
async def test_in_flight_same_document_set_in_reversed_order_returns_conflict(
    client, db_session, auth_headers, make_tenant, make_user, make_document, monkeypatch
):
    tenant = await make_tenant(name="InFlight", slug=f"inflight-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    documents = [
        await make_document(tenant, methodologist, embedding_status="pending", index_status="processing")
        for _ in range(2)
    ]
    await seed_direct_source_documents(db_session, monkeypatch, documents)

    from app.models.ai_job import AIJob

    job = AIJob(
        id=str(uuid4()),
        tenant_id=tenant.id,
        user_id=methodologist.id,
        status="running",
        stage="architect",
        params={"documents": [str(documents[0].id), str(documents[1].id)]},
    )
    db_session.add(job)
    await db_session.flush()

    response = await client.post(
        "/api/v1/ai/generate-course",
        json={
            "documents": [str(documents[1].id), str(documents[0].id)],
            "source_strategy": "intentional_combination",
            "combination_goal": "Объединить общие правила безопасной работы сотрудников.",
        },
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 409
    body = response.json()
    assert body["details"]["code"] == "generation_already_in_progress"
    assert body["details"]["job_id"] == job.id


@pytest.mark.asyncio
async def test_concurrent_identical_submissions_create_exactly_one_job(monkeypatch):
    """Two near-simultaneous identical HTTP submissions must admit at most
    one generation job: the admission check + insert is serialized by a
    transaction-scoped advisory lock on the tenant.

    Uses fully committed seed rows and two independent sessions: a true
    concurrent race cannot share the transactional `db_session` fixture,
    because rows created there are invisible to another session.
    """
    import asyncio

    from httpx import ASGITransport, AsyncClient

    from app.core.db import async_session_factory, get_db
    from app.main import app
    from app.models.document import Document
    from app.models.tenants import Tenant
    from app.models.users import User

    tenant_id = uuid4()
    user_id = uuid4()
    doc_ids = [uuid4(), uuid4()]
    sessions = []
    results = None

    async def _cleanup_committed_rows() -> None:
        async with async_session_factory() as cleanup:
            await cleanup.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)})
            await cleanup.execute(text("DELETE FROM ai_jobs WHERE tenant_id = :t"), {"t": str(tenant_id)})
            await cleanup.execute(text("DELETE FROM documents WHERE tenant_id = :t"), {"t": str(tenant_id)})
            await cleanup.execute(text("DELETE FROM users WHERE tenant_id = :t"), {"t": str(tenant_id)})
            await cleanup.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": str(tenant_id)})
            await cleanup.commit()

    async def _patched_get_db(request: Request):
        session = sessions[0 if request.scope["client"][1] == 123 else 1]
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()

    async def run_request(client_port: int) -> object:
        transport = ASGITransport(app=app, client=("127.0.0.1", client_port))
        async with AsyncClient(transport=transport, base_url="http://test") as request_client:
            return await request_client.post(
                "/api/v1/ai/generate-course", json=payload, headers=headers
            )

    from app.core.auth import create_access_token
    from app.modules.ai import job_service

    class _RecordingDispatcher:
        def __init__(self):
            self.submissions = []

        def dispatch(self, task_name, *, task_id, kwargs):
            self.submissions.append((task_name, task_id, kwargs))

    recording_dispatcher = _RecordingDispatcher()
    original_dispatcher = job_service.CeleryAIJobDispatcher
    app.dependency_overrides[get_db] = _patched_get_db
    job_service.CeleryAIJobDispatcher = lambda: recording_dispatcher
    try:
        async with async_session_factory() as setup:
            setup.add(
                Tenant(
                    id=tenant_id,
                    name="Concurrent",
                    slug=f"conc-{uuid4().hex[:8]}",
                    status="active",
                    plan="free",
                    settings={},
                )
            )
            await setup.commit()

        async with async_session_factory() as setup:
            await setup.execute(
                text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)}
            )
            setup.add(
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    email=f"conc-{uuid4().hex[:8]}@example.test",
                    first_name="Conc",
                    last_name="Test",
                    role="methodologist",
                    is_active=True,
                )
            )
            documents = [
                Document(
                    id=doc_id,
                    tenant_id=tenant_id,
                    uploaded_by=user_id,
                    title=f"Conc doc {position}",
                    filename=f"conc-{position}.md",
                    content_type="text/markdown",
                    size=1024,
                    s3_key=f"tenants/{tenant_id}/{doc_id}",
                    description="",
                    category="general",
                    embedding_status="pending",
                    source_family_id=doc_id,
                    version=1,
                    lifecycle_status="active",
                    index_status="processing",
                )
                for position, doc_id in enumerate(doc_ids)
            ]
            setup.add_all(documents)
            await setup.flush()
            await seed_direct_source_documents(setup, monkeypatch, documents)
            await setup.commit()

        token = create_access_token(
            {"sub": str(user_id), "tenant_id": str(tenant_id), "roles": ["methodologist"],
             "aud": "kamilya-lms"}
        )
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "documents": [str(doc_id) for doc_id in doc_ids],
            "target_audience": "Сотрудники",
            "source_strategy": "intentional_combination",
            "combination_goal": "Объединить общие правила безопасной работы сотрудников.",
        }

        for _ in range(2):
            session = async_session_factory()
            sessions.append(session)
            await session.execute(text("SELECT 1"))
        results = await asyncio.wait_for(
            asyncio.gather(run_request(123), run_request(124)),
            timeout=15,
        )

        statuses = sorted(response.status_code for response in results)
        async with async_session_factory() as check:
            await check.execute(
                text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)}
            )
            job_count = (
                await check.execute(
                    text("SELECT count(*) FROM ai_jobs WHERE tenant_id = :t"),
                    {"t": str(tenant_id)},
                )
            ).scalar_one()
        assert job_count == 1
        assert statuses == [202, 409]
        rejected = [response for response in results if response.status_code == 409][0]
        assert rejected.json()["details"]["code"] == "generation_already_in_progress"
    finally:
        job_service.CeleryAIJobDispatcher = original_dispatcher
        app.dependency_overrides.pop(get_db, None)
        for session in sessions:
            await session.rollback()
            await session.close()
        await _cleanup_committed_rows()


# ── Mixed-language explicit warning ──────────────────────────────────


@pytest.mark.asyncio
async def test_mixed_language_requires_explicit_confirmation_before_queueing(
    client, db_session, auth_headers, make_tenant, make_user, make_document, monkeypatch
):
    """A mixed-language multi-document set is refused (409) until the
    methodologist explicitly confirms the course language; after
    confirmation the submission queues with a structured warning."""
    tenant = await make_tenant(name="LangMix", slug=f"lang-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    doc_ru = await make_document(
        tenant, methodologist, name="ru.md", title="Правила",
        embedding_status="pending", index_status="processing",
    )
    doc_kk = await make_document(
        tenant, methodologist, name="kk.md", title="Ережелер",
        embedding_status="pending", index_status="processing",
    )
    await seed_direct_source_documents(
        db_session,
        monkeypatch,
        [doc_ru, doc_kk],
        texts={
            doc_ru.id: "# Правила\n\nПравила безопасности на производстве.",
            doc_kk.id: "# Ережелер\n\nЕрежелер қауіпсіздігі бойынша нұсқаулық.",
        },
    )

    class _StubJob:
        id = "stub-job"
        status = "pending"
        course_id = None
        created_at = updated_at = datetime.now(UTC)
        started_at = None
        progress = 0
        stage = "queued"
        message = ""
        errors = None

    async def _fake_submit(db, **kwargs):
        return _StubJob(), {"queue_position": 1, "estimated_wait_seconds": 0,
                            "tenant_active_jobs": 0, "tenant_active_limit": 2}

    from app.modules.ai import router as ai_router

    monkeypatch.setattr(ai_router, "submit_ai_job", _fake_submit)

    first = await client.post(
        "/api/v1/ai/generate-course",
        json={
            "documents": [str(doc_ru.id), str(doc_kk.id)],
            "language": "ru",
            "source_strategy": "intentional_combination",
            "combination_goal": "Объединить общие правила безопасной работы сотрудников.",
        },
        headers=auth_headers(methodologist),
    )

    assert first.status_code == 409, first.text
    detail = first.json()["details"]
    assert detail["code"] == "mixed_language_sources"
    assert set(detail["detected_languages"]) == {"ru", "kk"}

    # No job may have been created by the refused preflight submission.
    jobs = (
        await db_session.execute(text("SELECT count(*) FROM ai_jobs WHERE tenant_id = :t"), {"t": str(tenant.id)})
    ).scalar()
    assert jobs == 0

    second = await client.post(
        "/api/v1/ai/generate-course",
        json={
            "documents": [str(doc_ru.id), str(doc_kk.id)],
            "language": "ru",
            "language_confirmed": True,
            "source_strategy": "intentional_combination",
            "combination_goal": "Объединить общие правила безопасной работы сотрудников.",
        },
        headers=auth_headers(methodologist),
    )

    assert second.status_code == 202, second.text
    warning = second.json().get("mixed_language_warning")
    assert warning is not None
    assert warning["code"] == "mixed_language_sources"
    assert set(warning["detected_languages"]) == {"ru", "kk"}
    assert warning["course_language"] == "ru"


# ── Provenance persistence (pipeline save path, no providers) ────────


@pytest.mark.asyncio
async def test_multi_document_provenance_persisted_for_course_and_lessons(
    db_session, make_tenant, make_user, monkeypatch
):
    """Pipeline save path maps writer source_references to per-lesson
    provenance and course-level source ids for a multi-document set."""
    from app.models.ai_job import AIJob
    from app.modules.ai import pipeline
    from app.modules.ai.pipeline import GenerationState, _save_generation_to_db
    from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent

    tenant = await make_tenant(name="Provenance", slug=f"prov-{uuid4().hex[:8]}")
    user = await make_user(tenant, role="methodologist")
    doc_a, doc_b = str(uuid4()), str(uuid4())

    lesson_content = LessonContent(title="Урок", objectives=["Цель"], content="# Урок")
    lesson_content.source_references = [
        {"document": "a.pdf", "doc_id": doc_a, "headings": ["Раздел 1"], "context_sections": []},
        {"document": "b.pdf", "doc_id": doc_b, "headings": ["Раздел 2"], "context_sections": []},
    ]

    job_id = str(uuid4())
    db_session.add(
        AIJob(
            id=job_id,
            tenant_id=tenant.id,
            user_id=user.id,
            status="running",
            stage="writer",
        )
    )
    await db_session.flush()

    @asynccontextmanager
    async def _transactional_session():
        yield db_session

    monkeypatch.setattr(pipeline, "async_session_factory", _transactional_session)

    state = GenerationState(
        job_id=job_id,
        source_document_ids=[doc_a, doc_b],
        source_strategy="single_topic",
    )
    state.structure = type(
        "Structure",
        (),
        {
            "title": "Курс",
            "description": "",
            "modules": [
                type("M", (), {"title": "Модуль", "description": "", "lessons": [
                    type("L", (), {"title": "Урок"})()
                ]})()
            ],
        },
    )()
    state.content = CourseContent(
        title="Курс", description="", modules=[ModuleContent(title="Модуль", lessons=[lesson_content])]
    )

    class _FakeAssessment:
        assessments = []

    state.assessment = _FakeAssessment()
    await _save_generation_to_db(state, tenant.id, user.id)
    await db_session.commit()

    course = (
        await db_session.execute(
            text("SELECT source_document_ids, source_strategy FROM courses WHERE tenant_id = :t"),
            {"t": str(tenant.id)},
        )
    ).fetchone()
    assert course is not None
    assert sorted(course[0]) == sorted([doc_a, doc_b])
    assert course[1] == "single_topic"

    lesson_row = (
        await db_session.execute(
            text(
                "SELECT l.source_document_ids, l.source_references "
                "FROM lessons l WHERE l.tenant_id = :t"
            ),
            {"t": str(tenant.id)},
        )
    ).fetchone()
    assert lesson_row is not None
    assert sorted(lesson_row[0]) == sorted([doc_a, doc_b])
    reference_doc_ids = {ref.get("doc_id") for ref in lesson_row[1]}
    assert reference_doc_ids == {doc_a, doc_b}

