"""Unit tests for batch_service (B1b).

Mocks the DB and the recompute kernel. Verifies:
  - recompute_position_holders: queries User for holders, runs
    recompute_enrollments once per holder, aggregates.
  - recompute_department_members: queries Position ids in the
    department, then User ids in those positions, then runs
    recompute for each. Empty department is a no-op.
  - apply_rules_for_users: iterates user_ids, calls recompute once
    per user, aggregates.

We mock recompute_enrollments itself (not the DB queries inside it)
because the recompute kernel already has its own dedicated test
suite. The batch tests focus on fan-out + aggregation.
"""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.positions.assignment_service import RecomputeResult
from app.modules.positions.batch_service import (
    apply_rules_for_users,
    recompute_department_members,
    recompute_position_holders,
)


def _result_mock(added=0, removed=0, skipped_manual=0, protected_completed=0) -> RecomputeResult:
    return RecomputeResult(
        added=added,
        removed=removed,
        skipped_manual=skipped_manual,
        protected_completed=protected_completed,
    )


def _mock_select_chain(db: AsyncMock, result_rows: list) -> None:
    """Make db.execute() return a result whose .scalars().all() returns result_rows.

    Use this for batch_service / recompute tests. The pattern is
    `holder_result = await db.execute(...)` then
    `holder_result.scalars().all()` (the production code path).
    """
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=result_rows)
    db.execute = AsyncMock(return_value=MagicMock(scalars=scalars))


# ── 1. recompute_position_holders: fan-out + aggregate ──


@pytest.mark.asyncio
async def test_recompute_position_holders_runs_recompute_per_holder():
    db = AsyncMock()
    tenant_id = uuid4()
    position_id = uuid4()
    user_a, user_b = uuid4(), uuid4()

    # Inline result object so .scalars() returns our mock that has .all()
    result_obj = MagicMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=[(user_a,), (user_b,)])
    result_obj.scalars = MagicMock(return_value=scalars)
    db.execute = AsyncMock(return_value=result_obj)

    async def fake_recompute(d, user_id):
        if user_id == user_a:
            return _result_mock(added=2, removed=1)
        return _result_mock(added=1, removed=0)
    with patch("app.modules.positions.batch_service.recompute_enrollments", side_effect=fake_recompute):
        result = await recompute_position_holders(db, position_id, tenant_id)

    assert result.users_processed == 2
    assert result.added == 3
    assert result.removed == 1


@pytest.mark.asyncio
async def test_recompute_position_holders_empty_position():
    db = AsyncMock()
    _mock_select_chain(db, [])

    with patch("app.modules.positions.batch_service.recompute_enrollments") as fake:
        result = await recompute_position_holders(db, uuid4(), uuid4())

    assert result.users_processed == 0
    assert result.added == 0
    fake.assert_not_called()


# ── 2. recompute_department_members: fan-out via positions ──


@pytest.mark.asyncio
async def test_recompute_department_members_walks_position_to_users():
    db = AsyncMock()
    department_id = uuid4()
    tenant_id = uuid4()
    pos_a, pos_b = uuid4(), uuid4()
    user_a, user_b = uuid4(), uuid4()

    # First execute: positions in department → 2 positions
    scalars_first = MagicMock()
    scalars_first.all = MagicMock(return_value=[(pos_a,), (pos_b,)])
    result_first = MagicMock()
    result_first.scalars = MagicMock(return_value=scalars_first)

    # Second execute: users in those positions → 2 users
    scalars_second = MagicMock()
    scalars_second.all = MagicMock(return_value=[(user_a,), (user_b,)])
    result_second = MagicMock()
    result_second.scalars = MagicMock(return_value=scalars_second)

    db.execute = AsyncMock(side_effect=[result_first, result_second])

    async def fake_recompute(d, user_id):
        return _result_mock(added=1)
    with patch("app.modules.positions.batch_service.recompute_enrollments", side_effect=fake_recompute):
        result = await recompute_department_members(db, department_id, tenant_id)

    assert result.users_processed == 2
    assert result.added == 2


@pytest.mark.asyncio
async def test_recompute_department_members_empty_department():
    """Department with no positions is a no-op (no second query)."""
    db = AsyncMock()
    _mock_select_chain(db, [])

    with patch("app.modules.positions.batch_service.recompute_enrollments") as fake:
        result = await recompute_department_members(db, uuid4(), uuid4())

    assert result.users_processed == 0
    # Only one execute() was made (the position query). No second query.
    assert db.execute.call_count == 1
    fake.assert_not_called()


# ── 3. apply_rules_for_users: simple fan-out + aggregate ──


@pytest.mark.asyncio
async def test_apply_rules_for_users_runs_per_user():
    db = AsyncMock()
    user_a, user_b, user_c = uuid4(), uuid4(), uuid4()

    async def fake_recompute(d, user_id):
        if user_id in (user_a, user_b):
            return _result_mock(added=2)
        return _result_mock(added=0, removed=1)
    with patch("app.modules.positions.batch_service.recompute_enrollments", side_effect=fake_recompute):
        result = await apply_rules_for_users(db, [user_a, user_b, user_c])

    assert result.users_processed == 3
    assert result.added == 4
    assert result.removed == 1


@pytest.mark.asyncio
async def test_apply_rules_for_users_empty_list():
    db = AsyncMock()
    with patch("app.modules.positions.batch_service.recompute_enrollments") as fake:
        result = await apply_rules_for_users(db, [])
    assert result.users_processed == 0
    fake.assert_not_called()
