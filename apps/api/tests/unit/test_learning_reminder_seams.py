from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.learning_cycles import router as cycle_router
from app.modules.learning_cycles import service as cycle_service
from app.modules.learning_cycles.schemas import RuleCreate, RuleUpdate


class QueueDb:
    def __init__(self) -> None:
        self.flushes = 0
        self.executions: list[tuple[object, dict[str, object]]] = []
        self.commits = 0

    async def flush(self) -> None:
        self.flushes += 1

    async def execute(self, statement: object, params: dict[str, object]):
        self.executions.append((statement, params))

    async def commit(self) -> None:
        self.commits += 1


def _course_rule_create() -> RuleCreate:
    return RuleCreate(course_id=uuid4(), user_id=uuid4(), cadence_days=14, due_days=3)


def test_rule_schemas_default_to_opt_out_and_enforce_reminder_lead_bounds():
    create = _course_rule_create()
    update = RuleUpdate()

    assert create.reminder_enabled is False
    assert create.reminder_days_before_due == 1
    assert update.reminder_enabled is None
    assert update.reminder_days_before_due is None
    for value in (0, 31):
        with pytest.raises(ValidationError):
            RuleCreate(course_id=uuid4(), user_id=uuid4(), cadence_days=14, due_days=3, reminder_days_before_due=value)
        with pytest.raises(ValidationError):
            RuleUpdate(reminder_days_before_due=value)


@pytest.mark.asyncio
async def test_patch_updates_reminder_fields_without_changing_path_cadence_or_due(monkeypatch):
    rule = SimpleNamespace(
        id=uuid4(),
        learning_path_id=uuid4(),
        cadence_days=14,
        due_days=3,
        reminder_enabled=False,
        reminder_days_before_due=1,
    )

    async def owned_rule(_db, _rule_id, _tenant_id):
        return rule

    monkeypatch.setattr(cycle_router, "_owned_rule", owned_rule)
    result = await cycle_router.update_rule(
        rule.id,
        RuleUpdate(reminder_enabled=True, reminder_days_before_due=5),
        db=object(),
        user=SimpleNamespace(tenant_id=uuid4()),
    )

    assert result is rule
    assert (rule.reminder_enabled, rule.reminder_days_before_due) == (True, 5)
    assert (rule.cadence_days, rule.due_days) == (14, 3)


@pytest.mark.asyncio
async def test_path_cadence_guard_remains_active_when_patch_changes_cadence(monkeypatch):
    rule = SimpleNamespace(learning_path_id=uuid4(), cadence_days=14, due_days=3)

    async def owned_rule(_db, _rule_id, _tenant_id):
        return rule

    monkeypatch.setattr(cycle_router, "_owned_rule", owned_rule)
    with pytest.raises(HTTPException) as exc_info:
        await cycle_router.update_rule(
            uuid4(), RuleUpdate(cadence_days=21), db=object(), user=SimpleNamespace(tenant_id=uuid4())
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_path_rule_create_preserves_omitted_reminder_opt_in_and_applies_explicit_values(monkeypatch):
    tenant_id = uuid4()
    path = SimpleNamespace(id=uuid4(), recurrence_mode="fixed_interval_after_completion")
    rule = SimpleNamespace(reminder_enabled=True, reminder_days_before_due=3)

    class PathDb:
        async def scalar(self, _statement):
            return path

    async def reconcile(_db, *, path, user_id, created_by):
        assert path.id
        assert user_id
        assert created_by
        return SimpleNamespace(rule=rule)

    monkeypatch.setattr(cycle_router, "reconcile_learning_path_assignment", reconcile)
    user = SimpleNamespace(tenant_id=tenant_id, id=uuid4())

    omitted = RuleCreate(learning_path_id=path.id, user_id=uuid4())
    assert omitted.model_fields_set == {"learning_path_id", "user_id"}
    assert await cycle_router.create_rule(omitted, db=PathDb(), user=user) is rule
    assert (rule.reminder_enabled, rule.reminder_days_before_due) == (True, 3)

    explicit = RuleCreate(learning_path_id=path.id, user_id=uuid4(), reminder_enabled=False, reminder_days_before_due=7)
    assert await cycle_router.create_rule(explicit, db=PathDb(), user=user) is rule
    assert (rule.reminder_enabled, rule.reminder_days_before_due) == (False, 7)


@pytest.mark.asyncio
async def test_disabled_reminder_enqueue_performs_no_flush_sql_or_commit(monkeypatch):
    db = QueueDb()
    monkeypatch.setattr(cycle_service, "get_settings", lambda: SimpleNamespace(LEARNING_REMINDERS_ENABLED=False))

    await cycle_service._queue_reminder(db, uuid4(), course_id=uuid4())

    assert db.flushes == 0
    assert db.executions == []
    assert db.commits == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(("keyword", "target_parameter"), [("course_id", "course"), ("path_id", "path")])
async def test_enabled_reminder_enqueue_flushes_and_executes_in_caller_transaction(monkeypatch, keyword, target_parameter):
    db = QueueDb()
    tenant_id = uuid4()
    target_id = uuid4()
    monkeypatch.setattr(cycle_service, "get_settings", lambda: SimpleNamespace(LEARNING_REMINDERS_ENABLED=True))

    await cycle_service._queue_reminder(db, tenant_id, **{keyword: target_id})

    assert db.flushes == 1
    assert db.commits == 0
    assert len(db.executions) == 1
    _statement, params = db.executions[0]
    assert params == {"tid": tenant_id, "course": target_id if target_parameter == "course" else None, "path": target_id if target_parameter == "path" else None}


class StatusRows:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def mappings(self) -> StatusRows:
        return self

    def __iter__(self):
        return iter(self.rows)


class StatusDb:
    def __init__(self) -> None:
        self.executed = False
        self.params: dict[str, object] | None = None

    async def execute(self, _statement, params):
        self.executed = True
        self.params = params
        return StatusRows(
            [{"id": uuid4(), "status": "queued", "attempt_count": 0, "scheduled_at": "safe", "delivered_at": None, "last_error_category": None}]
        )


@pytest.mark.asyncio
async def test_reminder_statuses_uses_owned_rule_before_safe_status_query(monkeypatch):
    calls: list[str] = []
    tenant_id = uuid4()
    rule_id = uuid4()
    db = StatusDb()

    async def owned_rule(_db, owned_rule_id, owned_tenant_id):
        calls.append("owned")
        assert (owned_rule_id, owned_tenant_id) == (rule_id, tenant_id)
        assert db.executed is False
        return SimpleNamespace(id=rule_id)

    monkeypatch.setattr(cycle_router, "_owned_rule", owned_rule)
    result = await cycle_router.reminder_statuses(rule_id, db=db, user=SimpleNamespace(tenant_id=tenant_id))

    assert calls == ["owned"]
    assert db.params == {"tenant_id": tenant_id, "rule_id": rule_id}
    assert set(result[0]) == {"id", "status", "attempt_count", "scheduled_at", "delivered_at", "last_error_category"}
    assert not ({"email", "claim_token", "payload_hash", "provider_message_id"} & set(result[0]))
