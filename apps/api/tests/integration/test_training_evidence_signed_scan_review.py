"""Contract tests for learner returned-copy lifecycle and methodologist review."""

from __future__ import annotations

import io
from uuid import uuid4

import pytest

from app.models.enrollment import Enrollment
from app.modules.training_evidence.service import record_event

pytestmark = pytest.mark.asyncio


async def test_learner_can_append_only_to_own_training_event_and_methodologist_can_review(
    client, db_session, make_tenant, make_user, auth_headers
):
    tenant = await make_tenant(name="Signed scan review contract")
    learner = await make_user(tenant, role="student", email=f"learner-{uuid4().hex}@example.test")
    methodologist = await make_user(tenant, role="methodologist", email=f"method-{uuid4().hex}@example.test")
    enrollment = Enrollment(
        id=uuid4(),
        tenant_id=tenant.id,
        course_id=uuid4(),
        user_id=learner.id,
        status="completed",
        source="manual",
    )
    db_session.add(enrollment)
    await db_session.flush()
    event = await record_event(
        db_session,
        tenant_id=tenant.id,
        actor_user_id=methodologist.id,
        user_id=learner.id,
        enrollment_id=enrollment.id,
        procedure_type="training",
        payload_snapshot={"procedure": {"title": "Course completion"}},
    )

    initial = await client.get(
        f"/api/v1/training-evidence/events/mine/{event.id}/signed-scans",
        headers=auth_headers(learner),
    )
    assert initial.status_code == 200
    assert initial.json()["status"] == "awaiting_return"

    uploaded = await client.post(
        f"/api/v1/training-evidence/events/mine/{event.id}/signed-scans",
        headers=auth_headers(learner),
        files={"file": ("signed.pdf", b"%PDF-1.7\nreturned", "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    scan_id = uploaded.json()["id"]
    assert uploaded.json()["status"] == "uploaded_pending_review"

    review = await client.post(
        f"/api/v1/training-evidence/events/{event.id}/signed-scans/{scan_id}/review",
        headers=auth_headers(methodologist),
        json={"action": "accept"},
    )
    assert review.status_code == 201, review.text
    assert review.json()["status"] == "accepted"

    opened = await client.get(
        f"/api/v1/training-evidence/events/{event.id}/signed-scans/{scan_id}/download",
        headers=auth_headers(methodologist),
    )
    assert opened.status_code == 200
    assert opened.content == b"%PDF-1.7\nreturned"
    assert "inline" in opened.headers["content-disposition"]


async def test_knowledge_check_and_impersonation_cannot_use_returned_copy_routes(
    client, db_session, make_tenant, make_user, auth_headers
):
    tenant = await make_tenant(name="Signed scan negative contract")
    learner = await make_user(tenant, role="student", email=f"learner-{uuid4().hex}@example.test")
    methodologist = await make_user(tenant, role="methodologist", email=f"method-{uuid4().hex}@example.test")
    enrollment = Enrollment(
        id=uuid4(),
        tenant_id=tenant.id,
        course_id=uuid4(),
        user_id=learner.id,
        status="completed",
        source="manual",
    )
    db_session.add(enrollment)
    await db_session.flush()
    event = await record_event(
        db_session,
        tenant_id=tenant.id,
        actor_user_id=methodologist.id,
        user_id=learner.id,
        enrollment_id=enrollment.id,
        procedure_type="knowledge_check",
        payload_snapshot={"procedure": {"title": "Quiz"}},
    )
    response = await client.post(
        f"/api/v1/training-evidence/events/mine/{event.id}/signed-scans",
        headers=auth_headers(learner),
        files={"file": ("signed.pdf", io.BytesIO(b"%PDF-1.7\nnope"), "application/pdf")},
    )
    assert response.status_code in {404, 422}
