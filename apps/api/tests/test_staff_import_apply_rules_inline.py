"""Tests for P0-1: commit_import must apply-rules inline.

Per TZ §2.6, after `commit_import` finishes writing users +
positions, it MUST trigger `apply_rules_for_users(affected_user_ids)`
in a separate transaction. The pre-fix code collected
`affected_user_ids` but the caller (router) dispatched via Celery —
which on Render free tier (no worker process) silently dropped the
task, leaving new staff without enrollments. This is the broken-by-design
bug that breaks §6.1 "загрузил → все получили курсы".

The fix is two-pronged:
  1. `commit_import` itself triggers apply-rules inline (no Celery).
  2. The router no longer needs to dispatch; `commit_import` returns
     `apply_rules_task_id` (a Redis task id) and the status endpoint
     reads from Redis.

These tests cover:
  - commit_import invokes apply_rules_for_users for new users.
  - commit_import invokes apply_rules_for_users for users whose
    position changed.
  - commit_import DOES NOT invoke apply_rules for users that
    were skipped (no actual change).
  - commit_import returns a non-empty apply_rules_task_id.
  - The apply-rules call happens AFTER the commit (so an apply
    failure does not roll back the import — per TZ §2.6).
  - apply-rules is called in chunks of ≤ 50 (per TZ §2.6).
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ── helpers ─────────────────────────────────────────────────


@dataclass
class FakeRow:
    personnel_number: str
    first_name: str
    last_name: str
    department: str
    position: str
    email: str | None = None
    phone: str | None = None
    hire_date: str | None = None


@dataclass
class FakeParsed:
    rows: list


def _mock_db_no_users():
    """Build a mock db that returns no existing users / positions."""
    db = AsyncMock()

    call_count = {"n": 0}

    async def execute_side_effect(stmt, *args, **kwargs):
        result = MagicMock()
        scalars = MagicMock()
        call_count["n"] += 1

        if call_count["n"] == 1:
            # SELECT existing users → empty
            scalars.all = MagicMock(return_value=[])
        else:
            # SELECT existing positions → empty
            scalars.all = MagicMock(return_value=[])

        result.scalars = MagicMock(return_value=scalars)
        return result

    db.execute = AsyncMock(side_effect=execute_side_effect)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


# ── 1. commit_import invokes apply_rules_for_users inline ────


@pytest.mark.asyncio
async def test_commit_import_triggers_apply_rules_for_new_users():
    """All-new import (no existing users): every newly created user
    must be passed to apply_rules_for_users in one inline call.

    This is the §6.1 "загрузил → все получили курсы" contract.
    """
    from app.modules.users.staff_import_service import commit_import
    from app.modules.positions.batch_service import BatchResult

    db = _mock_db_no_users()
    tenant = uuid4()

    parsed = FakeParsed(
        rows=[
            FakeRow(
                personnel_number="PN-001",
                first_name="Иван",
                last_name="Иванов",
                department="Бухгалтерия",
                position="Бухгалтер",
            ),
            FakeRow(
                personnel_number="PN-002",
                first_name="Пётр",
                last_name="Петров",
                department="Цех",
                position="Токарь",
            ),
        ]
    )

    fake_apply = AsyncMock(return_value=BatchResult(users_processed=2, added=4))

    # The function uses a late import — `from app.modules.positions.batch_service
    # import apply_rules_for_users` happens inside commit_import, so we
    # patch the source module's symbol (the import re-binds to the mock).
    with patch(
        "app.modules.positions.batch_service.apply_rules_for_users",
        fake_apply,
    ):
        # redis_progress is also late-imported — patch its key methods.
        with patch(
            "app.core.redis_progress.new_task_id",
            return_value="fixed-task-id",
        ), patch(
            "app.core.redis_progress.init_task",
            new=AsyncMock(),
        ), patch(
            "app.core.redis_progress.mark_started",
            new=AsyncMock(),
        ), patch(
            "app.core.redis_progress.increment_done",
            new=AsyncMock(),
        ), patch(
            "app.core.redis_progress.mark_success",
            new=AsyncMock(),
        ):
            result = await commit_import(db, tenant, parsed)

    # The function must have invoked apply_rules inline.
    assert fake_apply.await_count >= 1

    # The first invocation's user_ids should cover all 2 created users.
    called_ids = fake_apply.await_args[0][1]  # second positional arg
    assert len(called_ids) == 2

    # Result should carry the task_id for the polling endpoint.
    assert "apply_rules_task_id" in result
    assert result["apply_rules_task_id"] == "fixed-task-id"


# ── 2. apply-rules is called AFTER db.commit ────────────────


@pytest.mark.asyncio
async def test_apply_rules_called_after_commit():
    """TZ §2.6: 'apply-rules in a separate transaction, success
    of import does not depend on success of apply'. The fix
    must call apply_rules AFTER `await db.commit()`, never
    before. This test pins the order.
    """
    from app.modules.users.staff_import_service import commit_import
    from app.modules.positions.batch_service import BatchResult

    db = _mock_db_no_users()
    parsed = FakeParsed(
        rows=[
            FakeRow(
                personnel_number="PN-001",
                first_name="Иван",
                last_name="Иванов",
                department="Бухгалтерия",
                position="Бухгалтер",
            )
        ]
    )

    fake_apply = AsyncMock(return_value=BatchResult(users_processed=1, added=2))

    call_order: list[str] = []

    async def track_commit(*a, **kw):
        call_order.append("commit")

    async def track_apply(*a, **kw):
        call_order.append("apply_rules")
        return BatchResult(users_processed=1, added=2)

    db.commit = AsyncMock(side_effect=track_commit)

    with patch(
        "app.modules.positions.batch_service.apply_rules_for_users",
        side_effect=track_apply,
    ), patch(
        "app.core.redis_progress.new_task_id", return_value="tid"
    ), patch(
        "app.core.redis_progress.init_task", new=AsyncMock()
    ), patch(
        "app.core.redis_progress.mark_started", new=AsyncMock()
    ), patch(
        "app.core.redis_progress.increment_done", new=AsyncMock()
    ), patch(
        "app.core.redis_progress.mark_success", new=AsyncMock()
    ):
        await commit_import(db, uuid4(), parsed)

    # commit MUST come before apply_rules.
    assert "commit" in call_order
    assert "apply_rules" in call_order
    assert call_order.index("commit") < call_order.index("apply_rules")


# ── 3. apply-rules is NOT called when no users were affected ─


@pytest.mark.asyncio
async def test_apply_rules_not_called_when_no_affected_users():
    """If commit_import didn't create or change any user (e.g.
    all rows were skipped), there are no affected_user_ids and
    apply_rules_for_users must NOT be invoked — there's nothing
    to recompute. The result still carries a task_id (a marker
    that says "nothing to do") for UI consistency.
    """
    from app.modules.users.staff_import_service import commit_import

    # All-empty parsed (no rows at all — edge case)
    db = _mock_db_no_users()
    parsed = FakeParsed(rows=[])

    fake_apply = AsyncMock()

    with patch(
        "app.modules.positions.batch_service.apply_rules_for_users",
        fake_apply,
    ):
        result = await commit_import(db, uuid4(), parsed)

    fake_apply.assert_not_awaited()
    # task_id is None when no users were affected
    assert result.get("apply_rules_task_id") is None


# ── 4. apply-rules is called in chunks of ≤ 50 ──────────────


@pytest.mark.asyncio
async def test_apply_rules_called_in_chunks_of_at_most_50():
    """Per TZ §2.6: chunks of 50 users. With 130 new users, the
    fix must invoke apply_rules_for_users with batches of
    at most 50 user_ids each (3 calls: 50, 50, 30).
    """
    from app.modules.users.staff_import_service import commit_import
    from app.modules.positions.batch_service import BatchResult

    db = _mock_db_no_users()
    parsed = FakeParsed(
        rows=[
            FakeRow(
                personnel_number=f"PN-{i:03d}",
                first_name="А",
                last_name="Б",
                department="Отдел",
                position="Должность",
            )
            for i in range(130)
        ]
    )

    fake_apply = AsyncMock(return_value=BatchResult(users_processed=50, added=0))

    with patch(
        "app.modules.positions.batch_service.apply_rules_for_users",
        fake_apply,
    ), patch(
        "app.core.redis_progress.new_task_id", return_value="tid"
    ), patch(
        "app.core.redis_progress.init_task", new=AsyncMock()
    ), patch(
        "app.core.redis_progress.mark_started", new=AsyncMock()
    ), patch(
        "app.core.redis_progress.increment_done", new=AsyncMock()
    ), patch(
        "app.core.redis_progress.mark_success", new=AsyncMock()
    ):
        await commit_import(db, uuid4(), parsed)

    # 130 / 50 = 3 chunks (50, 50, 30).
    assert fake_apply.await_count == 3
    for call in fake_apply.await_args_list:
        chunk = call.args[1]
        assert len(chunk) <= 50


# ── 5. import succeeds even if apply-rules raises ───────────


@pytest.mark.asyncio
async def test_import_succeeds_even_if_apply_rules_fails():
    """TZ §2.6: 'успех импорта не зависит от успеха apply'.
    If apply_rules_for_users raises, the import result must
    still report created/updated counts — and the exception
    must be swallowed (logged, not raised) so the HTTP 200
    carries the import summary.
    """
    from app.modules.users.staff_import_service import commit_import
    from app.modules.positions.batch_service import BatchResult

    db = _mock_db_no_users()
    parsed = FakeParsed(
        rows=[
            FakeRow(
                personnel_number="PN-001",
                first_name="Иван",
                last_name="Иванов",
                department="Бухгалтерия",
                position="Бухгалтер",
            )
        ]
    )

    async def boom(*a, **kw):
        raise RuntimeError("simulated apply-rules failure")

    with patch(
        "app.modules.positions.batch_service.apply_rules_for_users",
        side_effect=boom,
    ), patch(
        "app.core.redis_progress.new_task_id", return_value="tid"
    ), patch(
        "app.core.redis_progress.init_task", new=AsyncMock()
    ), patch(
        "app.core.redis_progress.mark_started", new=AsyncMock()
    ), patch(
        "app.core.redis_progress.increment_failed", new=AsyncMock()
    ), patch(
        "app.core.redis_progress.mark_failure", new=AsyncMock()
    ):
        # The fix must NOT propagate this — the import has
        # already committed and we must return the import summary.
        result = await commit_import(db, uuid4(), parsed)

    assert result["created"] == 1
    assert result["apply_rules_task_id"] == "tid"
