"""Focused non-DB contracts for recurring program-assignment notifications."""

from __future__ import annotations

import ast
import asyncio
import inspect
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.email import EmailService
from app.modules.enrollments import notification_outbox, notification_tasks
from app.modules.enrollments.notification_outbox import (
    ClaimedLearningPathAssignmentNotification,
)


MIGRATION = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "0146_learning_path_assignment_notification_outbox.py"
)


def test_migration_is_assignment_deduplicated_rls_safe_and_recoverable():
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'down_revision = "0145"' in source
    assert "learning_path_assignment_id" in source
    assert "unique=True" in source
    assert "ON CONFLICT (learning_path_assignment_id)" in source
    assert "a.status = 'active'" in source
    assert "p.status = 'published'" in source
    assert "a.source = 'recurring'" not in source
    assert "JOIN learning_path_cycle_instances" not in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "current_setting('app.tenant_id', true)" in source
    assert "FOR UPDATE SKIP LOCKED" in source
    assert "SECURITY DEFINER" in source
    assert "REVOKE ALL ON TABLE learning_path_assignment_notification_outbox FROM PUBLIC, lms_app" in source
    assert "GRANT EXECUTE ON FUNCTION due_learning_path_assignment_notifications(integer) TO lms_recovery" in source
    assert "REVOKE ALL ON FUNCTION due_learning_path_assignment_notifications(integer) FROM lms_app" in source
    assert "GRANT EXECUTE ON FUNCTION enqueue_learning_path_assignment_notification(uuid,uuid,uuid) TO lms_app" in source
    assert "GRANT EXECUTE ON FUNCTION claim_learning_path_assignment_notification(uuid,uuid) TO lms_app" in source
    assert "GRANT EXECUTE ON FUNCTION finalize_learning_path_assignment_notification(uuid,uuid,uuid,text,text,text) TO lms_app" in source
    assert source.count("SET search_path = public, pg_temp") == 4
    assert source.count("v_context <> p_tenant_id") == 3
    assert "0146 downgrade blocked" in source


def test_migration_uses_one_database_command_per_op_execute():
    source = MIGRATION.read_text(encoding="utf-8")
    tree = ast.parse(source)
    execute_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "op"
        and node.func.attr == "execute"
    ]
    assert execute_calls
    for call in execute_calls:
        assert len(call.args) == 1
        assert not call.keywords
        if isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
            sql = call.args[0].value.strip().rstrip(";")
            assert not re.search(
                r";\s*(CREATE|ALTER|GRANT|REVOKE|DROP|DO)\b",
                sql,
                flags=re.IGNORECASE,
            )


class _ScalarDb:
    async def scalar(self, statement, params):
        self.statement = str(statement)
        self.params = params
        return self.event_id


@pytest.mark.asyncio
async def test_enqueue_contains_only_tenant_and_assignment_identifiers():
    db = _ScalarDb()
    db.event_id = uuid4()
    tenant_id, assignment_id, actor_id = uuid4(), uuid4(), uuid4()
    result = await notification_outbox.queue_learning_path_assignment_notification(
        db,
        tenant_id=tenant_id,
        learning_path_assignment_id=assignment_id,
        assigned_by=actor_id,
    )

    assert result == db.event_id
    assert "enqueue_learning_path_assignment_notification" in db.statement
    assert db.params == {
        "tenant_id": tenant_id,
        "learning_path_assignment_id": assignment_id,
        "assigned_by": actor_id,
    }


@pytest.mark.asyncio
async def test_concurrent_enqueue_calls_keep_one_assignment_identity():
    tenant_id, assignment_id, actor_id, event_id = uuid4(), uuid4(), uuid4(), uuid4()

    class ConcurrentDb:
        def __init__(self):
            self.params = []

        async def scalar(self, _statement, params):
            self.params.append(params)
            await asyncio.sleep(0)
            return event_id

    db = ConcurrentDb()
    results = await asyncio.gather(
        *(
            notification_outbox.queue_learning_path_assignment_notification(
                db,
                tenant_id=tenant_id,
                learning_path_assignment_id=assignment_id,
                assigned_by=actor_id,
            )
            for _ in range(2)
        )
    )

    assert results == [event_id, event_id]
    assert [params["learning_path_assignment_id"] for params in db.params] == [
        assignment_id,
        assignment_id,
    ]


