"""Focused read-contract coverage for learner evidence and the training log."""

from __future__ import annotations

import pytest

from app.modules.training_evidence.service import confirm_step_up, record_event
from app.modules.training_log.schemas import TrainingLogFilter
from app.modules.training_log.service import get_training_log_page

pytestmark = pytest.mark.asyncio


async def _event(db_session, tenant, actor, subject, *, procedure_type, confirmation=True, enrollment_id=None):
    payload = {
        "source": "read-contract-test",
        "procedure": {"title": "Recorded learning procedure"},
        "release_version": 1,
        "content_release_sha256": "a" * 64,
    }
    if confirmation:
        payload["confirmation"] = {
            "statement": "I confirm the recorded learning result.",
            "object_version": "release:1",
        }
    return await record_event(
        db_session,
        tenant_id=tenant.id,
        actor_user_id=actor.id,
        user_id=subject.id,
        enrollment_id=enrollment_id,
        procedure_type=procedure_type,
        payload_snapshot=payload,
    )


async def test_learner_read_is_own_subject_only_and_hides_payload(
    client, db_session, make_tenant, make_user, auth_headers
):
    tenant = await make_tenant(name="Learner read tenant")
    methodologist = await make_user(tenant, role="methodologist", email="read-methodologist@example.test")
    learner = await make_user(tenant, role="student", email="read-learner@example.test")
    other_learner = await make_user(tenant, role="student", email="read-other@example.test")
    own = await _event(db_session, tenant, methodologist, learner, procedure_type="training")
    other = await _event(db_session, tenant, methodologist, other_learner, procedure_type="training")
    await db_session.flush()

    response = await client.get(
        "/api/v1/training-evidence/events/mine",
        headers=auth_headers(learner),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["id"] for item in body] == [str(own.id)]
    assert body[0]["confirmation_status"] == "pending"
    assert body[0]["procedure_title"] == "Recorded learning procedure"
    assert body[0]["confirmation_statement"] == "I confirm the recorded learning result."
    assert body[0]["confirmation_object_version"] == "release:1"
    assert body[0]["release_version"] == 1
    assert body[0]["release_sha256"] == "a" * 64
    assert "payload_snapshot" not in body[0]
    assert "payload_sha256" not in body[0]
    assert "tenant_id" not in body[0]

    own_response = await client.get(
        f"/api/v1/training-evidence/events/mine/{own.id}",
        headers=auth_headers(learner),
    )
    assert own_response.status_code == 200
    assert own_response.json()["id"] == str(own.id)

    foreign_response = await client.get(
        f"/api/v1/training-evidence/events/mine/{other.id}",
        headers=auth_headers(learner),
    )
    assert foreign_response.status_code == 404


async def test_methodologist_keeps_tenant_wide_event_read(
    client, db_session, make_tenant, make_user, auth_headers
):
    tenant = await make_tenant(name="Methodologist read tenant")
    methodologist = await make_user(tenant, role="methodologist", email="wide-methodologist@example.test")
    learner = await make_user(tenant, role="student", email="wide-learner@example.test")
    event = await _event(db_session, tenant, methodologist, learner, procedure_type="knowledge_check")
    await db_session.flush()

    response = await client.get(
        "/api/v1/training-evidence/events",
        headers=auth_headers(methodologist),
    )
    assert response.status_code == 200
    assert any(item["id"] == str(event.id) for item in response.json())


async def test_learner_confirmation_filter_reports_confirmed_event(
    client, db_session, make_tenant, make_user, auth_headers
):
    tenant = await make_tenant(name="Confirmation filter tenant")
    methodologist = await make_user(tenant, role="methodologist", email="filter-methodologist@example.test")
    learner = await make_user(tenant, role="student", email="filter-learner@example.test")
    event = await _event(db_session, tenant, methodologist, learner, procedure_type="knowledge_check")
    await confirm_step_up(
        db_session,
        tenant_id=tenant.id,
        event_id=event.id,
        user_id=learner.id,
        action_text="I confirm the recorded learning result.",
        object_version="release:1",
        reauth_method="email_otp",
        ip_address=None,
        user_agent="read-contract-test",
    )
    await db_session.flush()

    response = await client.get(
        "/api/v1/training-evidence/events/mine?confirmation_status=confirmed",
        headers=auth_headers(learner),
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(event.id)]
    assert response.json()[0]["confirmation_status"] == "confirmed"


async def test_training_log_preserves_training_and_knowledge_check_evidence(
    db_session, make_tenant, make_user, make_course
):
    tenant = await make_tenant(name="Training log evidence tenant")
    methodologist = await make_user(tenant, role="methodologist", email="log-methodologist@example.test")
    learner = await make_user(tenant, role="student", email="log-learner@example.test")
    course = await make_course(tenant, methodologist, title="Evidence log course")

    from app.models.enrollment import Enrollment

    enrollment = Enrollment(
        tenant_id=tenant.id,
        course_id=course.id,
        user_id=learner.id,
        status="enrolled",
        source="manual",
    )
    db_session.add(enrollment)
    await db_session.flush()
    training = await _event(
        db_session,
        tenant,
        methodologist,
        learner,
        procedure_type="training",
        enrollment_id=enrollment.id,
    )
    knowledge_check = await _event(
        db_session,
        tenant,
        methodologist,
        learner,
        procedure_type="knowledge_check",
        enrollment_id=enrollment.id,
    )
    await db_session.flush()

    page = await get_training_log_page(db_session, tenant.id, TrainingLogFilter(), limit=10)
    row = next(item for item in page.items if item.enrollment_id == enrollment.id)
    assert row.content_release_id is None
    assert {item.procedure_type for item in row.evidence_events} == {"training", "knowledge_check"}
    assert {item.event_id for item in row.evidence_events} == {training.id, knowledge_check.id}
    assert row.evidence_state == "forming"
    assert row.evidence_confirmation_status == "pending"
