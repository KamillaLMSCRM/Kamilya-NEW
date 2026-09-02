import ast
from datetime import UTC, datetime
from pathlib import Path
import re
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.learning_cycles.bridge import (
    reconcile_learning_path_assignment,
    sync_learning_path_rules,
)
from app.modules.learning_cycles.router import list_latest_occurrences
from app.modules.learning_cycles.schemas import RuleCreate, RuleResponse

ROOT = Path(__file__).resolve().parents[3]


def _path(**overrides):
    values = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "status": "published",
        "recurrence_mode": "fixed_interval_after_completion",
        "recurrence_cadence_days": 30,
        "recurrence_due_days": 7,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_reconcile_creates_active_rule_from_published_path_without_schedule():
    path = _path()
    learner_id = uuid4()
    db = SimpleNamespace(
        scalar=AsyncMock(side_effect=[learner_id, None]),
        flush=AsyncMock(),
        begin_nested=lambda: _Savepoint(),
    )
    db.add = lambda value: setattr(db, "created", value)

    result = await reconcile_learning_path_assignment(
        db, path=path, user_id=learner_id, created_by=uuid4()
    )

    assert result.action == "created"
    assert db.created.learning_path_id == path.id
    assert db.created.cadence_days == 30
    assert db.created.due_days == 7
    assert db.created.status == "active"
    assert db.created.next_run_at is None


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


@pytest.mark.asyncio
async def test_reconcile_recovers_unique_race_inside_nested_savepoint():
    path = _path()
    learner_id = uuid4()
    existing = SimpleNamespace(cadence_days=5, due_days=2)

    class RaceDb:
        def __init__(self):
            self.values = iter([learner_id, None, existing])
            self.flush_calls = 0

        async def scalar(self, _statement):
            return next(self.values)

        def add(self, _value):
            pass

        def begin_nested(self):
            return _Savepoint()

        async def flush(self):
            self.flush_calls += 1
            raise IntegrityError("insert", {}, Exception("duplicate"))

    db = RaceDb()
    result = await reconcile_learning_path_assignment(
        db, path=path, user_id=learner_id, created_by=uuid4()
    )

    assert result.action == "reconciled"
    assert result.rule is existing
    assert existing.cadence_days == path.recurrence_cadence_days
    assert existing.due_days == path.recurrence_due_days
    assert db.flush_calls == 1


def test_rule_contract_has_nullable_targets_and_target_type():
    course = uuid4()
    rule = SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), course_id=course, learning_path_id=None,
        user_id=uuid4(), cadence_days=30, due_days=7, status="draft",
        next_run_at=None, last_run_at=None, target_type="course",
    )
    response = RuleResponse.model_validate(rule)
    assert response.target_type == "course"
    assert response.course_id == course
    assert response.learning_path_id is None
    assert RuleCreate(course_id=course, user_id=uuid4(), cadence_days=3650, due_days=3650).due_days == 3650
    with pytest.raises(ValueError):
        RuleCreate(learning_path_id=uuid4(), user_id=uuid4(), cadence_days=3, due_days=1)
    with pytest.raises(ValueError):
        RuleCreate(course_id=course, user_id=uuid4(), cadence_days=10, due_days=11)


@pytest.mark.asyncio
async def test_sync_counts_only_real_rule_actions_and_skips_cancelled_history(monkeypatch):
    path = _path()
    active = SimpleNamespace(user_id=uuid4(), status="active")
    cancelled = SimpleNamespace(user_id=uuid4(), status="cancelled")
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [active, cancelled])
            )
        )
    )
    outcome = SimpleNamespace(action="created", rule=object())
    monkeypatch.setattr(
        "app.modules.learning_cycles.bridge.reconcile_learning_path_assignment",
        AsyncMock(return_value=outcome),
    )

    result = await sync_learning_path_rules(db, path=path, created_by=uuid4())

    assert result.total == 2
    assert result.created == 1
    assert result.reconciled == 0
    assert result.skipped == 1


