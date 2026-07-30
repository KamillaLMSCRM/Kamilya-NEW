"""Wave 2.1 source catalog API contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

INTERNAL_FIELDS = {"tenant_id", "uploaded_by", "s3_key"}


@pytest.mark.parametrize("role", ["admin", "student", "superadmin"])
@pytest.mark.parametrize(
    "operation",
    ["list", "get", "download", "usages", "reindex", "backfill", "delete"],
)
async def test_documents_endpoints_deny_non_methodologist_roles(
    client, make_tenant, make_user, make_document, auth_headers, role, operation
):
    tenant = await make_tenant()
    owner = await make_user(tenant, role="methodologist")
    document = await make_document(tenant, owner)
    caller = await make_user(tenant, role=role)
    method, path = {
        "list": ("GET", "/api/v1/documents/catalog"),
        "get": ("GET", f"/api/v1/documents/{document.id}"),
        "download": ("GET", f"/api/v1/documents/{document.id}/download"),
        "usages": ("GET", f"/api/v1/documents/{document.id}/usages"),
        "reindex": ("POST", f"/api/v1/documents/{document.id}/reindex"),
        "backfill": ("POST", "/api/v1/documents/maintenance/hash-backfill"),
        "delete": ("DELETE", f"/api/v1/documents/{document.id}"),
    }[operation]

    response = await client.request(method, path, headers=auth_headers(caller))

    assert response.status_code == 403


async def test_documents_catalog_denies_superadmin_without_tenant_context(client, make_superadmin, auth_headers):
    superadmin = await make_superadmin()

    response = await client.get(
        "/api/v1/documents/catalog",
        headers=auth_headers(superadmin),
    )

    assert response.status_code == 403


@pytest.mark.parametrize("operation", ["list", "get", "download", "usages", "delete"])
async def test_documents_endpoints_allow_methodologist(
    client,
    monkeypatch,
    make_tenant,
    make_user,
    make_document,
    auth_headers,
    operation,
):
    from app.modules.documents import router as documents_router

    class StorageStub:
        def get_bytes(self, key):
            return b"document bytes"

    monkeypatch.setattr(documents_router, "get_storage", lambda: StorageStub())
    tenant = await make_tenant()
    user = await make_user(tenant, role="methodologist")
    document = await make_document(
        tenant,
        user,
        embedding_status="success",
        index_status="ready",
    )
    method, path = {
        "list": ("GET", "/api/v1/documents/catalog"),
        "get": ("GET", f"/api/v1/documents/{document.id}"),
        "download": ("GET", f"/api/v1/documents/{document.id}/download"),
        "usages": ("GET", f"/api/v1/documents/{document.id}/usages"),
        "delete": ("DELETE", f"/api/v1/documents/{document.id}"),
    }[operation]

    if operation == "delete":
        monkeypatch.setattr(
            documents_router,
            "_dispatch_document_cleanup",
            lambda *args, **kwargs: None,
        )
    response = await client.request(method, path, headers=auth_headers(user))

    assert response.status_code in {200, 202}


async def test_documents_catalog_allows_methodologist_and_hides_internal_metadata(
    client, make_tenant, make_user, make_document, auth_headers
):
    tenant = await make_tenant()
    user = await make_user(tenant, role="methodologist")
    document = await make_document(
        tenant,
        user,
        content_sha256=None,
        index_status="ready",
    )

    response = await client.get("/api/v1/documents/catalog", headers=auth_headers(user))

    assert response.status_code == 200
    body = response.json()
    assert body["page"] == {"next_cursor": None, "has_more": False, "limit": 25}
    assert [item["id"] for item in body["items"]] == [str(document.id)]
    assert INTERNAL_FIELDS.isdisjoint(body["items"][0])


async def test_legacy_documents_list_remains_safe_array(client, make_tenant, make_user, make_document, auth_headers):
    tenant = await make_tenant()
    user = await make_user(tenant, role="methodologist")
    document = await make_document(tenant, user)

    response = await client.get("/api/v1/documents", headers=auth_headers(user))

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert [item["id"] for item in body] == [str(document.id)]
    assert INTERNAL_FIELDS.isdisjoint(body[0])


@pytest.mark.parametrize("path_suffix", ["", "/download", "/usages"])
async def test_document_get_and_download_are_cross_tenant_404(
    client, make_tenant, make_user, make_document, auth_headers, path_suffix
):
    tenant_a = await make_tenant()
    user_a = await make_user(tenant_a, role="methodologist")
    document = await make_document(tenant_a, user_a)
    tenant_b = await make_tenant()
    user_b = await make_user(tenant_b, role="methodologist")

    response = await client.get(
        f"/api/v1/documents/{document.id}{path_suffix}",
        headers=auth_headers(user_b),
    )

    assert response.status_code == 404


async def test_document_delete_is_cross_tenant_404(client, make_tenant, make_user, make_document, auth_headers):
    tenant_a = await make_tenant()
    user_a = await make_user(tenant_a, role="methodologist")
    document = await make_document(tenant_a, user_a)
    tenant_b = await make_tenant()
    user_b = await make_user(tenant_b, role="methodologist")

    response = await client.delete(
        f"/api/v1/documents/{document.id}",
        headers=auth_headers(user_b),
    )

    assert response.status_code == 404


async def test_single_document_public_dto_hides_internal_metadata(
    client, make_tenant, make_user, make_document, auth_headers
):
    tenant = await make_tenant()
    user = await make_user(tenant, role="methodologist")
    document = await make_document(tenant, user)

    response = await client.get(
        f"/api/v1/documents/{document.id}",
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    assert INTERNAL_FIELDS.isdisjoint(response.json())


async def test_catalog_uses_stable_cursor_when_sort_keys_tie(
    client, make_tenant, make_user, make_document, auth_headers
):
    tenant = await make_tenant()
    user = await make_user(tenant, role="methodologist")
    created_at = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
    documents = [
        await make_document(
            tenant,
            user,
            id=uuid4(),
            name=f"same-time-{number}.md",
            created_at=created_at,
        )
        for number in range(3)
    ]

    first = await client.get(
        "/api/v1/documents/catalog?limit=2&sort=created_desc",
        headers=auth_headers(user),
    )
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["page"]["has_more"] is True
    assert first_body["page"]["next_cursor"]

    second = await client.get(
        "/api/v1/documents/catalog",
        params={
            "limit": 2,
            "sort": "created_desc",
            "cursor": first_body["page"]["next_cursor"],
        },
        headers=auth_headers(user),
    )
    assert second.status_code == 200
    ids = [item["id"] for item in first_body["items"] + second.json()["items"]]
    assert len(ids) == len(set(ids)) == len(documents)


async def test_catalog_filters_q_category_index_status_used_and_sort(
    client, db_session, make_tenant, make_user, make_document, auth_headers
):
    from app.modules.positions.models import Position

    tenant = await make_tenant()
    user = await make_user(tenant, role="methodologist")
    unused = await make_document(
        tenant,
        user,
        name="unused.md",
        title="Archived handbook",
        category="general",
        index_status="failed",
    )
    used = await make_document(
        tenant,
        user,
        name="cashier.docx",
        title="Cashier handbook",
        category="job_instruction",
        index_status="ready",
        size=2048,
    )
    db_session.add(
        Position(
            tenant_id=tenant.id,
            name="Cashier",
            department="Retail",
            instruction_document_id=used.id,
        )
    )
    await db_session.flush()

    response = await client.get(
        "/api/v1/documents/catalog",
        params={
            "q": "cashier",
            "category": "job_instruction",
            "index_status": "ready",
            "used": "true",
            "sort": "size_desc",
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [str(used.id)]
    assert str(unused.id) not in {item["id"] for item in response.json()["items"]}


async def test_catalog_defaults_to_active_and_methodologist_can_query_recovery(
    client, make_tenant, make_user, make_document, auth_headers
):
    tenant = await make_tenant()
    methodologist = await make_user(tenant, role="methodologist")
    active = await make_document(tenant, methodologist, lifecycle_status="active")
    failed = await make_document(
        tenant,
        methodologist,
        name="failed-delete.md",
        lifecycle_status="delete_failed",
    )

    default_response = await client.get(
        "/api/v1/documents/catalog",
        headers=auth_headers(methodologist),
    )
    recovery_response = await client.get(
        "/api/v1/documents/catalog?lifecycle_status=delete_failed",
        headers=auth_headers(methodologist),
    )

    assert [item["id"] for item in default_response.json()["items"]] == [str(active.id)]
    assert [item["id"] for item in recovery_response.json()["items"]] == [str(failed.id)]


async def test_catalog_latest_ignores_newer_version_outside_lifecycle_scope(
    client, make_tenant, make_user, make_document, auth_headers
):
    tenant = await make_tenant()
    methodologist = await make_user(tenant, role="methodologist")
    active = await make_document(tenant, methodologist, version=1)
    await make_document(
        tenant,
        methodologist,
        name="pending-delete-v2.md",
        source_family_id=active.source_family_id,
        version=2,
        lifecycle_status="deletion_pending",
    )

    response = await client.get(
        "/api/v1/documents/catalog",
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == str(active.id)
    assert response.json()["items"][0]["is_latest"] is True


async def test_catalog_rejects_tampered_cursor(client, make_tenant, make_user, auth_headers):
    tenant = await make_tenant()
    user = await make_user(tenant, role="methodologist")

    response = await client.get(
        "/api/v1/documents/catalog?cursor=not-a-signed-cursor",
        headers=auth_headers(user),
    )

    assert response.status_code == 422


@pytest.mark.parametrize("role", ["admin", "student", "superadmin"])
async def test_document_upload_denies_non_methodologist_roles(client, make_tenant, make_user, auth_headers, role):
    tenant = await make_tenant()
    caller = await make_user(tenant, role=role)

    response = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("source.txt", b"safe source text", "text/plain")},
        headers=auth_headers(caller),
    )

    assert response.status_code == 403


async def test_document_upload_allows_methodologist_without_external_services(
    client,
    monkeypatch,
    tmp_path,
    make_tenant,
    make_user,
    auth_headers,
):
    from app.modules.documents import router as documents_router

    class StorageStub:
        def put_bytes(self, key, content, content_type):
            assert key.startswith(f"tenants/{tenant.id}/documents/")
            assert content == b"safe source text"
            assert content_type == "text/plain"

    tenant = await make_tenant()
    methodologist = await make_user(tenant, role="methodologist")
    monkeypatch.setattr(documents_router, "get_storage", lambda: StorageStub())
    dispatched = []
    monkeypatch.setattr(
        documents_router,
        "_dispatch_document_reindex",
        lambda job_id, document_id, tenant_id, revision: dispatched.append(
            (job_id, str(document_id), str(tenant_id), revision)
        ),
    )

    response = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("source.txt", b"safe source text", "text/plain")},
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 201
    assert response.json()["embedding_status"] == "pending"
    assert response.json()["indexing_job_id"]
    assert response.json()["status_url"].endswith(response.json()["indexing_job_id"])
    assert dispatched == [
        (
            response.json()["indexing_job_id"],
            response.json()["id"],
            str(tenant.id),
            1,
        )
    ]
    assert INTERNAL_FIELDS.isdisjoint(response.json())


async def test_document_upload_hashes_content_and_rejects_exact_duplicate(
    client,
    db_session,
    monkeypatch,
    tmp_path,
    make_tenant,
    make_user,
    auth_headers,
):
    import hashlib

    from sqlalchemy import select

    from app.models.document import Document
    from app.modules.documents import router as documents_router

    class StorageStub:
        def put_bytes(self, key, content, content_type):
            return key

        def delete_bytes(self, key):
            return True

    tenant = await make_tenant()
    methodologist = await make_user(tenant, role="methodologist")
    monkeypatch.setattr(documents_router, "get_storage", lambda: StorageStub())
    dispatched = []
    monkeypatch.setattr(
        documents_router,
        "_dispatch_document_reindex",
        lambda job_id, document_id, tenant_id, revision: dispatched.append(
            (job_id, str(document_id), str(tenant_id), revision)
        ),
    )
    content = b"same approved policy text"

    first = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("policy-v1.txt", content, "text/plain")},
        headers=auth_headers(methodologist),
    )
    duplicate = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("renamed-policy.txt", content, "text/plain")},
        headers=auth_headers(methodologist),
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    detail = duplicate.json()["details"]
    assert detail["code"] == "duplicate_document"
    assert detail["existing"]["id"] == first.json()["id"]
    stored = await db_session.scalar(
        select(Document).where(Document.id == first.json()["id"])
    )
    assert stored.content_sha256 == hashlib.sha256(content).hexdigest()
    assert stored.source_family_id == stored.id
    assert stored.version == 1


async def test_document_upload_creates_explicit_next_version(
    client,
    db_session,
    monkeypatch,
    tmp_path,
    make_tenant,
    make_user,
    auth_headers,
):
    from sqlalchemy import select

    from app.models.document import Document
    from app.modules.documents import router as documents_router

    class StorageStub:
        def put_bytes(self, key, content, content_type):
            return key

        def delete_bytes(self, key):
            return True

    tenant = await make_tenant()
    methodologist = await make_user(tenant, role="methodologist")
    monkeypatch.setattr(documents_router, "get_storage", lambda: StorageStub())
    dispatched = []
    monkeypatch.setattr(
        documents_router,
        "_dispatch_document_reindex",
        lambda job_id, document_id, tenant_id, revision: dispatched.append(
            (job_id, str(document_id), str(tenant_id), revision)
        ),
    )
    first = await client.post(
        "/api/v1/documents/upload",
        data={"title": "Safety policy", "category": "job_instruction"},
        files={"file": ("policy-v1.txt", b"approved policy v1", "text/plain")},
        headers=auth_headers(methodologist),
    )
    second = await client.post(
        "/api/v1/documents/upload",
        data={
            "title": "Safety policy",
            "category": "general",
            "new_version_of": first.json()["id"],
        },
        files={"file": ("policy-v2.txt", b"approved policy v2", "text/plain")},
        headers=auth_headers(methodologist),
    )

    assert first.status_code == second.status_code == 201
    first_row = await db_session.scalar(
        select(Document).where(Document.id == first.json()["id"])
    )
    second_row = await db_session.scalar(
        select(Document).where(Document.id == second.json()["id"])
    )
    assert second_row.source_family_id == first_row.source_family_id
    assert second_row.version == 2
    assert second_row.category == "job_instruction"


async def test_document_reindex_is_durable_and_reuses_active_job(
    client,
    db_session,
    monkeypatch,
    make_tenant,
    make_user,
    make_document,
    auth_headers,
):
    from sqlalchemy import select

    from app.models.ai_job import AIJob
    from app.models.document import Document
    from app.modules.documents import router as documents_router

    dispatched = []
    monkeypatch.setattr(
        documents_router,
        "_dispatch_document_reindex",
        lambda job_id, document_id, tenant_id, revision: dispatched.append(
            (job_id, str(document_id), str(tenant_id), revision)
        ),
    )
    tenant = await make_tenant()
    methodologist = await make_user(tenant, role="methodologist")
    document = await make_document(
        tenant,
        methodologist,
        embedding_status="success",
        index_status="ready",
        index_revision=1,
    )

    first = await client.post(
        f"/api/v1/documents/{document.id}/reindex",
        headers=auth_headers(methodologist),
    )
    second = await client.post(
        f"/api/v1/documents/{document.id}/reindex",
        headers=auth_headers(methodologist),
    )

    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]
    assert first.json()["revision"] == 2
    assert len(dispatched) == 1
    stored = await db_session.scalar(
        select(Document).where(Document.id == document.id)
    )
    job = await db_session.scalar(
        select(AIJob).where(AIJob.id == first.json()["job_id"])
    )
    assert stored.index_status == "processing"
    assert stored.index_revision == 2
    assert job.params["action"] == "document_reindex"


async def test_document_hash_backfill_reuses_active_job(
    client,
    monkeypatch,
    make_tenant,
    make_user,
    auth_headers,
):
    from app.modules.documents import router as documents_router

    dispatched = []
    monkeypatch.setattr(
        documents_router,
        "_dispatch_document_hash_backfill",
        lambda job_id, tenant_id: dispatched.append((job_id, str(tenant_id))),
    )
    tenant = await make_tenant()
    methodologist = await make_user(tenant, role="methodologist")

    first = await client.post(
        "/api/v1/documents/maintenance/hash-backfill",
        headers=auth_headers(methodologist),
    )
    second = await client.post(
        "/api/v1/documents/maintenance/hash-backfill",
        headers=auth_headers(methodologist),
    )

    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]
    assert len(dispatched) == 1


async def test_document_usages_lists_all_blocking_product_links(
    client,
    db_session,
    make_tenant,
    make_user,
    make_document,
    make_course,
    make_module,
    make_lesson,
    auth_headers,
):
    from app.models.ai_job import AIJob
    from app.modules.positions.models import Position

    tenant = await make_tenant()
    methodologist = await make_user(tenant, role="methodologist")
    document = await make_document(
        tenant,
        methodologist,
        embedding_status="success",
        index_status="ready",
    )
    position = Position(
        tenant_id=tenant.id,
        name="Cashier",
        department="Retail",
        instruction_document_id=document.id,
    )
    db_session.add(position)
    course = await make_course(tenant, methodologist, title="Cashier onboarding")
    course.source_instruction_id = document.id
    course.source_document_ids = [str(document.id)]
    module = await make_module(course)
    lesson = await make_lesson(module, title="First shift")
    lesson.source_document_ids = [str(document.id)]
    job = AIJob(
        id=f"job-{uuid4()}",
        tenant_id=tenant.id,
        user_id=methodologist.id,
        status="running",
        stage="architect",
        params={"documents": [str(document.id)]},
    )
    db_session.add(job)
    await db_session.flush()

    response = await client.get(
        f"/api/v1/documents/{document.id}/usages",
        headers=auth_headers(methodologist),
    )
    catalog_response = await client.get(
        "/api/v1/documents/catalog?include=usages_summary",
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"] == {
        "total": 5,
        "positions": 1,
        "courses": 1,
        "lessons": 1,
        "active_jobs": 1,
    }
    assert {item["type"] for item in body["items"]} == {
        "position_instruction",
        "course_instruction",
        "course_source",
        "lesson_source",
        "active_ai_job",
    }
    assert all(item["blocks_delete"] is True for item in body["items"])
    assert catalog_response.status_code == 200
    assert catalog_response.json()["items"][0]["usages_summary"] == {
        "total": 4,
        "courses": 1,
        "positions": 1,
        "lessons": 1,
        "active_jobs": 1,
    }


async def test_document_delete_returns_structured_409_when_document_is_used(
    client,
    db_session,
    make_tenant,
    make_user,
    make_document,
    auth_headers,
):
    from app.modules.positions.models import Position

    tenant = await make_tenant()
    methodologist = await make_user(tenant, role="methodologist")
    document = await make_document(
        tenant,
        methodologist,
        embedding_status="success",
        index_status="ready",
    )
    db_session.add(
        Position(
            tenant_id=tenant.id,
            name="Cashier",
            department="Retail",
            instruction_document_id=document.id,
        )
    )
    await db_session.flush()

    response = await client.delete(
        f"/api/v1/documents/{document.id}",
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 409
    detail = response.json()["details"]
    assert detail["code"] == "document_in_use"
    assert detail["summary"]["positions"] == 1
    assert detail["items"][0]["type"] == "position_instruction"


async def test_document_delete_returns_423_while_indexing(
    client, make_tenant, make_user, make_document, auth_headers
):
    tenant = await make_tenant()
    methodologist = await make_user(tenant, role="methodologist")
    document = await make_document(tenant, methodologist, index_status="processing")

    response = await client.delete(
        f"/api/v1/documents/{document.id}",
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 423
    assert response.json()["details"]["code"] == "document_processing"


async def test_document_delete_tombstones_and_reuses_durable_job(
    client,
    db_session,
    monkeypatch,
    make_tenant,
    make_user,
    make_document,
    auth_headers,
):
    from sqlalchemy import select

    from app.models.ai_job import AIJob
    from app.models.document import Document
    from app.modules.documents import router as documents_router

    dispatched = []
    monkeypatch.setattr(
        documents_router,
        "_dispatch_document_cleanup",
        lambda job_id, document_id, tenant_id: dispatched.append(
            (job_id, str(document_id), str(tenant_id))
        ),
    )
    tenant = await make_tenant()
    methodologist = await make_user(tenant, role="methodologist")
    document = await make_document(
        tenant,
        methodologist,
        embedding_status="success",
        index_status="ready",
    )

    first = await client.delete(
        f"/api/v1/documents/{document.id}",
        headers=auth_headers(methodologist),
    )
    second = await client.delete(
        f"/api/v1/documents/{document.id}",
        headers=auth_headers(methodologist),
    )

    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]
    assert len(dispatched) == 2
    stored = await db_session.scalar(
        select(Document).where(Document.id == document.id)
    )
    assert stored.lifecycle_status == "deletion_pending"
    assert stored.deletion_job_id == first.json()["job_id"]
    jobs = (
        await db_session.execute(
            select(AIJob).where(
                AIJob.tenant_id == tenant.id,
                AIJob.params["action"].as_string() == "document_cleanup",
            )
        )
    ).scalars().all()
    assert len(jobs) == 1


async def test_document_delete_marks_retryable_failure_when_enqueue_fails(
    client,
    db_session,
    monkeypatch,
    make_tenant,
    make_user,
    make_document,
    auth_headers,
):
    from sqlalchemy import select

    from app.models.ai_job import AIJob
    from app.models.document import Document
    from app.modules.documents import router as documents_router

    monkeypatch.setattr(
        documents_router,
        "_dispatch_document_cleanup",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("broker down")),
    )
    tenant = await make_tenant()
    methodologist = await make_user(tenant, role="methodologist")
    document = await make_document(
        tenant,
        methodologist,
        embedding_status="success",
        index_status="ready",
    )

    response = await client.delete(
        f"/api/v1/documents/{document.id}",
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 503
    stored = await db_session.scalar(select(Document).where(Document.id == document.id))
    job = await db_session.scalar(
        select(AIJob).where(AIJob.id == stored.deletion_job_id)
    )
    assert stored.lifecycle_status == "delete_failed"
    assert stored.deletion_error_code == "cleanup_enqueue_failed"
    assert job.status == "failed"
