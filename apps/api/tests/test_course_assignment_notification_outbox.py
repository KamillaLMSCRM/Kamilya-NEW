from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.enrollments import notification_outbox, notification_tasks
from app.modules.enrollments.notification_outbox import ClaimedAssignmentNotification

MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0097_course_assignment_notification_outbox.py"


def test_migration_is_bounded_rls_safe_and_idempotent():
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'down_revision = "0096"' in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "REVOKE ALL ON TABLE course_assignment_notification_outbox FROM PUBLIC, lms_app" in source
    assert "SECURITY DEFINER" in source
    assert "current_setting('app.tenant_id', true)" in source
    assert "FOR UPDATE SKIP LOCKED" in source
    assert "ON CONFLICT(enrollment_id)" in source
    assert "p_kind NOT IN ('success','terminal','transient','defer')" in source
    assert "0097 downgrade blocked" in source


def test_recovery_and_resend_interfaces_are_bounded():
    source = MIGRATION.read_text(encoding="utf-8")
    assert "due_course_assignment_notifications(p_limit integer DEFAULT 20)" in source
    assert "LIMIT greatest(1,least(p_limit,100))" in source
    assert "requeue_course_assignment_notification" in source
    assert "tenant_id=p_tenant_id" in source
    assert "Required role lms_recovery is missing" in source
    assert "GRANT EXECUTE ON FUNCTION due_course_assignment_notifications(integer) TO lms_recovery" in source
    assert "REVOKE ALL ON FUNCTION due_course_assignment_notifications(integer) FROM lms_app" in source


def test_tasks_are_routed_to_notifications():
    from app.core.celery_app import celery_app

    for name in (
        "enrollments.deliver_assignment_notification",
        "enrollments.recover_assignment_notifications",
    ):
        route = celery_app.amqp.router.route({}, name, args=(), kwargs={})
        assert route["queue"].name == "notifications"


def test_broker_independent_timer_invokes_direct_recovery_module():
    root = Path(__file__).parents[3]
    service = (root / "infra/systemd/kamilya-assignment-notification-recovery.service").read_text(encoding="utf-8")
    timer = (root / "infra/systemd/kamilya-assignment-notification-recovery.timer").read_text(encoding="utf-8")
    assert "app.modules.enrollments.notification_recovery" in service
    assert "celery" not in service.lower()
    assert "OnUnitActiveSec=1min" in timer
    assert "Persistent=true" in timer


class _Result:
    def __init__(self, value=None):
        self.value = value

    def one_or_none(self):
        return self.value


class _Session:
    def __init__(self, row, scalar_value=None):
        self.row = row
        self.scalar_value = scalar_value
        self.execute_calls = []
        self.scalar_statements = []

    async def execute(self, statement, params=None):
        self.execute_calls.append((str(statement), params))
        if str(statement).startswith("SELECT enrollments"):
            return _Result(self.row)
        return _Result()

    async def scalar(self, statement):
        self.scalar_statements.append(str(statement))
        return self.scalar_value


class _SessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args):
        return False


class _Store:
    instances = []

    def __init__(self, _db):
        self.finalizations = []
        _Store.instances.append(self)

    async def claim(self, *, tenant_id, notification_id):
        return ClaimedAssignmentNotification(notification_id, tenant_id, uuid4(), uuid4())

    async def finalize(self, _event, **kwargs):
        self.finalizations.append(kwargs)
        return True


def _row(*, login_access: bool):
    tenant_id, course_id = uuid4(), uuid4()
    return tenant_id, (
        SimpleNamespace(id=uuid4()),
        SimpleNamespace(
            id=uuid4(),
            tenant_id=tenant_id,
            email="learner@example.test",
            first_name="Ada",
            last_name="L",
            has_login_access=login_access,
        ),
        SimpleNamespace(id=course_id, tenant_id=tenant_id, title="Safety"),
        "Tenant",
    )


