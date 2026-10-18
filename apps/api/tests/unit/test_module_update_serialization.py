"""Async module update must materialize onupdate fields before response validation."""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import MissingGreenlet

from app.modules.lessons.schemas import ModuleResponse, ModuleUpdate
from app.modules.lessons.service import update_module


@pytest.mark.asyncio
async def test_module_update_refreshes_timestamp_before_response():
    now = datetime.now(UTC)
    tenant_id, module_id = uuid4(), uuid4()

    class ExpiredModule:
        id = module_id
        course_id = uuid4()
        title = "Old module"
        description = "Synthetic"
        order_index = 0
        ai_generated = False
        created_at = now
        expired = False

        @property
        def updated_at(self):
            if self.expired:
                raise MissingGreenlet("onupdate timestamp requires explicit async refresh")
            return now

    module = ExpiredModule()
    module.tenant_id = tenant_id
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: module)

    async def flush():
        module.expired = True

    async def refresh(row):
        assert row is module
        module.expired = False

    db.flush.side_effect = flush
    db.refresh.side_effect = refresh
    response = ModuleResponse.model_validate(
        await update_module(db, module_id, tenant_id, ModuleUpdate(title="Renamed module")),
    )
    assert response.title == "Renamed module"
    assert response.updated_at == now
    assert tenant_id in db.execute.await_args.args[0].compile().params.values()
    db.refresh.assert_awaited_once_with(module)
