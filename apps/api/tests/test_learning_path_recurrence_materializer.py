"""Focused non-DB contracts for recurring learning-path materialization."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.learning_cycles import service as cycle_service
from app.modules.learning_cycles.models import LearningPathCycleInstance
from app.modules.enrollments import notification_tasks
from app.modules.learning_paths import service as path_service
from app.modules.learning_paths.models import LearningPathAssignment


@pytest.mark.parametrize(
    "entrypoint",
    (
        "app.modules.learning_cycles.service",
        "app.modules.learning_cycles.tasks",
    ),
)
def test_direct_runtime_entrypoint_registers_all_cycle_foreign_keys(entrypoint):
    code = f"""
import importlib
importlib.import_module({entrypoint!r})
from app.modules.learning_cycles.models import LearningPathCycleInstance
from app.modules.learning_paths.models import LearningPathAssignment

for table in (LearningPathCycleInstance.__table__, LearningPathAssignment.__table__):
    for foreign_key in table.foreign_keys:
        foreign_key.column
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _Db:
    def __init__(self, values, events=None):
        self.values = iter(values)
        self.added = []
        self.commits = 0
        self.events = events

    async def execute(self, *_args, **_kwargs):
        return None

    async def scalar(self, _statement):
        return next(self.values)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        for value in self.added:
            if isinstance(value, (LearningPathCycleInstance, LearningPathAssignment)) and value.id is None:
                value.id = uuid4()

    async def commit(self):
        self.commits += 1
        if self.events is not None:
            self.events.append("commit")

    def begin_nested(self):
        return _Savepoint()


class _SessionContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *_args):
        return False


def _path(tenant_id, *, status="published"):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        status=status,
        recurrence_mode="fixed_interval_after_completion",
        recurrence_cadence_days=30,
        recurrence_due_days=7,
        sequencing_mode="linear",
        courses=[],
    )


def _rule(tenant_id, path, user_id, *, next_run_at):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        learning_path_id=path.id,
        course_id=None,
        user_id=user_id,
        cadence_days=30,
        due_days=7,
        status="active",
        next_run_at=next_run_at,
        last_run_at=None,
        created_by=uuid4(),
    )


@pytest.mark.asyncio
async def test_due_path_rule_creates_one_cycle_and_recurring_assignment(monkeypatch):
    tenant_id, user_id = uuid4(), uuid4()
    scheduled_for = datetime(2026, 9, 1, tzinfo=UTC)
    path = _path(tenant_id)
    rule = _rule(tenant_id, path, user_id, next_run_at=scheduled_for)
    learner = SimpleNamespace(
        id=user_id,
        role="student",
        is_active=True,
        status="active",
        email="learner@example.test",
        has_login_access=True,
    )
    events = []
    db = _Db([rule, path, learner, None, 0], events)

    monkeypatch.setattr(cycle_service, "async_session_factory", lambda: _SessionContext(db))
    sync = AsyncMock(return_value=0)
    monkeypatch.setattr(cycle_service, "sync_assignment_enrollments", sync)
    notification_id = uuid4()

    async def enqueue(*_args, **_kwargs):
        assert db.commits == 0
        events.append("enqueue")
        return notification_id

    dispatch = MagicMock(side_effect=lambda **_kwargs: events.append("dispatch"))
    monkeypatch.setattr(cycle_service, "queue_learning_path_assignment_notification", enqueue)
    monkeypatch.setattr(notification_tasks.deliver_assignment_notification_task, "apply_async", dispatch)

    result = await cycle_service.materialize_rule(rule.id, tenant_id, now=scheduled_for)

    cycles = [item for item in db.added if isinstance(item, LearningPathCycleInstance)]
    assignments = [item for item in db.added if item.__class__.__name__ == "LearningPathAssignment"]
    assert result["status"] == "materialized"
    assert len(cycles) == 1
    assert len(assignments) == 1
    assert assignments[0].source == "recurring"
    assert assignments[0].recurrence_instance_id == cycles[0].id
    assert cycles[0].sequence_no == 1
    assert cycles[0].due_at == scheduled_for + timedelta(days=7)
    sync.assert_awaited_once()
    assert rule.last_run_at == scheduled_for
    assert rule.next_run_at is None
    assert db.commits == 1
    assert result["notification_id"] == str(notification_id)
    assert events == ["enqueue", "commit", "dispatch"]
    assert dispatch.call_args.kwargs["kwargs"] == {"notification_kind": "learning_path"}


