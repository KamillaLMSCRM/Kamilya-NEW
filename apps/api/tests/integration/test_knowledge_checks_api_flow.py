"""Authenticated standalone knowledge-check journey on the integration database."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.modules.courses.models import Course
from app.modules.knowledge_checks.models import KnowledgeCheckAssignment
from app.modules.lessons.models import Lesson

pytestmark = pytest.mark.asyncio
BASE = "/api/v1/knowledge-checks"


def response_json(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def assert_public(payload):
    serialized = json.dumps(payload)
    assert "is_correct" not in serialized
    assert "explanation" not in serialized


async def test_standalone_check_http_journey(
    client, db_session, make_tenant, make_user, set_current_tenant, auth_headers,
) -> None:
    tenant = await make_tenant(name="Standalone knowledge checks")
    author = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student")
    other_learner = await make_user(tenant, role="student")
    admin = await make_user(tenant, role="admin")
    other_tenant = await make_tenant(name="Other knowledge checks tenant")
    foreign_author = await make_user(other_tenant, role="methodologist")
    foreign_learner = await make_user(other_tenant, role="student")
    author_headers = auth_headers(author)
    learner_headers = auth_headers(learner)

    await set_current_tenant(tenant)
    before_courses = await db_session.scalar(select(func.count(Course.id)).where(Course.tenant_id == tenant.id))
    before_lessons = await db_session.scalar(select(func.count(Lesson.id)).where(Lesson.tenant_id == tenant.id))

    check_id, question_id, right_id, wrong_id = (str(uuid4()) for _ in range(4))
    content = {
        "title": "Standalone check", "instructions": "Choose one answer", "pass_score": 100,
        "attempt_limit": 2, "time_limit_minutes": None,
        "questions": [{"id": question_id, "text": "Required action?", "type": "MCQ", "points": 1,
                       "explanation": "Author only", "choices": [
                           {"id": right_id, "text": "Correct action", "is_correct": True},
                           {"id": wrong_id, "text": "Other action", "is_correct": False},
                       ]}],
    }
    created = response_json(await client.post(f"{BASE}/", headers=author_headers, json={"id": check_id, **content}))
    assert created["revision"] == 1 and created["status"] == "draft"
    assert (await client.get(f"{BASE}/{check_id}", headers=auth_headers(foreign_author))).status_code == 404
    assert (await client.get(f"{BASE}/{check_id}", headers=learner_headers)).status_code == 403
    published = response_json(await client.post(f"{BASE}/{check_id}/publish", headers=author_headers,
                                                json={"expected_revision": 1}))
    assert published["status"] == "published"

    mixed = await client.post(f"{BASE}/{check_id}/assign", headers=author_headers,
                              json={"expected_revision": 1, "user_ids": [str(learner.id), str(admin.id)]})
    assert mixed.status_code == 404
    foreign = await client.post(f"{BASE}/{check_id}/assign", headers=author_headers,
                                json={"expected_revision": 1, "user_ids": [str(learner.id), str(foreign_learner.id)]})
    assert foreign.status_code == 404
    await set_current_tenant(tenant)
    assert await db_session.scalar(select(func.count(KnowledgeCheckAssignment.id)).where(
        KnowledgeCheckAssignment.tenant_id == tenant.id, KnowledgeCheckAssignment.check_id == UUID(check_id))) == 0

    assigned = response_json(await client.post(f"{BASE}/{check_id}/assign", headers=author_headers,
                                               json={"expected_revision": 1, "user_ids": [str(learner.id)]}))
    assignment_id = assigned["items"][0]["id"]
    assert assigned["items"][0]["status"] == "assigned"
    assert (await client.get(f"{BASE}/assignments/{assignment_id}", headers=auth_headers(other_learner))).status_code == 404
    assert (await client.get(f"{BASE}/assignments/{assignment_id}", headers=auth_headers(foreign_learner))).status_code == 404
    assert (await client.get(f"{BASE}/my", headers=author_headers)).status_code == 403
    my_items = response_json(await client.get(f"{BASE}/my", headers=learner_headers))["items"]
    assert any(item["id"] == assignment_id for item in my_items)

    started = response_json(await client.post(f"{BASE}/assignments/{assignment_id}/start", headers=learner_headers))
    attempt_id = started["id"]
    assert started["number"] == 1 and started["status"] == "started"
    assert_public(started)
    assert response_json(await client.post(f"{BASE}/assignments/{assignment_id}/start", headers=learner_headers))["id"] == attempt_id
    assert (await client.get(f"{BASE}/attempts/{attempt_id}", headers=auth_headers(other_learner))).status_code == 404
    assert (await client.get(f"{BASE}/attempts/{attempt_id}", headers=auth_headers(foreign_learner))).status_code == 404
    wrong = {"answers": [{"question_id": question_id, "selected_choice_ids": [wrong_id]}]}
    saved = response_json(await client.put(f"{BASE}/attempts/{attempt_id}/answers", headers=learner_headers, json=wrong))
    assert saved["answers"] == wrong["answers"]
    reloaded = response_json(await client.get(f"{BASE}/attempts/{attempt_id}", headers=learner_headers))
    assert reloaded["answers"] == wrong["answers"]
    assert_public(reloaded)
    failed = response_json(await client.post(f"{BASE}/attempts/{attempt_id}/submit", headers=learner_headers, json=wrong))
    assert failed["score_percent"] == 0 and failed["passed"] is False
    assert_public(failed)

    second = response_json(await client.post(f"{BASE}/assignments/{assignment_id}/start", headers=learner_headers))
    assert second["id"] != attempt_id and second["number"] == 2
    correct = {"answers": [{"question_id": question_id, "selected_choice_ids": [right_id]}]}
    passed = response_json(await client.post(f"{BASE}/attempts/{second['id']}/submit", headers=learner_headers, json=correct))
    assert passed["score_percent"] == 100 and passed["passed"] is True
    assert_public(passed)
    assert (await client.post(f"{BASE}/assignments/{assignment_id}/start", headers=learner_headers)).status_code == 409
    history = response_json(await client.get(f"{BASE}/assignments/{assignment_id}", headers=learner_headers))
    assert [attempt["passed"] for attempt in history["attempts"]] == [False, True]
    assert_public(history)
    results = response_json(await client.get(f"{BASE}/{check_id}/results", headers=author_headers))
    assert len(results["items"]) == 1
    assert [attempt["passed"] for attempt in results["items"][0]["attempts"]] == [False, True]

    revised_content = {**content, "title": "Standalone check revision two"}
    edited = response_json(await client.put(f"{BASE}/{check_id}", headers=author_headers,
                                            json={"expected_revision": 1, **revised_content}))
    assert edited["revision"] == 2 and edited["status"] == "draft"
    response_json(await client.post(f"{BASE}/{check_id}/publish", headers=author_headers,
                                    json={"expected_revision": 2}))
    revised = response_json(await client.post(f"{BASE}/{check_id}/assign", headers=author_headers,
                                              json={"expected_revision": 2, "user_ids": [str(learner.id)]}))
    assert revised["items"][0]["id"] != assignment_id
    assert revised["items"][0]["revision"] == 2
    old = response_json(await client.get(f"{BASE}/assignments/{assignment_id}", headers=learner_headers))
    assert old["title"] == content["title"] and [a["passed"] for a in old["attempts"]] == [False, True]
    assert response_json(await client.get(f"{BASE}/attempts/{attempt_id}", headers=learner_headers))["snapshot"]["title"] == content["title"]
    all_results = response_json(await client.get(f"{BASE}/{check_id}/results", headers=author_headers))["items"]
    assert {item["revision"] for item in all_results} == {1, 2}

    await set_current_tenant(tenant)
    assert await db_session.scalar(select(func.count(Course.id)).where(Course.tenant_id == tenant.id)) == before_courses
    assert await db_session.scalar(select(func.count(Lesson.id)).where(Lesson.tenant_id == tenant.id)) == before_lessons