@pytest.mark.asyncio
async def test_sync_does_not_arm_completed_or_create_stale_rule(monkeypatch):
    path = _path()
    completed = SimpleNamespace(user_id=uuid4(), status="completed", completed_at=datetime.now(UTC))
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [completed]))
        )
    )
    reconcile = AsyncMock()
    monkeypatch.setattr("app.modules.learning_cycles.bridge.reconcile_learning_path_assignment", reconcile)

    result = await sync_learning_path_rules(db, path=path, created_by=uuid4())

    assert result.total == 1
    assert result.created == 0
    assert result.reconciled == 0
    assert result.skipped == 1
    reconcile.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancelled_recurring_assignment_is_not_reactivated_as_manual():
    from app.modules.learning_paths.router import assign_path_audience
    from app.modules.learning_paths.schemas import LearningPathAssignmentAudience

    path = _path()
    learner_id = uuid4()
    cycle_id = uuid4()
    recurring_assignment = SimpleNamespace(
        user_id=learner_id,
        status="cancelled",
        recurrence_instance_id=cycle_id,
    )
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [recurring_assignment]))
    )
    created_assignment_id = uuid4()

    async def flush():
        db.add.call_args.args[0].id = created_assignment_id

    db.flush = AsyncMock(side_effect=flush)
    db.scalar = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    notification_id = uuid4()
    enqueue = AsyncMock(return_value=notification_id)
    dispatch = MagicMock()
    actor_id = uuid4()
    response = SimpleNamespace(
        id=uuid4(),
        path_id=path.id,
        user_id=learner_id,
        source="manual",
        source_ref_id=None,
        assigned_by=None,
        starts_at=None,
        due_at=None,
        status="active",
        created_at=datetime.now(UTC),
        cancelled_at=None,
        completed_at=None,
        user_name=None,
        user_email=None,
    )
    with (
        patch("app.modules.learning_paths.router._get_path", new=AsyncMock(return_value=path)),
        patch(
            "app.modules.learning_paths.router._resolve_audience",
            new=AsyncMock(return_value={learner_id: ("manual", None)}),
        ),
        patch("app.modules.learning_paths.router.sync_assignment_enrollments", new=AsyncMock()),
        patch("app.modules.learning_paths.router.reconcile_learning_path_assignment", new=AsyncMock()),
        patch(
            "app.modules.learning_paths.router.queue_learning_path_assignment_notification",
            new=enqueue,
        ),
        patch(
            "app.modules.enrollments.notification_tasks.deliver_assignment_notification_task.apply_async",
            new=dispatch,
        ),
        patch("app.modules.learning_paths.router._assignment_response", return_value=response),
    ):
        result = await assign_path_audience(
            path.id,
            LearningPathAssignmentAudience(user_ids=[learner_id]),
            db=db,
            user=SimpleNamespace(tenant_id=path.tenant_id, id=actor_id, is_impersonating=False),
        )

    created = db.add.call_args.args[0]
    assert result.added == 1
    assert created is not recurring_assignment
    assert created.source == "manual"
    assert created.recurrence_instance_id is None
    assert recurring_assignment.status == "cancelled"
    assert recurring_assignment.recurrence_instance_id == cycle_id
    enqueue.assert_awaited_once_with(
        db,
        tenant_id=path.tenant_id,
        learning_path_assignment_id=created_assignment_id,
        assigned_by=actor_id,
    )
    dispatch.assert_called_once_with(
        args=[str(path.tenant_id), str(notification_id)],
        kwargs={"notification_kind": "learning_path"},
    )


@pytest.mark.asyncio
async def test_occurrences_readback_serializes_latest_course_and_path_targets():
    now = datetime.now(UTC)
    course_occurrence = SimpleNamespace(
        id=uuid4(), rule_id=uuid4(), user_id=uuid4(), course_id=uuid4(), enrollment_id=uuid4(),
        scheduled_for=now, due_at=now, status="assigned",
    )
    path_occurrence = SimpleNamespace(
        id=uuid4(), rule_id=uuid4(), user_id=uuid4(), path_id=uuid4(), scheduled_for=now,
        due_at=now, completed_at=None, status="active",
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(all=lambda: [(course_occurrence, None)]),
                SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [path_occurrence])),
            ]
        )
    )

    result = await list_latest_occurrences(db=db, user=SimpleNamespace(tenant_id=uuid4()))

    assert {item.target_type for item in result} == {"course", "learning_path"}
    path_result = next(item for item in result if item.target_type == "learning_path")
    assert path_result.course_id is None
    assert path_result.learning_path_id == path_occurrence.path_id


def test_0145_contains_due_identity_and_occurrence_scoped_enrollment_contract():
    migration = (ROOT / "apps/api/alembic/versions/0145_learning_path_recurrence_bridge.py").read_text(encoding="utf-8")
    model = (ROOT / "apps/api/app/models/enrollment.py").read_text(encoding="utf-8")
    assert "down_revision = \"0144\"" in migration
    assert "due_days BETWEEN 0 AND 3650" in migration
    assert "due_days <= cadence_days" in migration
    assert "learning_path_assignment_id" in migration
    assert "uq_enrollments_learning_path_assignment_course" in migration
    assert "ck_enrollments_one_recurrence_identity" in migration
    assert "learning-path enrollment ownership mismatch" in migration
    assert "ForeignKey(\"learning_path_assignments.id\", ondelete=\"RESTRICT\")" in model


def test_0145_op_execute_sends_one_postgresql_command_per_call():
    migration_path = ROOT / "apps/api/alembic/versions/0145_learning_path_recurrence_bridge.py"
    tree = ast.parse(migration_path.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "op"
            and node.func.attr == "execute"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            continue
        sql_without_dollar_body = re.sub(r"\$\$.*?\$\$", "$$body$$", node.args[0].value, flags=re.DOTALL)
        statements = [statement for statement in sql_without_dollar_body.split(";") if statement.strip()]
        if len(statements) > 1:
            offenders.append(node.lineno)
    assert offenders == []