@pytest.mark.asyncio
async def test_claim_commit_is_followed_by_tenant_context_reset(monkeypatch):
    tenant_id, row = _row(login_access=True)
    session = _Session(row)
    email = SimpleNamespace(delivery_ready=lambda: True, send_course_assignment=AsyncMock(return_value="msg-1"))
    _Store.instances.clear()
    monkeypatch.setattr(notification_tasks, "async_session_factory", lambda: _SessionContext(session))
    monkeypatch.setattr(notification_tasks, "PostgresAssignmentNotificationStore", _Store)
    monkeypatch.setattr(notification_tasks, "EmailService", lambda: email)
    monkeypatch.setattr(notification_tasks, "get_settings", lambda: SimpleNamespace(PUBLIC_URL="https://lms.example"))

    result = await notification_tasks._deliver(tenant_id=tenant_id, notification_id=uuid4())

    context_calls = [call for call in session.execute_calls if "set_current_tenant" in call[0]]
    assert len(context_calls) == 2
    assert result == {"status": "sent"}
    assert email.send_course_assignment.await_args.kwargs["access_url"].startswith("https://lms.example/")
    assert email.send_course_assignment.await_args.kwargs["idempotency_key"].startswith("course-assignment/")


@pytest.mark.asyncio
async def test_unconfigured_email_is_deferred_without_send(monkeypatch):
    tenant_id, row = _row(login_access=True)
    session = _Session(row)
    email = SimpleNamespace(delivery_ready=lambda: False, send_course_assignment=AsyncMock())
    _Store.instances.clear()
    monkeypatch.setattr(notification_tasks, "async_session_factory", lambda: _SessionContext(session))
    monkeypatch.setattr(notification_tasks, "PostgresAssignmentNotificationStore", _Store)
    monkeypatch.setattr(notification_tasks, "EmailService", lambda: email)

    result = await notification_tasks._deliver(tenant_id=tenant_id, notification_id=uuid4())

    assert result == {"status": "deferred"}
    assert _Store.instances[-1].finalizations[-1] == {"kind": "defer", "error_category": "configuration_missing"}
    email.send_course_assignment.assert_not_awaited()


@pytest.mark.asyncio
async def test_inactive_learner_without_unexpired_invite_is_not_emailed(monkeypatch):
    tenant_id, row = _row(login_access=False)
    session = _Session(row)
    email = SimpleNamespace(delivery_ready=lambda: True, send_course_assignment=AsyncMock())
    _Store.instances.clear()
    monkeypatch.setattr(notification_tasks, "async_session_factory", lambda: _SessionContext(session))
    monkeypatch.setattr(notification_tasks, "PostgresAssignmentNotificationStore", _Store)
    monkeypatch.setattr(notification_tasks, "EmailService", lambda: email)
    monkeypatch.setattr(notification_tasks, "get_settings", lambda: SimpleNamespace(PUBLIC_URL="https://lms.example"))

    result = await notification_tasks._deliver(tenant_id=tenant_id, notification_id=uuid4())

    assert result == {"status": "dead"}
    assert "user_invitations.expires_at >" in session.scalar_statements[-1]
    assert _Store.instances[-1].finalizations[-1]["error_category"] == "activation_not_prepared"
    email.send_course_assignment.assert_not_awaited()


