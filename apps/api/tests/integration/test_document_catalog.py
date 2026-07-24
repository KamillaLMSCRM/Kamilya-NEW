"""Wave 2.1 source catalog API contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

INTERNAL_FIELDS = {"tenant_id", "uploaded_by", "s3_key"}


@pytest.mark.parametrize("role", ["admin", "org_admin", "student", "superadmin"])
@pytest.mark.parametrize("operation", ["list", "get", "download", "delete"])
async def test_documents_endpoints_deny_non_methodologist_roles(
    client, make_tenant, make_user, make_document, auth_headers, role, operation
):
    tenant = await make_tenant()
    owner = await make_user(tenant, role="methodologist")
    document = await make_document(tenant, owner)
    caller = await make_user(tenant, role=role)
    method, path = {
        "list": ("GET", "/api/v1/documents"),
        "get": ("GET", f"/api/v1/documents/{document.id}"),
        "download": ("GET", f"/api/v1/documents/{document.id}/download"),
        "delete": ("DELETE", f"/api/v1/documents/{document.id}"),
    }[operation]

    response = await client.request(method, path, headers=auth_headers(caller))

    assert response.status_code == 403


async def test_documents_catalog_denies_superadmin_without_tenant_context(client, make_superadmin, auth_headers):
    superadmin = await make_superadmin()

    response = await client.get(
        "/api/v1/documents",
        headers=auth_headers(superadmin),
    )

    assert response.status_code == 403


@pytest.mark.parametrize("operation", ["list", "get", "download", "delete"])
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
    document = await make_document(tenant, user)
    method, path = {
        "list": ("GET", "/api/v1/documents"),
        "get": ("GET", f"/api/v1/documents/{document.id}"),
        "download": ("GET", f"/api/v1/documents/{document.id}/download"),
        "delete": ("DELETE", f"/api/v1/documents/{document.id}"),
    }[operation]

    response = await client.request(method, path, headers=auth_headers(user))

    assert response.status_code in {200, 204}


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

    response = await client.get("/api/v1/documents", headers=auth_headers(user))

    assert response.status_code == 200
    body = response.json()
    assert body["page"] == {"next_cursor": None, "has_more": False, "limit": 25}
    assert [item["id"] for item in body["items"]] == [str(document.id)]
    assert INTERNAL_FIELDS.isdisjoint(body["items"][0])


@pytest.mark.parametrize("path_suffix", ["", "/download"])
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
        "/api/v1/documents?limit=2&sort=created_desc",
        headers=auth_headers(user),
    )
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["page"]["has_more"] is True
    assert first_body["page"]["next_cursor"]

    second = await client.get(
        "/api/v1/documents",
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
        "/api/v1/documents",
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
        "/api/v1/documents",
        headers=auth_headers(methodologist),
    )
    recovery_response = await client.get(
        "/api/v1/documents?lifecycle_status=delete_failed",
        headers=auth_headers(methodologist),
    )

    assert [item["id"] for item in default_response.json()["items"]] == [str(active.id)]
    assert [item["id"] for item in recovery_response.json()["items"]] == [str(failed.id)]


async def test_catalog_rejects_tampered_cursor(client, make_tenant, make_user, auth_headers):
    tenant = await make_tenant()
    user = await make_user(tenant, role="methodologist")

    response = await client.get(
        "/api/v1/documents?cursor=not-a-signed-cursor",
        headers=auth_headers(user),
    )

    assert response.status_code == 422
