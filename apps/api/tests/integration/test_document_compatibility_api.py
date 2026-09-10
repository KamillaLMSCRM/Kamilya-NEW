from __future__ import annotations

from uuid import uuid4

import pytest
from direct_source_fixtures import seed_direct_source_documents


@pytest.mark.asyncio
async def test_multiple_direct_sources_are_unverified_and_require_goal(
    client,
    db_session,
    auth_headers,
    make_tenant,
    make_user,
    make_document,
    monkeypatch,
):
    tenant = await make_tenant(name="Source Governance", slug=f"sources-{uuid4().hex[:8]}")
    methodologist = await make_user(
        tenant,
        role="methodologist",
        email=f"methodologist-{uuid4().hex[:8]}@example.test",
    )
    safety = await make_document(
        tenant,
        methodologist,
        name="fire-safety.md",
        title="Пожарная безопасность",
        embedding_status="pending",
        index_status="processing",
    )
    marketing = await make_document(
        tenant,
        methodologist,
        name="brand-playbook.md",
        title="Стандарт рекламы бренда",
        embedding_status="pending",
        index_status="processing",
    )
    await seed_direct_source_documents(
        db_session,
        monkeypatch,
        [safety, marketing],
        texts={
            safety.id: "# Пожарная безопасность\n\nПравила безопасной эвакуации сотрудников.",
            marketing.id: "# Стандарт рекламы бренда\n\nПравила подготовки рекламных материалов.",
        },
    )

    payload = {"documents": [str(safety.id), str(marketing.id)]}
    headers = auth_headers(methodologist)
    analysis_response = await client.post(
        "/api/v1/ai/document-compatibility",
        json=payload,
        headers=headers,
    )

    assert analysis_response.status_code == 200
    analysis = analysis_response.json()
    assert analysis["status"] == "unverified"
    assert analysis["analysis_mode"] == "direct_source"
    assert analysis["score"] is None
    assert analysis["requires_decision"] is True
    assert len(analysis["clusters"]) == 2

    generation_response = await client.post(
        "/api/v1/ai/generate-course",
        json={**payload, "target_audience": "Сотрудники компании"},
        headers=headers,
    )

    assert generation_response.status_code == 409
    response_body = generation_response.json()
    assert response_body["error"] == "conflict"
    detail = response_body["details"]
    assert detail["code"] == "source_combination_goal_required"
    assert detail["analysis"]["analysis_mode"] == "direct_source"
    assert detail["analysis"]["score"] is None
    assert detail["analysis"]["requires_decision"] is True


@pytest.mark.asyncio
async def test_document_pending_deletion_cannot_enter_new_generation(
    client,
    auth_headers,
    make_tenant,
    make_user,
    make_document,
):
    tenant = await make_tenant()
    methodologist = await make_user(tenant, role="methodologist")
    document = await make_document(
        tenant,
        methodologist,
        embedding_status="success",
        index_status="ready",
        lifecycle_status="deletion_pending",
    )

    response = await client.post(
        "/api/v1/ai/document-compatibility",
        json={"documents": [str(document.id)]},
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 404
    assert "documents_not_found" in response.text


@pytest.mark.asyncio
async def test_document_compatibility_uses_the_same_five_source_limit(
    client,
    auth_headers,
    make_tenant,
    make_user,
):
    tenant = await make_tenant()
    methodologist = await make_user(tenant, role="methodologist")

    response = await client.post(
        "/api/v1/ai/document-compatibility",
        json={"documents": [str(uuid4()) for _ in range(6)]},
        headers=auth_headers(methodologist),
    )

    assert response.status_code == 422
    body = response.json()
    assert body["details"]["code"] == "too_many_documents"
    assert body["details"]["limit"] == 5