@pytest.mark.asyncio
async def test_activation_assignment_email_updates_invitation_delivery_lifecycle(monkeypatch):
    tenant_id, row = _row(login_access=False)
    invite = SimpleNamespace(
        token="valid-token",
        delivery_status="pending",
        delivery_message_id=None,
        delivery_last_attempt_at=None,
        delivery_attempt_count=0,
        delivery_failure_category="old",
        delivery_failure_message="old",
    )
    session = _Session(row, scalar_value=invite)
    email = SimpleNamespace(delivery_ready=lambda: True, send_course_assignment=AsyncMock(return_value="provider-1"))
    _Store.instances.clear()
    monkeypatch.setattr(notification_tasks, "async_session_factory", lambda: _SessionContext(session))
    monkeypatch.setattr(notification_tasks, "PostgresAssignmentNotificationStore", _Store)
    monkeypatch.setattr(notification_tasks, "EmailService", lambda: email)
    monkeypatch.setattr(notification_tasks, "get_settings", lambda: SimpleNamespace(PUBLIC_URL="https://lms.example"))
    assert await notification_tasks._deliver(tenant_id=tenant_id, notification_id=uuid4()) == {"status": "sent"}
    assert email.send_course_assignment.await_args.kwargs["activation_required"] is True
    assert (
        email.send_course_assignment.await_args.kwargs["access_url"]
        == "https://lms.example/accept-invite?token=valid-token"
    )
    assert invite.delivery_status == "sent"
    assert invite.delivery_message_id == "provider-1"
    assert invite.delivery_attempt_count == 1
    assert invite.delivery_failure_category is None


@pytest.mark.asyncio
async def test_recovery_processes_bounded_due_rows_directly(monkeypatch):
    due = [SimpleNamespace(id=uuid4(), tenant_id=uuid4()), SimpleNamespace(id=uuid4(), tenant_id=uuid4())]
    processed = []

    class DueStore:
        def __init__(self, _db):
            pass

        async def due(self, limit):
            assert limit == 20
            return due

    async def deliver(**kwargs):
        processed.append(kwargs)
        return {"status": "sent"}

    recovery_engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(
        notification_tasks,
        "get_settings",
        lambda: SimpleNamespace(ASSIGNMENT_RECOVERY_DATABASE_URL="postgresql+asyncpg://recovery"),
    )
    monkeypatch.setattr(notification_tasks, "create_async_engine", lambda *_args, **_kwargs: recovery_engine)
    monkeypatch.setattr(
        notification_tasks, "async_sessionmaker", lambda *_args, **_kwargs: lambda: _SessionContext(object())
    )
    monkeypatch.setattr(notification_tasks, "PostgresAssignmentNotificationStore", DueStore)
    monkeypatch.setattr(notification_tasks, "_deliver", deliver)
    assert await notification_tasks.recover_due_notifications() == {"due": 2, "processed": 2}
    assert processed == [{"tenant_id": item.tenant_id, "notification_id": item.id} for item in due]
    recovery_engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_recovery_refuses_shared_api_database_role(monkeypatch):
    monkeypatch.setattr(
        notification_tasks, "get_settings", lambda: SimpleNamespace(ASSIGNMENT_RECOVERY_DATABASE_URL="")
    )
    with pytest.raises(RuntimeError, match="ASSIGNMENT_RECOVERY_DATABASE_URL"):
        await notification_tasks.recover_due_notifications()


@pytest.mark.asyncio
async def test_store_rejects_invalid_finalize_kind_without_db_call():
    db = SimpleNamespace(scalar=AsyncMock(), commit=AsyncMock())
    store = notification_outbox.PostgresAssignmentNotificationStore(db)
    event = ClaimedAssignmentNotification(uuid4(), uuid4(), uuid4(), uuid4())
    with pytest.raises(ValueError, match="invalid assignment notification"):
        await store.finalize(event, kind="invented")
    db.scalar.assert_not_awaited()


def _enrollment_db(user):
    db = AsyncMock()
    course = SimpleNamespace(id=uuid4(), tenant_id=user.tenant_id, status="published")
    db.scalar = AsyncMock(return_value=course)
    users_result = MagicMock()
    users_result.scalars.return_value.all.return_value = [user]
    duplicate_result = MagicMock()
    duplicate_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(side_effect=[users_result, duplicate_result])
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db, course