@pytest.mark.asyncio
async def test_invalid_active_learner_creates_a_skipped_cycle_without_assignment(monkeypatch):
    tenant_id, user_id = uuid4(), uuid4()
    scheduled_for = datetime(2026, 9, 1, tzinfo=UTC)
    path = _path(tenant_id)
    rule = _rule(tenant_id, path, user_id, next_run_at=scheduled_for)
    learner = SimpleNamespace(
        id=user_id,
        role="student",
        is_active=False,
        status="active",
        email="learner@example.test",
        has_login_access=True,
    )
    db = _Db([rule, path, learner, None, 0])

    monkeypatch.setattr(cycle_service, "async_session_factory", lambda: _SessionContext(db))
    sync = AsyncMock()
    monkeypatch.setattr(cycle_service, "sync_assignment_enrollments", sync)
    enqueue = AsyncMock()
    monkeypatch.setattr(cycle_service, "queue_learning_path_assignment_notification", enqueue)

    await cycle_service.materialize_rule(rule.id, tenant_id, now=scheduled_for)

    cycles = [item for item in db.added if isinstance(item, LearningPathCycleInstance)]
    assert len(cycles) == 1
    assert cycles[0].status == "skipped"
    assert not [item for item in db.added if item.__class__.__name__ == "LearningPathAssignment"]
    sync.assert_not_awaited()
    enqueue.assert_not_awaited()
    assert rule.next_run_at is None


@pytest.mark.asyncio
async def test_missing_path_deactivates_rule_without_fabricating_cycle(monkeypatch):
    tenant_id, user_id = uuid4(), uuid4()
    scheduled_for = datetime(2026, 9, 1, tzinfo=UTC)
    path = _path(tenant_id)
    rule = _rule(tenant_id, path, user_id, next_run_at=scheduled_for)
    learner = SimpleNamespace(
        id=user_id,
        role="student",
        is_active=True,
        status="active",
        email="learner@example.test",
        has_login_access=True,
    )
    db = _Db([rule, None, learner, None, 0])

    monkeypatch.setattr(cycle_service, "async_session_factory", lambda: _SessionContext(db))

    result = await cycle_service.materialize_rule(rule.id, tenant_id, now=scheduled_for)

    assert result == {"status": "skipped", "reason": "missing_path"}
    assert rule.status == "inactive"
    assert rule.next_run_at == scheduled_for
    assert not [item for item in db.added if isinstance(item, LearningPathCycleInstance)]
    assert db.commits == 1


@pytest.mark.asyncio
async def test_dispatch_failure_keeps_durable_program_event_recoverable(monkeypatch):
    tenant_id, user_id = uuid4(), uuid4()
    scheduled_for = datetime(2026, 9, 1, tzinfo=UTC)
    path = _path(tenant_id)
    rule = _rule(tenant_id, path, user_id, next_run_at=scheduled_for)
    learner = SimpleNamespace(
        id=user_id,
        role="student",
        is_active=True,
        status="active",
        email="learner@example.test",
        has_login_access=True,
    )
    events = []
    db = _Db([rule, path, learner, None, 0], events)
    notification_id = uuid4()
    monkeypatch.setattr(cycle_service, "async_session_factory", lambda: _SessionContext(db))
    monkeypatch.setattr(cycle_service, "sync_assignment_enrollments", AsyncMock(return_value=0))

    async def enqueue(*_args, **_kwargs):
        events.append("enqueue")
        return notification_id

    monkeypatch.setattr(cycle_service, "queue_learning_path_assignment_notification", enqueue)
    dispatch = MagicMock(side_effect=RuntimeError("broker unavailable"))
    monkeypatch.setattr(notification_tasks.deliver_assignment_notification_task, "apply_async", dispatch)

    result = await cycle_service.materialize_rule(rule.id, tenant_id, now=scheduled_for)

    assert result == {"status": "materialized", "notification_id": str(notification_id)}
    assert events == ["enqueue", "commit"]
    dispatch.assert_called_once()

    due = [SimpleNamespace(id=notification_id, tenant_id=tenant_id)]
    recovered = []

    class EmptyCourseStore:
        def __init__(self, _db):
            pass

        async def due(self, _limit):
            return []

    class ProgramStore:
        def __init__(self, _db):
            pass

        async def due(self, _limit):
            return due

    async def deliver(**kwargs):
        recovered.append(kwargs)
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
        ProgramStore,
    )
    monkeypatch.setattr(notification_tasks, "_deliver_learning_path", deliver)

    recovery_result = await notification_tasks.recover_due_notifications(limit=1)

    assert recovery_result == {
        "due": 1,
        "processed": 1,
        "attempted": 1,
        "succeeded": 1,
        "failed": 0,
    }
    assert recovered == [{"tenant_id": tenant_id, "notification_id": notification_id}]


