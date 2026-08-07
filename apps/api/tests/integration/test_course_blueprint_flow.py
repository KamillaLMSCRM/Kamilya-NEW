"""Tenant-safe user flow for the finance IS course blueprint."""

import pytest
from sqlalchemy import func, select

from app.modules.courses.blueprint_catalog import FINANCE_IS_BLUEPRINT_ID, get_blueprint
from app.modules.quizzes.models import Question, Quiz


@pytest.mark.asyncio
async def test_methodologist_adapts_finance_blueprint_before_approval(
    client,
    db_session,
    auth_headers,
    make_tenant,
    make_user,
    make_document,
    set_current_tenant,
):
    tenant = await make_tenant(name="Finance Tenant", slug="finance-blueprint")
    methodologist = await make_user(
        tenant,
        role="methodologist",
        email="methodologist@finance-blueprint.example",
    )
    other_tenant = await make_tenant(name="Other Tenant", slug="finance-blueprint-other")
    other_methodologist = await make_user(
        other_tenant,
        role="methodologist",
        email="methodologist@finance-blueprint-other.example",
    )
    foreign_document = await make_document(
        other_tenant,
        other_methodologist,
        name="foreign-policy.pdf",
    )
    await set_current_tenant(tenant)
    headers = auth_headers(methodologist)

    catalog = await client.get(
        "/api/v1/course-blueprints?locale=ru",
        headers=headers,
    )
    assert catalog.status_code == 200, catalog.text
    assert catalog.json()[0]["id"] == FINANCE_IS_BLUEPRINT_ID
    assert catalog.json()[0]["lesson_count"] == 8

    cross_tenant = await client.post(
        f"/api/v1/course-blueprints/{FINANCE_IS_BLUEPRINT_ID}/instantiate",
        headers=headers,
        json={"locale": "ru", "source_document_ids": [str(foreign_document.id)]},
    )
    assert cross_tenant.status_code == 404, cross_tenant.text
    assert "blueprint_source_documents_not_found" in cross_tenant.json()["message"]

    created = await client.post(
        f"/api/v1/course-blueprints/{FINANCE_IS_BLUEPRINT_ID}/instantiate",
        headers=headers,
        json={"locale": "ru"},
    )
    assert created.status_code == 201, created.text
    course_id = created.json()["course_id"]
    assert created.json()["readiness_percent"] == 70
    assert len(created.json()["missing_checklist_items"]) == 8

    blocked_review = await client.post(
        f"/api/v1/courses/{course_id}/review",
        headers=headers,
        json={"review_status": "approved", "comment": "Checked"},
    )
    assert blocked_review.status_code == 409, blocked_review.text
    assert blocked_review.json()["details"]["code"] == "blueprint_adaptation_incomplete"

    blocked_publish = await client.post(
        f"/api/v1/courses/{course_id}/publish",
        headers=headers,
    )
    assert blocked_publish.status_code == 409, blocked_publish.text
    assert blocked_publish.json()["details"]["code"] == "blueprint_adaptation_incomplete"

    blueprint = get_blueprint("ru")
    answers = {item["id"]: f"Tenant rule: {item['id']}" for item in blueprint["checklist"]}
    adapted = await client.put(
        f"/api/v1/courses/{course_id}/blueprint-adaptation",
        headers=headers,
        json={"locale": "ru", "answers": answers},
    )
    assert adapted.status_code == 200, adapted.text
    assert adapted.json()["readiness_percent"] == 100
    assert adapted.json()["missing_checklist_items"] == []

    still_unreviewed = await client.post(
        f"/api/v1/courses/{course_id}/publish",
        headers=headers,
    )
    assert still_unreviewed.status_code == 409, still_unreviewed.text
    assert still_unreviewed.json()["details"]["code"] == "course_review_required"

    structure = await client.get(
        f"/api/v1/courses/{course_id}/structure",
        headers=headers,
    )
    assert structure.status_code == 200, structure.text
    assert len(structure.json()["modules"]) == 1
    lessons = structure.json()["modules"][0]["lessons"]
    assert len(lessons) == 8
    assert sum(
        "Настройка вашей организации" in (lesson["content"] or "")
        for lesson in lessons
    ) == 7

    quiz_count = await db_session.scalar(
        select(func.count(Quiz.id)).where(Quiz.tenant_id == tenant.id)
    )
    question_count = await db_session.scalar(
        select(func.count(Question.id))
        .join(Quiz, Quiz.id == Question.quiz_id)
        .where(Quiz.tenant_id == tenant.id)
    )
    assert quiz_count == 8
    assert question_count == 16

    approved = await client.post(
        f"/api/v1/courses/{course_id}/review",
        headers=headers,
        json={"review_status": "approved", "comment": "Adaptation checked"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["review_status"] == "approved"

    published = await client.post(
        f"/api/v1/courses/{course_id}/publish",
        headers=headers,
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"

    duplicate = await client.post(
        f"/api/v1/course-blueprints/{FINANCE_IS_BLUEPRINT_ID}/instantiate",
        headers=headers,
        json={"locale": "ru", "answers": answers},
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["details"]["existing_course_id"] == course_id