class _Result:
    def __init__(self, row):
        self.row = row

    def one_or_none(self):
        return self.row


class _Session:
    def __init__(self, row, scalar_value=None):
        self.row = row
        self.scalar_value = scalar_value
        self.execute_calls = []
        self.scalar_statements = []

    async def execute(self, statement, params=None):
        self.execute_calls.append((str(statement), params))
        if str(statement).startswith("SELECT learning_path_assignments"):
            return _Result(self.row)
        return _Result(None)

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
        return ClaimedLearningPathAssignmentNotification(
            notification_id, tenant_id, uuid4(), uuid4()
        )

    async def finalize(self, _event, **kwargs):
        self.finalizations.append(kwargs)
        return True


@pytest.mark.asyncio
async def test_program_delivery_uses_one_program_message_and_program_route(monkeypatch):
    tenant_id, path_id = uuid4(), uuid4()
    row = (
        SimpleNamespace(id=uuid4(), tenant_id=tenant_id, path_id=path_id),
        SimpleNamespace(
            id=uuid4(),
            tenant_id=tenant_id,
            email="learner@example.test",
            first_name="Ada",
            last_name="L",
            has_login_access=True,
        ),
        SimpleNamespace(id=path_id, tenant_id=tenant_id, title="Safety program"),
        "Tenant",
    )
    session = _Session(row)
    email = SimpleNamespace(
        delivery_ready=lambda: True,
        send_learning_path_assignment=AsyncMock(return_value="msg-program-1"),
    )
    _Store.instances.clear()
    monkeypatch.setattr(notification_tasks, "async_session_factory", lambda: _SessionContext(session))
    monkeypatch.setattr(notification_tasks, "PostgresLearningPathAssignmentNotificationStore", _Store)
    monkeypatch.setattr(notification_tasks, "EmailService", lambda: email)
    monkeypatch.setattr(
        notification_tasks,
        "get_settings",
        lambda: SimpleNamespace(PUBLIC_URL="https://lms.example"),
    )

    result = await notification_tasks._deliver_learning_path(
        tenant_id=tenant_id, notification_id=uuid4()
    )

    assert result == {"status": "sent"}
    assert len([call for call in session.execute_calls if "set_current_tenant" in call[0]]) == 2
    email.send_learning_path_assignment.assert_awaited_once()
    kwargs = email.send_learning_path_assignment.await_args.kwargs
    assert kwargs["path_title"] == "Safety program"
    assert kwargs["access_url"] == "https://lms.example/learning-paths"
    assert kwargs["program_url"] == "https://lms.example/learning-paths"
    assert kwargs["idempotency_key"].startswith("learning-path-assignment/")
    assignment_query = next(
        statement
        for statement, _params in session.execute_calls
        if statement.startswith("SELECT learning_path_assignments")
    )
    assert "learning_path_assignments.status" in assignment_query
    assert "learning_paths.status" in assignment_query
    assert "learning_path_assignments.source =" not in assignment_query
    assert _Store.instances[-1].finalizations == [
        {"kind": "success", "message_id": "msg-program-1"}
    ]


@pytest.mark.asyncio
async def test_program_email_template_preserves_program_route_and_idempotency(monkeypatch):
    service = EmailService()
    send = AsyncMock(return_value="provider-id")
    monkeypatch.setattr(service, "_send", send)

    result = await service.send_learning_path_assignment(
        to_email="learner@example.test",
        company_name="Tenant",
        learner_name="Ada",
        path_title="Safety program",
        access_url="https://lms.example/learning-paths",
        program_url="https://lms.example/learning-paths",
        activation_required=False,
        idempotency_key="learning-path-assignment/event-id",
    )

    assert result == "provider-id"
    assert "Safety program" in send.await_args.kwargs["text"]
    assert "https://lms.example/learning-paths" in send.await_args.kwargs["html"]
    assert send.await_args.kwargs["idempotency_key"] == "learning-path-assignment/event-id"