@pytest.mark.asyncio
async def test_completion_schedules_rule_and_cycle_once():
    tenant_id, user_id = uuid4(), uuid4()
    path = _path(tenant_id)
    completed_at = datetime(2026, 9, 2, tzinfo=UTC)
    rule = SimpleNamespace(status="active", next_run_at=None)
    cycle_completed_at = completed_at - timedelta(minutes=1)
    cycle = SimpleNamespace(status="completed", completed_at=cycle_completed_at)
    assignment = SimpleNamespace(
        tenant_id=tenant_id,
        path_id=path.id,
        user_id=user_id,
        assigned_by=uuid4(),
        recurrence_instance_id=uuid4(),
    )
    db = _Db([rule, cycle])

    await path_service._schedule_recurrence_after_completion(
        db, assignment, path, completed_at=completed_at
    )

    assert rule.next_run_at == completed_at + timedelta(days=30)
    assert cycle.status == "completed"
    assert cycle.completed_at == cycle_completed_at


@pytest.mark.asyncio
async def test_completion_does_not_create_missing_rule():
    tenant_id, user_id = uuid4(), uuid4()
    path = _path(tenant_id)
    assignment = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        path_id=path.id,
        user_id=user_id,
        assigned_by=uuid4(),
        recurrence_instance_id=None,
    )
    db = _Db([None])

    await path_service._schedule_recurrence_after_completion(
        db,
        assignment,
        path,
        completed_at=datetime(2026, 9, 2, tzinfo=UTC),
    )

    assert db.added == []


@pytest.mark.asyncio
async def test_assignment_scopes_progress_and_new_occurrence_stays_active(monkeypatch):
    tenant_id, user_id, assignment_id = uuid4(), uuid4(), uuid4()
    course_id = uuid4()
    assignment = SimpleNamespace(
        id=assignment_id,
        tenant_id=tenant_id,
        user_id=user_id,
        status="active",
        starts_at=None,
    )
    course = SimpleNamespace(id=course_id, status="published")
    step = SimpleNamespace(course_id=course_id, required=True, order_index=0, course=course)
    path = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        status="published",
        sequencing_mode="linear",
        recurrence_mode="fixed_interval_after_completion",
        recurrence_cadence_days=30,
        recurrence_due_days=7,
        courses=[step],
    )

    class Result:
        def __init__(self, values):
            self.values = values

        def scalars(self):
            return self

        def all(self):
            return self.values

    class Db:
        def __init__(self):
            self.added = []
            self.statements = []

        async def execute(self, statement):
            self.statements.append(str(statement))
            return Result([])

        def add(self, value):
            self.added.append(value)

        async def flush(self):
            return None

    db = Db()
    monkeypatch.setattr(path_service, "_load_assignment_path", AsyncMock(return_value=path))

    await path_service.sync_assignment_enrollments(db, assignment)

    assert assignment.status == "active"
    assert len(db.added) == 1
    assert db.added[0].learning_path_assignment_id == assignment_id
    assert all("learning_path_assignment_id" in statement for statement in db.statements)
