from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text


def _unit_vector(index: int, dimensions: int = 4096) -> str:
    values = [0.0] * dimensions
    values[index] = 1.0
    return "[" + ",".join(str(value) for value in values) + "]"


@pytest.mark.asyncio
async def test_mixed_document_topics_are_reported_and_block_generation(
    client,
    db_session,
    auth_headers,
    make_tenant,
    make_user,
    make_document,
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
        embedding_status="success",
    )
    marketing = await make_document(
        tenant,
        methodologist,
        name="brand-playbook.md",
        title="Стандарт рекламы бренда",
        embedding_status="success",
    )
    for document, vector in ((safety, _unit_vector(0)), (marketing, _unit_vector(1))):
        await db_session.execute(
            text(
                "INSERT INTO document_embeddings "
                "(id, tenant_id, doc_id, text, headings, doc_name, embedding) "
                "VALUES (:id, :tenant_id, :doc_id, :text, :headings, :doc_name, CAST(:embedding AS vector))"
            ),
            {
                "id": uuid4().hex,
                "tenant_id": str(tenant.id),
                "doc_id": str(document.id),
                "text": document.title,
                "headings": "[]",
                "doc_name": document.filename,
                "embedding": vector,
            },
        )
    await db_session.flush()

    payload = {"documents": [str(safety.id), str(marketing.id)]}
    headers = auth_headers(methodologist)
    analysis_response = await client.post(
        "/api/v1/ai/document-compatibility",
        json=payload,
        headers=headers,
    )

    assert analysis_response.status_code == 200
    analysis = analysis_response.json()
    assert analysis["status"] == "incompatible"
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
    assert detail["code"] == "mixed_document_topics"
    assert detail["analysis"]["requires_decision"] is True
