"""Security contract for the no-email assignment access flow."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.assignment_access import AssignmentAccessCredential
from app.models.enrollment import Enrollment


def test_0096_enforces_ownership_and_refuses_destructive_downgrade() -> None:
    from pathlib import Path

    source = Path("alembic/versions/0096_assignment_access_credentials.py").read_text(encoding="utf-8")
    assert "validate_assignment_access_ownership" in source
    assert "e.tenant_id = NEW.tenant_id" in source
    assert "e.user_id = NEW.user_id" in source
    assert "ur.role = 'student'" in source
    assert "0096 downgrade refused" in source


def test_0106_policy_migration_enforces_tenant_ownership_and_refuses_data_loss() -> None:
    from pathlib import Path

    source = Path("alembic/versions/0106_enrollment_access_policies.py").read_text(encoding="utf-8")
    assert "validate_enrollment_access_policy_ownership" in source
    assert "e.tenant_id = NEW.tenant_id" in source
    assert "e.user_id = NEW.user_id" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE enrollment_access_policies TO lms_app" in source
    assert "0106 downgrade refused" in source


def test_0108_separates_link_expiry_from_issued_assignment_sessions() -> None:
    from pathlib import Path

    source = Path("alembic/versions/0108_assignment_access_first_exchange_marker.py").read_text(encoding="utf-8")
    assert "first_exchanged_at" in source
    assert "0108 downgrade refused" in source


def test_link_expiry_blocks_only_a_fresh_pin_exchange() -> None:
    from app.modules.enrollments.access_service import can_exchange_assignment_link

    now = datetime.now(UTC)
    credential = AssignmentAccessCredential(expires_at=now - timedelta(seconds=1))
    # A marker tells authentication that a bearer session was issued, but does
    # not permit another public PIN exchange after the link deadline.
    credential.first_exchanged_at = now - timedelta(minutes=1)
    assert not can_exchange_assignment_link(credential, now=now)


def test_first_exchange_marks_completion_start_without_a_duration() -> None:
    from app.models.enrollment_access_policy import EnrollmentAccessPolicy
    from app.modules.enrollments.access_service import record_assignment_exchange_start

    now = datetime.now(UTC)
    policy = EnrollmentAccessPolicy(
        tenant_id=uuid4(),
        enrollment_id=uuid4(),
        user_id=uuid4(),
        delivery_mode="personal_link",
        completion_window_minutes=None,
    )
    credential = AssignmentAccessCredential(expires_at=now + timedelta(minutes=1))

    record_assignment_exchange_start(policy, credential, now=now)

    assert policy.completion_window_started_at == now
    assert policy.completion_window_expires_at is None
    assert credential.first_exchanged_at == now


def test_unstarted_policy_reports_elapsed_link_as_expired() -> None:
    from app.models.enrollment_access_policy import EnrollmentAccessPolicy
    from app.modules.enrollments.access_service import access_policy_payload

    policy = EnrollmentAccessPolicy(
        tenant_id=uuid4(),
        enrollment_id=uuid4(),
        user_id=uuid4(),
        delivery_mode="personal_link",
        link_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert access_policy_payload(policy)["state"] == "expired"


async def _issue(client, enrollment_id, headers):
    return await client.post(
        f"/api/v1/courses/enrollments/{enrollment_id}/access-without-email",
        headers=headers,
    )


async def _issue_link(client, enrollment_id, headers, *, completion_window_minutes=None, due_at=None):
    payload = {"delivery_mode": "personal_link"}
    if completion_window_minutes is not None:
        payload["completion_window_minutes"] = completion_window_minutes
    if due_at is not None:
        payload["due_at"] = due_at
    return await client.post(
        f"/api/v1/courses/enrollments/{enrollment_id}/access-link",
        json=payload,
        headers=headers,
    )


async def _enrollment(client, course, learner, headers):
    response = await client.post(
        f"/api/v1/courses/{course.id}/enrollments",
        json={"user_ids": [str(learner.id)]},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()[0]["id"]


@pytest.mark.asyncio
async def test_reissue_revokes_history_and_exchange_is_learner_only(
    client, db_session, make_tenant, make_user, make_course, auth_headers
):
    tenant = await make_tenant(name="No email")
    manager = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student", email=None)
    # The shared factory intentionally supplies a generated email for a falsey
    # value. Clear it explicitly so this test exercises the no-email contract.
    learner.email = None
    await db_session.flush()
    course = await make_course(tenant, manager, status="published")
    enrollment_id = await _enrollment(client, course, learner, auth_headers(manager))

    first = await _issue(client, enrollment_id, auth_headers(manager))
    second = await _issue(client, enrollment_id, auth_headers(manager))
    assert first.status_code == second.status_code == 200
    rows = (
        await db_session.scalars(
            select(AssignmentAccessCredential).where(AssignmentAccessCredential.enrollment_id == enrollment_id)
        )
    ).all()
    assert len(rows) == 2
    assert sum(item.revoked_at is None for item in rows) == 1
    assert rows[0].token_hash not in first.text and rows[0].pin_hash not in first.text

    old_token = first.json()["access_url"].rsplit("/", 1)[1]
    denied = await client.post(
        f"/api/v1/assignment-access/{old_token}/exchange", json={"pin": first.json()["temporary_pin"]}
    )
    assert denied.status_code == 404
    token = second.json()["access_url"].rsplit("/", 1)[1]
    accepted = await client.post(
        f"/api/v1/assignment-access/{token}/exchange", json={"pin": second.json()["temporary_pin"]}
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["user"]["user_id"] == str(learner.id)
    assert accepted.json()["user"]["role"] == "student"

    bearer = {"Authorization": f"Bearer {accepted.json()['access_token']}"}
    assert (await client.get("/api/v1/users/me", headers=bearer)).status_code == 200

    # Once the learner has exchanged the PIN, reissue must not reset the
    # completion window or revoke the live bearer as a side effect.  The
    # methodologist must use the explicit audited revoke/extend operations.
    third = await _issue(client, enrollment_id, auth_headers(manager))
    assert third.status_code == 409
    assert third.json()["details"]["code"] == "assignment_window_already_started"
    assert (await client.get("/api/v1/users/me", headers=bearer)).status_code == 200

    revoked = await client.post(
        f"/api/v1/courses/enrollments/{enrollment_id}/access-policy/revoke",
        json={"reason": "manager ended the remote session"},
        headers=auth_headers(manager),
    )
    assert revoked.status_code == 200, revoked.text
    revoked_session = await client.get("/api/v1/users/me", headers=bearer)
    assert revoked_session.status_code == 401


@pytest.mark.asyncio
async def test_wrong_pin_lockout_after_five_attempts(
    client, db_session, make_tenant, make_user, make_course, auth_headers
):
    tenant = await make_tenant(name="Lockout")
    manager = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student", email=None)
    learner.email = None
    await db_session.flush()
    course = await make_course(tenant, manager, status="published")
    enrollment_id = await _enrollment(client, course, learner, auth_headers(manager))
    issued = await _issue(client, enrollment_id, auth_headers(manager))
    token = issued.json()["access_url"].rsplit("/", 1)[1]

    # The application creates one DB session per real HTTP request.  This
    # integration fixture intentionally shares one transactional session, so
    # requests are issued sequentially; the service's SELECT ... FOR UPDATE
    # is asserted separately as the concurrent-request serialization guard.
    attempts = [
        await client.post(f"/api/v1/assignment-access/{token}/exchange", json={"pin": "000000"}) for _ in range(5)
    ]
    assert all(response.status_code == 401 for response in attempts)
    locked = await client.post(
        f"/api/v1/assignment-access/{token}/exchange", json={"pin": issued.json()["temporary_pin"]}
    )
    assert locked.status_code == 401


def test_pin_exchange_serializes_concurrent_updates() -> None:
    from pathlib import Path

    source = Path("app/modules/enrollments/access_service.py").read_text(encoding="utf-8")
    assert ".with_for_update()" in source


def test_completed_assignment_bearer_can_read_its_result_artifacts() -> None:
    """Completion must not log the remote learner out before PDF/certificate download."""
    from pathlib import Path

    source = Path("app/core/auth.py").read_text(encoding="utf-8")
    assert 'Enrollment.status.in_(("enrolled", "in_progress", "completed"))' in source


@pytest.mark.asyncio
async def test_window_guard_filters_by_exact_enrollment_bound_to_assignment_token() -> None:
    """A second enrollment for the same learner/course cannot select its policy."""
    from app.models.enrollment import Enrollment
    from app.modules.enrollments.access_service import require_active_enrollment_window

    tenant_id, user_id, course_id, bound_enrollment_id = uuid4(), uuid4(), uuid4(), uuid4()
    enrollment = Enrollment(
        id=bound_enrollment_id,
        tenant_id=tenant_id,
        user_id=user_id,
        course_id=course_id,
        status="enrolled",
        source="manual",
    )

    class CapturingDb:
        def __init__(self):
            self.statements = []

        async def scalar(self, statement):
            self.statements.append(statement)
            return enrollment if len(self.statements) == 1 else None

    db = CapturingDb()
    resolved = await require_active_enrollment_window(
        db,
        user_id=user_id,
        tenant_id=tenant_id,
        course_id=course_id,
        enrollment_id=bound_enrollment_id,
    )
    assert resolved is enrollment
    params = db.statements[0].compile().params
    assert bound_enrollment_id in params.values()


@pytest.mark.asyncio
async def test_completed_assignment_enrollment_blocks_learning_mutations() -> None:
    from app.modules.enrollments.access_service import AssignmentWindowExpiredError, require_active_enrollment_window

    class CompletedDb:
        async def scalar(self, _statement):
            return None

    with pytest.raises(AssignmentWindowExpiredError) as exc_info:
        await require_active_enrollment_window(
            CompletedDb(),
            user_id=uuid4(),
            tenant_id=uuid4(),
            course_id=uuid4(),
            enrollment_id=uuid4(),
        )
    assert exc_info.value.code == "assignment_enrollment_not_active"


@pytest.mark.asyncio
async def test_completed_assignment_enrollment_keeps_exact_read_access() -> None:
    from app.models.enrollment import Enrollment
    from app.modules.enrollments.access_service import require_assignment_enrollment_read_access

    tenant_id, user_id, course_id, enrollment_id = uuid4(), uuid4(), uuid4(), uuid4()
    enrollment = Enrollment(
        id=enrollment_id,
        tenant_id=tenant_id,
        user_id=user_id,
        course_id=course_id,
        status="completed",
        source="manual",
    )

    class CompletedDb:
        def __init__(self):
            self.calls = 0

        async def scalar(self, _statement):
            self.calls += 1
            return enrollment if self.calls == 1 else None

    resolved = await require_assignment_enrollment_read_access(
        CompletedDb(),
        user_id=user_id,
        tenant_id=tenant_id,
        course_id=course_id,
        enrollment_id=enrollment_id,
    )
    assert resolved is enrollment


def test_personal_link_completion_certificate_is_bound_to_explicit_enrollment() -> None:
    from pathlib import Path

    service = Path("app/modules/certificates/service.py").read_text(encoding="utf-8")
    router = Path("app/modules/certificates/router.py").read_text(encoding="utf-8")
    assert "enrollment_id is not None or enrollment.recurring_assignment_id" in service
    assert 'getattr(user, "assignment_access_enrollment_id", None) is not None' in router
    assert "Certificate is issued by course completion" in router


def test_assignment_bound_secondary_learner_surfaces_are_scoped() -> None:
    from pathlib import Path

    surveys = Path("app/modules/surveys/router.py").read_text(encoding="utf-8")
    assistant = Path("app/modules/learner_assistant/router.py").read_text(encoding="utf-8")
    scorm = Path("app/modules/scorm/router.py").read_text(encoding="utf-8")
    assert surveys.count("Enrollment.id == assignment_enrollment_id") >= 2
    assert "return await require_course_access(db, course_id, user)" in assistant
    assert 'payload.get("assignment_access_enrollment_id")' in scorm
    assert "attempt.enrollment_id != enrollment_id" in scorm


def test_assignment_result_surfaces_are_scoped_to_exact_enrollment() -> None:
    from pathlib import Path

    certificates = Path("app/modules/certificates/router.py").read_text(encoding="utf-8")
    evidence = Path("app/modules/training_evidence/router.py").read_text(encoding="utf-8")
    courses = Path("app/modules/courses/router.py").read_text(encoding="utf-8")
    assert "cert.enrollment_id == assignment_enrollment_id" in certificates
    assert "event.enrollment_id != assignment_enrollment_id" in evidence
    assert "Enrollment.id == assignment_enrollment_id" in courses


@pytest.mark.asyncio
async def test_expired_assignment_window_raises_structured_expiry_code() -> None:
    from app.models.enrollment import Enrollment
    from app.models.enrollment_access_policy import EnrollmentAccessPolicy
    from app.modules.enrollments.access_service import AssignmentWindowExpiredError, require_active_enrollment_window

    tenant_id, user_id, course_id, enrollment_id = uuid4(), uuid4(), uuid4(), uuid4()
    enrollment = Enrollment(
        id=enrollment_id,
        tenant_id=tenant_id,
        user_id=user_id,
        course_id=course_id,
        status="enrolled",
        source="manual",
    )
    policy = EnrollmentAccessPolicy(
        tenant_id=tenant_id,
        enrollment_id=enrollment_id,
        user_id=user_id,
        delivery_mode="personal_link",
        completion_window_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    class FakeDb:
        def __init__(self):
            self.values = iter((enrollment, policy))

        async def scalar(self, _statement):
            return next(self.values)

    with pytest.raises(AssignmentWindowExpiredError) as exc_info:
        await require_active_enrollment_window(
            FakeDb(),
            user_id=user_id,
            tenant_id=tenant_id,
            course_id=course_id,
            enrollment_id=enrollment_id,
        )
    assert exc_info.value.code == "assignment_completion_window_expired"


@pytest.mark.asyncio
async def test_started_bearer_can_continue_after_link_expiry() -> None:
    """The exact enrollment guard must ignore the elapsed initial-link deadline."""
    from app.models.enrollment import Enrollment
    from app.models.enrollment_access_policy import EnrollmentAccessPolicy
    from app.modules.enrollments.access_service import access_policy_payload, require_active_enrollment_window

    tenant_id, user_id, course_id, enrollment_id = uuid4(), uuid4(), uuid4(), uuid4()
    enrollment = Enrollment(
        id=enrollment_id,
        tenant_id=tenant_id,
        user_id=user_id,
        course_id=course_id,
        status="in_progress",
        source="manual",
    )
    policy = EnrollmentAccessPolicy(
        tenant_id=tenant_id,
        enrollment_id=enrollment_id,
        user_id=user_id,
        delivery_mode="personal_link",
        link_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        completion_window_started_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    class FakeDb:
        def __init__(self):
            self.values = iter((enrollment, policy))

        async def scalar(self, _statement):
            return next(self.values)

    resolved = await require_active_enrollment_window(
        FakeDb(),
        user_id=user_id,
        tenant_id=tenant_id,
        course_id=course_id,
        enrollment_id=enrollment_id,
    )
    assert resolved is enrollment
    assert access_policy_payload(policy)["state"] == "available"


@pytest.mark.asyncio
async def test_due_date_still_blocks_a_started_assignment_session() -> None:
    from app.models.enrollment import Enrollment
    from app.models.enrollment_access_policy import EnrollmentAccessPolicy
    from app.modules.enrollments.access_service import AssignmentWindowExpiredError, require_active_enrollment_window

    tenant_id, user_id, course_id, enrollment_id = uuid4(), uuid4(), uuid4(), uuid4()
    enrollment = Enrollment(
        id=enrollment_id,
        tenant_id=tenant_id,
        user_id=user_id,
        course_id=course_id,
        status="in_progress",
        source="manual",
    )
    policy = EnrollmentAccessPolicy(
        tenant_id=tenant_id,
        enrollment_id=enrollment_id,
        user_id=user_id,
        delivery_mode="personal_link",
        link_expires_at=datetime.now(UTC) - timedelta(days=1),
        completion_window_started_at=datetime.now(UTC) - timedelta(minutes=2),
        due_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    class FakeDb:
        def __init__(self):
            self.values = iter((enrollment, policy))

        async def scalar(self, _statement):
            return next(self.values)

    with pytest.raises(AssignmentWindowExpiredError) as exc_info:
        await require_active_enrollment_window(
            FakeDb(),
            user_id=user_id,
            tenant_id=tenant_id,
            course_id=course_id,
            enrollment_id=enrollment_id,
        )
    assert exc_info.value.code == "assignment_due_at_expired"


@pytest.mark.asyncio
async def test_issue_is_not_available_for_email_or_cross_tenant(
    client, make_tenant, make_user, make_course, auth_headers, monkeypatch
):
    from app.modules.enrollments.notification_tasks import deliver_assignment_notification_task

    monkeypatch.setattr(deliver_assignment_notification_task, "apply_async", lambda *args, **kwargs: None)
    owner = await make_tenant(name="Owner")
    outsider = await make_tenant(name="Outsider")
    manager = await make_user(owner, role="methodologist")
    other_manager = await make_user(outsider, role="methodologist")
    email_learner = await make_user(owner, role="student", email="learner@example.test")
    course = await make_course(owner, manager, status="published")
    enrollment_id = await _enrollment(client, course, email_learner, auth_headers(manager))

    # The compatibility endpoint remains no-email-only, but the explicit
    # personal-link delivery surface deliberately supports active learners who
    # do have an email address.
    assert (await _issue(client, enrollment_id, auth_headers(manager))).status_code == 404
    issued = await _issue_link(client, enrollment_id, auth_headers(manager), completion_window_minutes=30)
    assert issued.status_code == 200, issued.text
    assert issued.json()["completion_window_minutes"] == 30
    assert (await _issue_link(client, enrollment_id, auth_headers(other_manager))).status_code == 404


@pytest.mark.asyncio
async def test_personal_link_starts_window_once_and_returns_assigned_course(
    client, db_session, make_tenant, make_user, make_course, auth_headers
):
    tenant = await make_tenant(name="Timed access")
    manager = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student", email="learner@example.test")
    course = await make_course(tenant, manager, status="published")
    enrollment_id = await _enrollment(client, course, learner, auth_headers(manager))

    issued = await _issue_link(client, enrollment_id, auth_headers(manager), completion_window_minutes=30)
    assert issued.status_code == 200, issued.text
    token = issued.json()["access_url"].rsplit("/", 1)[1]
    first = await client.post(
        f"/api/v1/assignment-access/{token}/exchange", json={"pin": issued.json()["temporary_pin"]}
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["assigned_course_id"] == str(course.id)
    assert body["enrollment_id"] == enrollment_id
    assert body["access_policy"]["completion_window_started_at"] is not None
    assert body["access_policy"]["completion_window_expires_at"] is not None

    window = await client.get(
        f"/api/v1/courses/{course.id}/access-window",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert window.status_code == 200, window.text
    window_body = window.json()
    assert window_body["access_policy"]["enrollment_id"] == enrollment_id
    assert (
        window_body["access_policy"]["completion_window_expires_at"]
        == body["access_policy"]["completion_window_expires_at"]
    )
    assert "temporary_pin" not in window_body

    second = await client.post(
        f"/api/v1/assignment-access/{token}/exchange", json={"pin": issued.json()["temporary_pin"]}
    )
    assert second.status_code == 200, second.text
    assert (
        second.json()["access_policy"]["completion_window_started_at"]
        == body["access_policy"]["completion_window_started_at"]
    )


@pytest.mark.asyncio
async def test_switching_personal_link_to_email_revokes_its_existing_bearer(
    client, make_tenant, make_user, make_course, auth_headers
):
    tenant = await make_tenant(name="Policy delivery switch")
    manager = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student", email="learner@example.test")
    course = await make_course(tenant, manager, status="published")
    enrollment_id = await _enrollment(client, course, learner, auth_headers(manager))
    issued = await _issue_link(client, enrollment_id, auth_headers(manager))
    assert issued.status_code == 200, issued.text
    token = issued.json()["access_url"].rsplit("/", 1)[1]
    exchanged = await client.post(
        f"/api/v1/assignment-access/{token}/exchange", json={"pin": issued.json()["temporary_pin"]}
    )
    assert exchanged.status_code == 200, exchanged.text
    bearer = {"Authorization": f"Bearer {exchanged.json()['access_token']}"}
    assert (await client.get("/api/v1/users/me", headers=bearer)).status_code == 200

    changed = await client.put(
        f"/api/v1/courses/enrollments/{enrollment_id}/access-policy",
        json={"delivery_mode": "email"},
        headers=auth_headers(manager),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["delivery_mode"] == "email"
    assert (await client.get("/api/v1/users/me", headers=bearer)).status_code == 401


@pytest.mark.asyncio
async def test_atomic_personal_link_enrollment_reveals_credential_without_email_outbox(
    client, db_session, make_tenant, make_user, make_course, auth_headers
):
    tenant = await make_tenant(name="Atomic personal link")
    manager = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student", email="learner@example.test")
    course = await make_course(tenant, manager, status="published")

    response = await client.post(
        f"/api/v1/courses/{course.id}/personal-link-enrollment",
        json={"user_id": str(learner.id), "completion_window_minutes": 30},
        headers=auth_headers(manager),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user_id"] == str(learner.id)
    assert body["enrollment_id"]
    assert body["temporary_pin"]

    enrollment = await db_session.get(Enrollment, body["enrollment_id"])
    assert enrollment is not None
    assert getattr(enrollment, "notification_outbox_id", None) is None


@pytest.mark.asyncio
async def test_put_started_personal_link_policy_requires_extend_or_reissue(
    client, make_tenant, make_user, make_course, auth_headers
):
    tenant = await make_tenant(name="Started policy immutable")
    manager = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student", email="learner@example.test")
    course = await make_course(tenant, manager, status="published")
    enrollment_id = await _enrollment(client, course, learner, auth_headers(manager))
    issued = await _issue_link(client, enrollment_id, auth_headers(manager), completion_window_minutes=30)
    token = issued.json()["access_url"].rsplit("/", 1)[1]
    assert (
        await client.post(f"/api/v1/assignment-access/{token}/exchange", json={"pin": issued.json()["temporary_pin"]})
    ).status_code == 200

    rejected = await client.put(
        f"/api/v1/courses/enrollments/{enrollment_id}/access-policy",
        json={"delivery_mode": "personal_link", "completion_window_minutes": 60},
        headers=auth_headers(manager),
    )
    assert rejected.status_code == 409


@pytest.mark.asyncio
async def test_reissue_cannot_reset_an_already_started_completion_window(
    client, make_tenant, make_user, make_course, auth_headers, monkeypatch
):
    from app.modules.enrollments.notification_tasks import deliver_assignment_notification_task

    monkeypatch.setattr(deliver_assignment_notification_task, "apply_async", lambda *args, **kwargs: None)
    tenant = await make_tenant(name="Started reissue guard")
    manager = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student", email="learner@example.test")
    course = await make_course(tenant, manager, status="published")
    enrollment_id = await _enrollment(client, course, learner, auth_headers(manager))
    issued = await _issue_link(client, enrollment_id, auth_headers(manager), completion_window_minutes=30)
    token = issued.json()["access_url"].rsplit("/", 1)[1]
    exchanged = await client.post(
        f"/api/v1/assignment-access/{token}/exchange", json={"pin": issued.json()["temporary_pin"]}
    )
    assert exchanged.status_code == 200, exchanged.text
    bearer = {"Authorization": f"Bearer {exchanged.json()['access_token']}"}
    started_at = exchanged.json()["access_policy"]["completion_window_started_at"]
    expires_at = exchanged.json()["access_policy"]["completion_window_expires_at"]

    rejected = await _issue_link(
        client,
        enrollment_id,
        auth_headers(manager),
        completion_window_minutes=60,
    )
    assert rejected.status_code == 409
    assert rejected.json()["details"]["code"] == "assignment_window_already_started"

    still_active = await client.get(
        f"/api/v1/courses/{course.id}/access-window",
        headers=bearer,
    )
    assert still_active.status_code == 200, still_active.text
    assert still_active.json()["access_policy"]["completion_window_started_at"] == started_at
    assert still_active.json()["access_policy"]["completion_window_expires_at"] == expires_at


@pytest.mark.asyncio
async def test_audited_extension_keeps_started_marker_and_new_deadline_active(
    client, make_tenant, make_user, make_course, auth_headers, monkeypatch
):
    from app.modules.enrollments.notification_tasks import deliver_assignment_notification_task

    monkeypatch.setattr(deliver_assignment_notification_task, "apply_async", lambda *args, **kwargs: None)
    tenant = await make_tenant(name="Started extension")
    manager = await make_user(tenant, role="methodologist")
    learner = await make_user(tenant, role="student", email="learner@example.test")
    course = await make_course(tenant, manager, status="published")
    enrollment_id = await _enrollment(client, course, learner, auth_headers(manager))
    issued = await _issue_link(client, enrollment_id, auth_headers(manager), completion_window_minutes=30)
    token = issued.json()["access_url"].rsplit("/", 1)[1]
    exchanged = await client.post(
        f"/api/v1/assignment-access/{token}/exchange", json={"pin": issued.json()["temporary_pin"]}
    )
    assert exchanged.status_code == 200, exchanged.text
    bearer = {"Authorization": f"Bearer {exchanged.json()['access_token']}"}
    started_at = exchanged.json()["access_policy"]["completion_window_started_at"]

    extended = await client.post(
        f"/api/v1/courses/enrollments/{enrollment_id}/access-policy/extend",
        json={"completion_window_minutes": 60, "reason": "Approved extra time"},
        headers=auth_headers(manager),
    )
    assert extended.status_code == 200, extended.text
    assert extended.json()["completion_window_started_at"] == started_at
    assert extended.json()["completion_window_expires_at"] is not None

    active = await client.get(f"/api/v1/courses/{course.id}/access-window", headers=bearer)
    assert active.status_code == 200, active.text
    assert active.json()["access_policy"]["completion_window_started_at"] == started_at
    assert (
        active.json()["access_policy"]["completion_window_expires_at"]
        == extended.json()["completion_window_expires_at"]
    )
