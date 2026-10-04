from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.modules.ai.budget import check_and_charge_llm_budget


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _RowResult:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


@pytest.mark.asyncio
async def test_new_month_usage_insert_supplies_required_uuid_primary_key() -> None:
    tenant_id = uuid4()
    db = AsyncMock()
    db.execute.side_effect = [
        _ScalarResult(5000),
        _RowResult((10, 1)),
        _ScalarResult(tenant_id),
    ]

    await check_and_charge_llm_budget(db, str(tenant_id))

    insert_statement, insert_params = db.execute.await_args_list[1].args
    sql = str(insert_statement)
    assert "INSERT INTO tenant_llm_usage (id, tenant_id" in sql
    assert isinstance(insert_params["usage_id"], UUID)
    assert insert_params["tenant_id"] == str(tenant_id)
    assert insert_params["cost"] == 10


@pytest.mark.asyncio
@pytest.mark.parametrize("configured,expected", [(0, 5000), (None, 5000), (2, 2)])
async def test_budget_preserves_legacy_defaults_and_enforces_first_insert(configured, expected):
    tenant_id = uuid4()
    db = AsyncMock()
    current = _ScalarResult(0)
    current.scalar = lambda: 0
    db.execute.side_effect = [_ScalarResult(configured), _RowResult(None), current]
    with pytest.raises(HTTPException) as exc:
        await check_and_charge_llm_budget(db, str(tenant_id), operation="assignment_intent_parse", estimated_cost_cents=1)
    assert exc.value.status_code == 429
    statement, params = db.execute.await_args_list[1].args
    assert params["budget"] == expected
    # Both first-month INSERT and existing-row UPDATE enforce the reservation.
    sql = str(statement)
    assert "WHERE CAST(:cost AS INTEGER) <= CAST(:budget AS INTEGER)" in sql
    assert "SELECT :usage_id, :tenant_id, :month_key, CAST(:cost AS INTEGER), 1" in sql
    assert "WHERE tenant_llm_usage.cost_cents + :cost <= :budget" in sql
