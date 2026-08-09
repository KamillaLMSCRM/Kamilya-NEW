"""End-to-end candidate assessment flow on PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models.users import User
from app.modules.courses.release_models import ContentRelease
from app.modules.courses.release_service import canonical_json_sha256

pytestmark = pytest.mark.asyncio


async def test_candidate_is_assessed_without_becoming_company_user(
    client,
    db_session,
    make_tenant,
    make_user,
    make_course,
    set_current_tenant,
    auth_headers,
) -> None:
    tenant = await make_tenant(name="Candidate API")
    methodologist = await make_user(tenant, role="methodologist")
    course = await make_course(tenant, methodologist, status="published")
    quiz_id, question_id, right_id, wrong_id = (uuid4() for _ in range(4))
    release_snapshot = {
        "course": {"title": "Pre-employment assessment"},
        "modules": [
            {
                "lessons": [
                    {
                        "quizzes": [
                            {
                                "id": str(quiz_id),
                                "title": "Knowledge check",
                                "pass_score": 80,
                                "review_status": "approved",
                                "questions": [
                                    {
                                        "id": str(question_id),
                                        "text": "Choose the required action",
                                        "type": "single_choice",
                                        "points": 1,
                                        "choices": [
                                            {"id": str(right_id), "text": "Required action", "is_correct": True},
                                            {"id": str(wrong_id), "text": "Wrong action", "is_correct": False},
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                ]
            }
        ],
    }
    await set_current_tenant(tenant)
    release = ContentRelease(
        id=uuid4(),
        tenant_id=tenant.id,
        course_id=course.id,
        version=1,
        snapshot=release_snapshot,
        snapshot_sha256=canonical_json_sha256(release_snapshot),
        published_by=methodologist.id,
    )
    db_session.add(release)
    await db_session.flush()

    headers = auth_headers(methodologist)
    created = await client.post(
        "/api/v1/candidate-assessments",
        headers=headers,
        json={
            "content_release_id": str(release.id),
            "title": "Assessment before hiring",
            "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
            "attempt_limit": 1,
            "retention_days": 30,
        },
    )
    assert created.status_code == 201, created.text
    campaign_id = created.json()["id"]
    activated = await client.patch(
        f"/api/v1/candidate-assessments/{campaign_id}",
        headers=headers,
        json={"status": "active"},
    )
    assert activated.status_code == 200, activated.text

    invitation = await client.post(
        f"/api/v1/candidate-assessments/{campaign_id}/candidates",
        headers=headers,
        json={"first_name": "Имя", "last_name": "Фамилия", "email": None, "phone": None},
    )
    assert invitation.status_code == 201, invitation.text
    issued = invitation.json()
    token = issued["access_url"].rsplit("/", 1)[1]

    exchange = await client.post(
        f"/api/v1/candidate-assessment/{token}/exchange",
        json={"pin": issued["temporary_pin"], "consent": True},
    )
    assert exchange.status_code == 200, exchange.text
    access = exchange.json()
    assert "is_correct" not in str(access["assessment"])

    submitted = await client.post(
        "/api/v1/candidate-assessment/submit",
        headers={"Authorization": f"Bearer {access['access_token']}"},
        json={
            "attempt_id": access["attempt_id"],
            "answers": [
                {"question_id": str(question_id), "selected_choice_ids": [str(right_id)]},
            ],
        },
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json() == {
        "attempt_id": access["attempt_id"],
        "score_percent": 100,
        "passed": True,
    }

    candidates = await client.get(f"/api/v1/candidate-assessments/{campaign_id}/candidates", headers=headers)
    assert candidates.status_code == 200
    assert candidates.json()[0]["status"] == "completed"

    # Candidate isolation is structural: the flow never creates a staff User.
    await set_current_tenant(tenant)
    candidate_staff_rows = await db_session.scalar(
        select(func.count(User.id)).where(User.tenant_id == tenant.id, User.first_name == "Имя")
    )
    assert candidate_staff_rows == 0
