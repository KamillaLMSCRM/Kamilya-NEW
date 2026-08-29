"""Integration coverage for the v1 multi-document generation contract.

Covers: aggregate source budget, document-count cap, index-readiness gate,
cross-tenant isolation, duplicate normalization before job submission,
serialized admission (in-flight idempotency), and the mixed-language
preflight confirmation flow. Uses the same transactional API client fixtures
as the existing document compatibility tests.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import Request
from sqlalchemy import text


def _unit_vector(index: int, dimensions: int = 4096) -> str:
    values = [0.0] * dimensions
    values[index] = 1.0
    return "[" + ",".join(str(value) for value in values) + "]"


def _same_direction_vector(index: int, dimensions: int = 4096) -> str:
    values = [0.5] * dimensions
    values[index] = 1.0
    return "[" + ",".join(str(value) for value in values) + "]"


async def _seed_committed_embedding(session, tenant_id, doc_id, sha) -> None:
    """Insert one verified embedding row for a committed document.

    Mirrors the provenance contract of `_seed_embeddings` but writes through
    the caller's session without touching the transactional fixture.
    """
    await session.execute(
        text(
            "INSERT INTO document_embeddings "
            "(id, tenant_id, doc_id, text, headings, doc_name, embedding, "
            "chunk_index, embedding_provenance_state, embedding_provider, "
            "embedding_model, embedding_revision, embedding_native_dimensions, "
            "embedding_storage_dimensions, embedding_content_sha256, "
            "embedding_source_revision, embedding_indexed_at) "
            "VALUES (:id, :tenant_id, :doc_id, :text, :headings, :doc_name, "
            "CAST(:embedding AS vector), 0, 'verified', 'test-provider', "
            "'test-model', 'v1', 4096, 4096, :sha, 'document:' || :sha, now())"
        ),
        {
            "id": uuid4().hex,
            "tenant_id": str(tenant_id),
            "doc_id": str(doc_id),
            "text": "Concurrent document chunk",
            "headings": "[]",
            "doc_name": "conc.md",
            "embedding": _same_direction_vector(0),
            "sha": sha,
        },
    )


async def _seed_embeddings(db_session, tenant, documents, vector_factory=_unit_vector) -> None:
    for position, document in enumerate(documents):
        # Fully verified provenance rows: the language sampling query and the
        # retrieval path only consider `verified` rows whose source revision
        # matches the document's current content revision. The sha derives
        # from the unique doc id so documents never collide on the
        # (tenant_id, content_sha256) unique index.
        chunk_text = document.title
        sha = hashlib.sha256(str(document.id).encode("utf-8")).hexdigest()
        await db_session.execute(
            text(
                "UPDATE documents SET content_sha256 = :sha WHERE id = :doc_id"
            ),
            {"sha": sha, "doc_id": str(document.id)},
        )
        await db_session.execute(
            text(
                "INSERT INTO document_embeddings "
                "(id, tenant_id, doc_id, text, headings, doc_name, embedding, "
                "chunk_index, embedding_provenance_state, embedding_provider, "
                "embedding_model, embedding_revision, embedding_native_dimensions, "
                "embedding_storage_dimensions, embedding_content_sha256, "
                "embedding_source_revision, embedding_indexed_at) "
                "VALUES (:id, :tenant_id, :doc_id, :text, :headings, :doc_name, "
                "CAST(:embedding AS vector), 0, 'verified', 'test-provider', "
                "'test-model', 'v1', 4096, 4096, :sha, 'document:' || :sha, now())"
            ),
            {
                "id": uuid4().hex,
                "tenant_id": str(tenant.id),
                "doc_id": str(document.id),
                "text": chunk_text,
                "headings": "[]",
                "doc_name": document.filename,
                "embedding": vector_factory(position),
                "sha": sha,
            },
        )
    await db_session.flush()


@pytest.mark.asyncio
async def test_failed_index_document_is_rejected_with_clear_code(
    client, db_session, auth_headers, make_tenant, make_user, make_document
):
    tenant = await make_tenant(name="Idx Gate", slug=f"idx-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    document = await make_document(
        tenant,
        methodologist,
        embedding_status="success",
        index_status="failed",
    )
    await _seed_embeddings(db_session, tenant, [document])

    response = await client.post(
        "/api/v1/ai/generate-course",
        json={"documents": [str(document.id)]},
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 409
    assert response.json()["details"]["code"] == "documents_index_failed"


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
    await _seed_embeddings(db_session, owner_tenant, [foreign_document])

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
    await _seed_embeddings(db_session, tenant, documents, vector_factory=_same_direction_vector)

    captured: dict = {}

    class _StubJob:
        id = "stub-job"
        status = "pending"
        course_id = None
        created_at = updated_at = datetime.now(timezone.utc)
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
        },
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 202, response.text
    params = captured.get("params") or {}
    assert params.get("documents") == [str(documents[0].id), str(documents[1].id)]


@pytest.mark.asyncio
async def test_mixed_topics_still_conflict_without_explicit_strategy(
    client, db_session, auth_headers, make_tenant, make_user, make_document
):
    tenant = await make_tenant(name="Mixed", slug=f"mixed-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    safety = await make_document(
        tenant, methodologist, name="fire.md", title="Пожарная безопасность",
        embedding_status="success", index_status="ready",
    )
    marketing = await make_document(
        tenant, methodologist, name="brand.md", title="Стандарт рекламы бренда",
        embedding_status="success", index_status="ready",
    )
    await _seed_embeddings(db_session, tenant, [safety, marketing])

    response = await client.post(
        "/api/v1/ai/generate-course",
        json={"documents": [str(safety.id), str(marketing.id)]},
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 409
    assert response.json()["details"]["code"] == "mixed_document_topics"


# ── Aggregate budget �─────────────────────────────────────────────────


async def _set_chunk_totals(db_session, documents, total: int) -> None:
    for document in documents:
        await db_session.execute(
            text("UPDATE documents SET index_chunks_total = :total WHERE id = :doc_id"),
            {"total": total, "doc_id": str(document.id)},
        )
    await db_session.flush()


@pytest.mark.asyncio
async def test_multi_document_submission_above_budget_returns_422(
    client, db_session, auth_headers, make_tenant, make_user, make_document, monkeypatch
):
    from app.core.config import get_settings

    tenant = await make_tenant(name="Budget", slug=f"budget-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    documents = [
        await make_document(tenant, methodologist, embedding_status="success", index_status="ready")
        for _ in range(2)
    ]
    await _seed_embeddings(db_session, tenant, documents, vector_factory=_same_direction_vector)
    over_limit = get_settings().AI_MULTI_DOC_MAX_TOTAL_CHUNKS
    await _set_chunk_totals(db_session, documents, over_limit)

    response = await client.post(
        "/api/v1/ai/generate-course",
        json={"documents": [str(documents[0].id), str(documents[1].id)]},
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 422
    assert response.json()["details"]["code"] == "aggregate_source_budget_exceeded"


@pytest.mark.asyncio
async def test_single_document_submission_is_exempt_from_multi_doc_budget(
    client, db_session, auth_headers, make_tenant, make_user, make_document, monkeypatch
):
    from app.core.config import get_settings

    tenant = await make_tenant(name="Single", slug=f"single-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    document = await make_document(
        tenant, methodologist, embedding_status="success", index_status="ready"
    )
    await _seed_embeddings(db_session, tenant, [document])
    over_limit = get_settings().AI_MULTI_DOC_MAX_TOTAL_CHUNKS
    await _set_chunk_totals(db_session, [document], over_limit)

    captured: dict = {}

    class _StubJob:
        id = "stub-job"
        status = "pending"
        course_id = None
        created_at = updated_at = datetime.now(timezone.utc)
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

    tenant = await make_tenant(name="AtLimit", slug=f"atlimit-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    documents = [
        await make_document(tenant, methodologist, embedding_status="success", index_status="ready")
        for _ in range(2)
    ]
    await _seed_embeddings(db_session, tenant, documents, vector_factory=_same_direction_vector)
    at_limit = get_settings().AI_MULTI_DOC_MAX_TOTAL_CHUNKS // 2
    await _set_chunk_totals(db_session, documents, at_limit)

    captured: dict = {}

    class _StubJob:
        id = "stub-job"
        status = "pending"
        course_id = None
        created_at = updated_at = datetime.now(timezone.utc)
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
        json={"documents": [str(documents[0].id), str(documents[1].id)]},
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
        await make_document(tenant, methodologist, embedding_status="success", index_status="ready")
        for _ in range(6)
    ]
    await _seed_embeddings(db_session, tenant, documents, vector_factory=_same_direction_vector)

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
        await make_document(tenant, methodologist, embedding_status="success", index_status="ready")
        for _ in range(21)
    ]
    await _seed_embeddings(db_session, tenant, documents, vector_factory=_same_direction_vector)

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
        tenant, methodologist, embedding_status="success", index_status="ready",
        lifecycle_status=lifecycle_status,
    )
    await _seed_embeddings(db_session, tenant, [document])

    response = await client.post(
        "/api/v1/ai/generate-course",
        json={"documents": [str(document.id)]},
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 404
    assert "documents_not_found" in response.text


@pytest.mark.asyncio
async def test_processing_index_document_is_rejected_as_not_ready(
    client, db_session, auth_headers, make_tenant, make_user, make_document
):
    tenant = await make_tenant(name="Processing", slug=f"proc-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    document = await make_document(
        tenant, methodologist, embedding_status="success", index_status="processing",
    )
    await _seed_embeddings(db_session, tenant, [document])

    response = await client.post(
        "/api/v1/ai/generate-course",
        json={"documents": [str(document.id)]},
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 409
    assert response.json()["details"]["code"] == "documents_index_not_ready"


# ── In-flight idempotency �────────────────────────────────────────────


@pytest.mark.asyncio
async def test_in_flight_same_document_set_in_reversed_order_returns_conflict(
    client, db_session, auth_headers, make_tenant, make_user, make_document, monkeypatch
):
    tenant = await make_tenant(name="InFlight", slug=f"inflight-{uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    documents = [
        await make_document(tenant, methodologist, embedding_status="success", index_status="ready")
        for _ in range(2)
    ]
    await _seed_embeddings(db_session, tenant, documents, vector_factory=_same_direction_vector)

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
        json={"documents": [str(documents[1].id), str(documents[0].id)]},
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 409
    body = response.json()
    assert body["details"]["code"] == "generation_already_in_progress"
    assert body["details"]["job_id"] == job.id


@pytest.mark.asyncio
async def test_concurrent_identical_submissions_create_exactly_one_job():
    """Two near-simultaneous identical HTTP submissions must admit at most
    one generation job: the admission check + insert is serialized by a
    transaction-scoped advisory lock on the tenant.

    Uses fully committed seed rows and two independent sessions: a true
    concurrent race cannot share the transactional `db_session` fixture,
    because rows created there are invisible to another session.
    """
    import asyncio

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import func, select

    from app.core.db import async_session_factory, get_db
    from app.main import app
    from app.models.document import Document
    from app.models.tenants import Tenant
    from app.models.users import User

    tenant_id = uuid4()
    user_id = uuid4()
    doc_ids = [uuid4(), uuid4()]
    shas = [hashlib.sha256(str(doc_id).encode("utf-8")).hexdigest() for doc_id in doc_ids]

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
        for position, (doc_id, sha) in enumerate(zip(doc_ids, shas)):
            setup.add(
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
                    embedding_status="success",
                    source_family_id=doc_id,
                    version=1,
                    content_sha256=sha,
                    lifecycle_status="active",
                    index_status="ready",
                    index_chunks_total=1,
                    index_chunks_indexed=1,
                    index_revision=1,
                )
            )
        await setup.commit()

    async with async_session_factory() as setup:
        await setup.execute(
            text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)}
        )
        for doc_id, sha in zip(doc_ids, shas):
            await _seed_committed_embedding(setup, tenant_id, doc_id, sha)
        await setup.commit()

    from app.core.auth import create_access_token

    token = create_access_token(
        {"sub": str(user_id), "tenant_id": str(tenant_id), "roles": ["methodologist"],
         "aud": "kamilya-lms"}
    )
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "documents": [str(doc_id) for doc_id in doc_ids],
        "target_audience": "Сотрудники",
    }

    # Two requests must truly race on the same database rows, so each gets its
    # own real session. The override inspects the ASGI client address, which
    # each request sets to a distinct value, so concurrent requests never
    # share a session. Each session's first connection is provisioned
    # sequentially before the gather: under NullPool concurrent
    # first-connection provisioning collides on the engine.
    sessions = []

    async def _patched_get_db(request: Request):
        session = sessions[0 if request.scope["client"][1] == 123 else 1]
        yield session

    async def run_request(client_port: int) -> object:
        transport = ASGITransport(app=app, client=("127.0.0.1", client_port))
        async with AsyncClient(transport=transport, base_url="http://test") as request_client:
            return await request_client.post(
                "/api/v1/ai/generate-course", json=payload, headers=headers
            )

    app.dependency_overrides[get_db] = _patched_get_db

    from app.modules.ai import job_service

    class _RecordingDispatcher:
        def __init__(self):
            self.submissions = []

        def dispatch(self, task_name, *, task_id, kwargs):
            self.submissions.append((task_name, task_id, kwargs))

    recording_dispatcher = _RecordingDispatcher()

    original_dispatcher = job_service.CeleryAIJobDispatcher
    job_service.CeleryAIJobDispatcher = lambda: recording_dispatcher
    try:
        for index in range(2):
            session = async_session_factory()
            sessions.append(session)
            await session.execute(text("SELECT 1"))
        results = await asyncio.gather(
            run_request(123), run_request(124)
        )
    finally:
        job_service.CeleryAIJobDispatcher = original_dispatcher
        app.dependency_overrides.pop(get_db, None)
        for session in sessions:
            await session.close()

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
    # One admitted, the duplicate rejected by the serialized admission gate.
    assert statuses == [202, 409]
    rejected = [r for r in results if r.status_code == 409][0]
    assert rejected.json()["details"]["code"] == "generation_already_in_progress"

    # Cleanup committed rows; RLS context scoped per transaction.
    async with async_session_factory() as cleanup:
        await cleanup.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)})
        await cleanup.execute(text("DELETE FROM ai_jobs WHERE tenant_id = :t"), {"t": str(tenant_id)})
        await cleanup.execute(text("DELETE FROM document_embeddings WHERE tenant_id = :t"), {"t": str(tenant_id)})
        await cleanup.execute(text("DELETE FROM documents WHERE tenant_id = :t"), {"t": str(tenant_id)})
        await cleanup.execute(text("DELETE FROM users WHERE tenant_id = :t"), {"t": str(tenant_id)})
        await cleanup.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": str(tenant_id)})
        await cleanup.commit()


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
        embedding_status="success", index_status="ready",
    )
    doc_kk = await make_document(
        tenant, methodologist, name="kk.md", title="Ережелер",
        embedding_status="success", index_status="ready",
    )
    await _seed_embeddings(db_session, tenant, [doc_ru, doc_kk], vector_factory=_same_direction_vector)
    # Russian chunk text for doc_ru; Kazakh chunk text for doc_kk.
    await db_session.execute(
        text("UPDATE document_embeddings SET text = 'Правила безопасности на производстве' WHERE doc_id = :d"),
        {"d": str(doc_ru.id)},
    )
    await db_session.execute(
        text("UPDATE document_embeddings SET text = 'Ережелер қауіпсіздігі бойынша нұсқаулық' WHERE doc_id = :d"),
        {"d": str(doc_kk.id)},
    )
    await db_session.flush()

    class _StubJob:
        id = "stub-job"
        status = "pending"
        course_id = None
        created_at = updated_at = datetime.now(timezone.utc)
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
        json={"documents": [str(doc_ru.id), str(doc_kk.id)], "language": "ru"},
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
    db_session, make_tenant, make_user
):
    """Pipeline save path maps writer source_references to per-lesson
    provenance and course-level source ids for a multi-document set."""
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

    state = GenerationState(
        job_id=str(uuid4()),
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

    from app.modules.courses.models import Course

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

