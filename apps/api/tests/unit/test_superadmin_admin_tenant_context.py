from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.admin.superadmin.service import SuperadminService


class _ScalarResult:
    def scalar_one_or_none(self):
        return None


@pytest.mark.asyncio
async def test_sync_user_role_binds_target_tenant_before_rls_query() -> None:
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[object(), _ScalarResult()])
    db.flush = AsyncMock()
    service = SuperadminService(db)
    tenant_id = uuid4()

    await service._sync_user_role(uuid4(), tenant_id, "methodologist")

    statements = [str(call.args[0]) for call in db.execute.await_args_list]
    assert len(statements) == 2
    assert "set_current_tenant" in statements[0]
    assert "FROM user_roles" in statements[1]
    db.add.assert_called_once()
    db.flush.assert_awaited_once()