def test_legacy_two_argument_course_task_executes_course_delivery(monkeypatch):
    signature = inspect.signature(notification_tasks.deliver_assignment_notification_task.run)
    assert signature.parameters["notification_kind"].default == "course"
    tenant_id, notification_id = uuid4(), uuid4()
    delivered = []

    async def deliver(**kwargs):
        delivered.append(kwargs)
        return {"status": "sent"}

    monkeypatch.setattr(notification_tasks, "_deliver", deliver)

    result = notification_tasks.deliver_assignment_notification_task.run(
        str(tenant_id), str(notification_id)
    )

    assert result == {"status": "sent"}
    assert delivered == [{"tenant_id": tenant_id, "notification_id": notification_id}]


@pytest.mark.asyncio
async def test_recovery_polls_and_delivers_program_outbox(monkeypatch):
    due = [SimpleNamespace(id=uuid4(), tenant_id=uuid4())]
    processed = []

    class EmptyCourseStore:
        def __init__(self, _db):
            pass

        async def due(self, limit):
            assert limit == 20
            return []

    class ProgramDueStore:
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
        lambda: SimpleNamespace(
            ASSIGNMENT_RECOVERY_DATABASE_URL="postgresql+asyncpg://recovery"
        ),
    )
    monkeypatch.setattr(
        notification_tasks,
        "create_async_engine",
        lambda *_args, **_kwargs: recovery_engine,
    )
    monkeypatch.setattr(
        notification_tasks,
        "async_sessionmaker",
        lambda *_args, **_kwargs: lambda: _SessionContext(object()),
    )
    monkeypatch.setattr(
        notification_tasks, "PostgresAssignmentNotificationStore", EmptyCourseStore
    )
    monkeypatch.setattr(
        notification_tasks,
        "PostgresLearningPathAssignmentNotificationStore",
        ProgramDueStore,
    )
    monkeypatch.setattr(notification_tasks, "_deliver_learning_path", deliver)

    assert await notification_tasks.recover_due_notifications() == {
        "due": 1,
        "processed": 1,
        "attempted": 1,
        "succeeded": 1,
        "failed": 0,
    }
    assert processed == [{"tenant_id": due[0].tenant_id, "notification_id": due[0].id}]
    recovery_engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_or_expired_program_invitation_is_terminal(monkeypatch):
    tenant_id, path_id = uuid4(), uuid4()
    row = (
        SimpleNamespace(id=uuid4(), tenant_id=tenant_id, path_id=path_id),
        SimpleNamespace(
            id=uuid4(),
            tenant_id=tenant_id,
            email="learner@example.test",
            first_name="Ada",
            last_name="L",
            has_login_access=False,
        ),
        SimpleNamespace(id=path_id, tenant_id=tenant_id, title="Safety program"),
        "Tenant",
    )
    session = _Session(row, scalar_value=None)
    email = SimpleNamespace(
        delivery_ready=lambda: True,
        send_learning_path_assignment=AsyncMock(),
    )
    _Store.instances.clear()
    monkeypatch.setattr(notification_tasks, "async_session_factory", lambda: _SessionContext(session))
    monkeypatch.setattr(notification_tasks, "PostgresLearningPathAssignmentNotificationStore", _Store)
    monkeypatch.setattr(notification_tasks, "EmailService", lambda: email)
    monkeypatch.setattr(
        notification_tasks,
        "get_settings",
        lambda: SimpleNamespace(PUBLIC_URL="https://lms.example"),
    )

    result = await notification_tasks._deliver_learning_path(
        tenant_id=tenant_id, notification_id=uuid4()
    )

    assert result == {"status": "dead"}
    assert "user_invitations.expires_at >" in session.scalar_statements[-1]
    assert _Store.instances[-1].finalizations[-1] == {
        "kind": "terminal",
        "error_category": "activation_not_prepared",
    }
    email.send_learning_path_assignment.assert_not_awaited()


@pytest.mark.asyncio
async def test_program_email_html_escapes_all_dynamic_values(monkeypatch):
    service = EmailService()
    send = AsyncMock(return_value="provider-id")
    monkeypatch.setattr(service, "_send", send)

    await service.send_learning_path_assignment(
        to_email="learner@example.test",
        company_name="Tenant <Admin>",
        learner_name="<Ada & Bob>",
        path_title='<script>alert("path")</script>',
        access_url='https://lms.example/learning-paths?x="bad"&y=1',
        program_url="https://lms.example/learning-paths?a=1&b=2",
        activation_required=False,
        idempotency_key="learning-path-assignment/event-id",
    )

    html = send.await_args.kwargs["html"]
    assert "<script>" not in html
    assert "Tenant &lt;Admin&gt;" in html
    assert "&lt;Ada &amp; Bob&gt;" in html
    assert "&lt;script&gt;alert(&quot;path&quot;)&lt;/script&gt;" in html
    assert "x=&quot;bad&quot;&amp;y=1" in html
    assert "a=1&amp;b=2" in html


