from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.models.enrollment import Enrollment
from app.modules.learning_cycles import service as cycle_service
from app.modules.learning_cycles.models import RecurringLearningAssignment, RecurringLearningRule
from app.modules.learning_reminders.store import PostgresLearningReminderStore


async def _course_occurrence(db_session, make_tenant, make_user, make_course, set_current_tenant):
    tenant = await make_tenant(name=f"Reminder tenant {uuid4().hex[:8]}")
    methodologist = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student", email=f"learner-{uuid4().hex[:8]}@example.invalid")
    learner.password_hash = None
    learner.telegram_id = 700000000 + int(uuid4().int % 1000000)
    course = await make_course(tenant, methodologist, status="published", review_status="approved")
    await set_current_tenant(tenant)
    now = datetime.now(UTC)
    rule = RecurringLearningRule(
        tenant_id=tenant.id, course_id=course.id, user_id=learner.id,
        cadence_days=30, due_days=7, reminder_enabled=True,
        reminder_days_before_due=1, status="active", created_by=methodologist.id,
    )
    db_session.add(rule)
    await db_session.flush()
    assignment = RecurringLearningAssignment(
        tenant_id=tenant.id, rule_id=rule.id, user_id=learner.id,
        course_id=course.id, scheduled_for=now, due_at=now + timedelta(hours=1),
        status="assigned",
    )
    db_session.add(assignment)
    await db_session.flush()
    enrollment = Enrollment(
        tenant_id=tenant.id, user_id=learner.id, course_id=course.id,
        recurring_assignment_id=assignment.id, status="enrolled", source="recurring",
    )
    db_session.add(enrollment)
    await db_session.flush()
    assignment.enrollment_id = enrollment.id
    await db_session.flush()
    return tenant, methodologist, learner, rule, assignment


async def _enqueue(db_session, occurrence, monkeypatch):
    monkeypatch.setattr(cycle_service, "get_settings", lambda: SimpleNamespace(LEARNING_REMINDERS_ENABLED=True))
    await cycle_service._queue_reminder(db_session, occurrence[0].id, course_id=occurrence[4].id)


async def _reminder_id(client, auth_headers, occurrence):
    response = await client.get(
        f"/api/v1/learning-cycles/{occurrence[3].id}/reminders",
        headers=auth_headers(occurrence[1]),
    )
    assert response.status_code == 200, response.text
    statuses = response.json()
    assert len(statuses) == 1
    return UUID(statuses[0]["id"])


async def _restore_tenant(set_current_tenant, occurrence):
    await set_current_tenant(occurrence[0])


@pytest.mark.asyncio
async def test_producer_enqueues_valid_occurrence_and_payload_uses_physical_login_data(
    db_session, client, auth_headers, make_tenant, make_user, make_course, set_current_tenant, monkeypatch
):
    occurrence = await _course_occurrence(db_session, make_tenant, make_user, make_course, set_current_tenant)
    await _enqueue(db_session, occurrence, monkeypatch)
    reminder_id = await _reminder_id(client, auth_headers, occurrence)
    store = PostgresLearningReminderStore(db_session)
    await _restore_tenant(set_current_tenant, occurrence)
    event = await store.claim(tenant_id=occurrence[0].id, reminder_id=reminder_id)
    assert event is not None
    await _restore_tenant(set_current_tenant, occurrence)
    payload = await store.payload(event)
    assert payload is not None
    assert payload.has_login_access is True
    assert payload.email == occurrence[2].email


@pytest.mark.asyncio
async def test_tenant_context_rejects_foreign_statuses_without_foreign_rows(
    db_session, client, auth_headers, make_tenant, make_user, make_course, set_current_tenant, monkeypatch
):
    first = await _course_occurrence(db_session, make_tenant, make_user, make_course, set_current_tenant)
    await _enqueue(db_session, first, monkeypatch)
    second = await _course_occurrence(db_session, make_tenant, make_user, make_course, set_current_tenant)
    await _enqueue(db_session, second, monkeypatch)
    await _restore_tenant(set_current_tenant, first)
    with pytest.raises(Exception, match="tenant context mismatch"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("SELECT public.enqueue_learning_reminder(:tenant_id,:occurrence_id,NULL)"),
                {"tenant_id": second[0].id, "occurrence_id": second[4].id},
            )
    await _restore_tenant(set_current_tenant, first)
    own = await client.get(
        f"/api/v1/learning-cycles/{first[3].id}/reminders", headers=auth_headers(first[1])
    )
    assert own.status_code == 200, own.text
    assert len(own.json()) == 1
    foreign = await client.get(
        f"/api/v1/learning-cycles/{second[3].id}/reminders", headers=auth_headers(first[1])
    )
    assert foreign.status_code == 404


@pytest.mark.asyncio
async def test_claim_begin_finalize_success_is_visible_through_status_api(
    db_session, client, auth_headers, make_tenant, make_user, make_course, set_current_tenant, monkeypatch
):
    occurrence = await _course_occurrence(db_session, make_tenant, make_user, make_course, set_current_tenant)
    await _enqueue(db_session, occurrence, monkeypatch)
    reminder_id = await _reminder_id(client, auth_headers, occurrence)
    store = PostgresLearningReminderStore(db_session)
    await _restore_tenant(set_current_tenant, occurrence)
    event = await store.claim(tenant_id=occurrence[0].id, reminder_id=reminder_id)
    assert event is not None
    await _restore_tenant(set_current_tenant, occurrence)
    assert await store.begin_send(event, payload_hash="a" * 64, transport="resend") is True
    await _restore_tenant(set_current_tenant, occurrence)
    assert await store.finalize(event, kind="success", message_id="<opaque-reminder@example.invalid>") is True
    await _restore_tenant(set_current_tenant, occurrence)
    response = await client.get(
        f"/api/v1/learning-cycles/{occurrence[3].id}/reminders", headers=auth_headers(occurrence[1])
    )
    assert response.json()[0]["status"] == "sent"
    assert response.json()[0]["attempt_count"] == 1


@pytest.mark.asyncio
async def test_smtp_second_reservation_is_blocked_without_email_or_network(
    db_session, client, auth_headers, make_tenant, make_user, make_course, set_current_tenant, monkeypatch
):
    occurrence = await _course_occurrence(db_session, make_tenant, make_user, make_course, set_current_tenant)
    await _enqueue(db_session, occurrence, monkeypatch)
    reminder_id = await _reminder_id(client, auth_headers, occurrence)
    store = PostgresLearningReminderStore(db_session)
    await _restore_tenant(set_current_tenant, occurrence)
    event = await store.claim(tenant_id=occurrence[0].id, reminder_id=reminder_id)
    assert event is not None
    await _restore_tenant(set_current_tenant, occurrence)
    assert await store.begin_send(event, payload_hash="b" * 64, transport="smtp") is True
    await _restore_tenant(set_current_tenant, occurrence)
    assert await store.begin_send(event, payload_hash="b" * 64, transport="smtp") is False
    await _restore_tenant(set_current_tenant, occurrence)
    response = await client.get(
        f"/api/v1/learning-cycles/{occurrence[3].id}/reminders", headers=auth_headers(occurrence[1])
    )
    assert response.json()[0]["status"] == "sending"
    assert response.json()[0]["attempt_count"] == 1