@pytest.mark.asyncio
async def test_manual_assignment_prepares_activation_and_outbox_without_commit():
    from app.modules.enrollments.service import enroll_users

    tenant_id, actor_id = uuid4(), uuid4()
    learner = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        role="student",
        is_active=True,
        status="active",
        email="new@example.test",
        has_login_access=False,
    )
    db, course = _enrollment_db(learner)
    invitation = AsyncMock(return_value={"invitation_id": uuid4()})
    enqueue = AsyncMock(return_value=uuid4())
    release = SimpleNamespace(id=uuid4())
    with (
        patch("app.modules.enrollments.service.ensure_course_release", new=AsyncMock(return_value=release)),
        patch("app.modules.users.invitations_service.prepare_user_invitation", new=invitation),
        patch("app.modules.enrollments.service.queue_manual_enrollment_notification", new=enqueue),
    ):
        created = await enroll_users(db, course.id, tenant_id, [learner.id], assigned_by=actor_id)
    assert len(created) == 1
    invitation.assert_awaited_once()
    assert invitation.await_args.kwargs["reuse_valid"] is True
    enqueue.assert_awaited_once_with(db, tenant_id=tenant_id, enrollment_id=created[0].id, assigned_by=actor_id)
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_active_learner_queues_course_notification_without_invitation():
    from app.modules.enrollments.service import enroll_users

    tenant_id, actor_id = uuid4(), uuid4()
    learner = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        role="student",
        is_active=True,
        status="active",
        email="active@example.test",
        has_login_access=True,
    )
    db, course = _enrollment_db(learner)
    invitation = AsyncMock()
    enqueue = AsyncMock(return_value=uuid4())
    with (
        patch(
            "app.modules.enrollments.service.ensure_course_release",
            new=AsyncMock(return_value=SimpleNamespace(id=uuid4())),
        ),
        patch("app.modules.users.invitations_service.prepare_user_invitation", new=invitation),
        patch("app.modules.enrollments.service.queue_manual_enrollment_notification", new=enqueue),
    ):
        created = await enroll_users(db, course.id, tenant_id, [learner.id], assigned_by=actor_id)
    assert len(created) == 1
    invitation.assert_not_awaited()
    enqueue.assert_awaited_once()


@pytest.mark.asyncio
async def test_broker_failure_after_commit_does_not_lose_assignment():
    from app.modules.enrollments import router

    tenant_id = uuid4()
    enrollment = SimpleNamespace(id=uuid4(), notification_outbox_id=uuid4())
    db = SimpleNamespace(commit=AsyncMock())
    user = SimpleNamespace(id=uuid4(), tenant_id=tenant_id)
    with (
        patch.object(router, "enroll_users", new=AsyncMock(return_value=[enrollment])),
        patch.object(
            notification_tasks.deliver_assignment_notification_task,
            "apply_async",
            side_effect=RuntimeError("broker down"),
        ),
    ):
        result = await router.create_enrollments(
            uuid4(),
            SimpleNamespace(
                user_ids=[uuid4()],
                delivery_mode="email",
                link_expires_at=None,
                completion_window_minutes=None,
                due_at=None,
            ),
            db,
            user,
        )
    assert result == [enrollment]
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_active_email_learner_gets_configured_course_url_without_invitation_query():
    from app.modules.enrollments.service import get_enrollment_access

    tenant_id, enrollment_id, course_id = uuid4(), uuid4(), uuid4()
    enrollment = SimpleNamespace(id=enrollment_id, user_id=uuid4(), course_id=course_id)
    learner = SimpleNamespace(id=enrollment.user_id, email="active@example.test", has_login_access=True)
    row_result = MagicMock()
    row_result.one_or_none.return_value = (enrollment, learner)
    db = SimpleNamespace(execute=AsyncMock(return_value=row_result), scalar=AsyncMock(return_value=None))
    access = await get_enrollment_access(db, enrollment_id, tenant_id, base_url="https://tenant.example/")
    assert access["access_kind"] == "course_access"
    assert access["access_url"] == f"https://tenant.example/courses/{course_id}"
    # Access policy must be read even for an email-capable learner because a
    # methodologist may explicitly choose personal-link delivery for them.
    db.scalar.assert_awaited_once()