@pytest.mark.asyncio
async def test_claim_and_finalize_forward_exact_tenant_and_claim_token():
    tenant_id, notification_id, assignment_id, claim_token = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )

    class MappingResult:
        def mappings(self):
            return self

        def one_or_none(self):
            return {
                "id": notification_id,
                "tenant_id": tenant_id,
                "learning_path_assignment_id": assignment_id,
                "claim_token": claim_token,
            }

    class Db:
        def __init__(self):
            self.execute_params = None
            self.scalar_params = None
            self.commits = 0

        async def execute(self, statement, params):
            self.execute_statement = str(statement)
            self.execute_params = params
            return MappingResult()

        async def scalar(self, statement, params):
            self.scalar_statement = str(statement)
            self.scalar_params = params
            return True

        async def commit(self):
            self.commits += 1

    db = Db()
    store = notification_outbox.PostgresLearningPathAssignmentNotificationStore(db)
    item = await store.claim(tenant_id=tenant_id, notification_id=notification_id)
    assert item is not None
    assert db.execute_params == {
        "tenant_id": tenant_id,
        "notification_id": notification_id,
    }

    assert await store.finalize(item, kind="success", message_id="provider-id") is True
    assert db.scalar_params == {
        "tenant_id": tenant_id,
        "id": notification_id,
        "token": claim_token,
        "kind": "success",
        "message_id": "provider-id",
        "error_category": "",
    }
    assert db.commits == 2


@pytest.mark.asyncio
async def test_recovery_is_fair_globally_bounded_and_continues_after_poison_item(monkeypatch):
    course_due = [SimpleNamespace(id=uuid4(), tenant_id=uuid4()) for _ in range(3)]
    program_due = [SimpleNamespace(id=uuid4(), tenant_id=uuid4()) for _ in range(3)]
    attempted = []

    class CourseStore:
        def __init__(self, _db):
            pass

        async def due(self, limit):
            assert limit == 3
            return course_due

    class ProgramStore:
        def __init__(self, _db):
            pass

        async def due(self, limit):
            assert limit == 3
            return program_due

    async def deliver_course(**kwargs):
        attempted.append(("course", kwargs["notification_id"]))
        if kwargs["notification_id"] == course_due[0].id:
            raise RuntimeError("poison course row")
        return {"status": "sent"}

    async def deliver_program(**kwargs):
        attempted.append(("learning_path", kwargs["notification_id"]))
        return {"status": "sent"}

    recovery_engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(
        notification_tasks,
        "get_settings",
        lambda: SimpleNamespace(
            ASSIGNMENT_RECOVERY_DATABASE_URL="postgresql+asyncpg://recovery"
        ),
    )
    monkeypatch.setattr(
        notification_tasks,
        "create_async_engine",
        lambda *_args, **_kwargs: recovery_engine,
    )
    monkeypatch.setattr(
        notification_tasks,
        "async_sessionmaker",
        lambda *_args, **_kwargs: lambda: _SessionContext(object()),
    )
    monkeypatch.setattr(notification_tasks, "PostgresAssignmentNotificationStore", CourseStore)
    monkeypatch.setattr(
        notification_tasks,
        "PostgresLearningPathAssignmentNotificationStore",
        ProgramStore,
    )
    monkeypatch.setattr(notification_tasks, "_deliver", deliver_course)
    monkeypatch.setattr(notification_tasks, "_deliver_learning_path", deliver_program)

    result = await notification_tasks.recover_due_notifications(limit=3)

    assert result == {
        "due": 3,
        "processed": 3,
        "attempted": 3,
        "succeeded": 2,
        "failed": 1,
    }
    assert attempted == [
        ("course", course_due[0].id),
        ("learning_path", program_due[0].id),
        ("course", course_due[1].id),
    ]
