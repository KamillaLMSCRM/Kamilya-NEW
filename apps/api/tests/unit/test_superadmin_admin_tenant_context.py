from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.admin.superadmin.schemas import AdminCreate
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


@pytest.mark.asyncio
async def test_create_admin_without_commit_keeps_transaction_open_for_audit() -> None:
    tenant_id = uuid4()
    existing = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        email="methodologist@example.com",
        telegram_id=None,
        first_name="Before",
        last_name="User",
        role="admin",
        is_active=True,
    )
    db = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    service = SuperadminService(db)
    service._find_existing_user = AsyncMock(return_value=existing)
    service._sync_user_role = AsyncMock()

    await service.create_admin(
        tenant_id,
        AdminCreate(
            email="methodologist@example.com",
            first_name="After",
            last_name="User",
            role="methodologist",
            is_active=True,
            send_invite=False,
        ),
        superadmin_id=uuid4(),
        commit=False,
    )

    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()
    db.refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_admin_refreshes_before_transaction_local_context_commit() -> None:
    events: list[str] = []
    tenant_id = uuid4()
    existing = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        email="methodologist@example.com",
        telegram_id=None,
        first_name="Before",
        last_name="User",
        role="admin",
        is_active=True,
    )
    db = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock(side_effect=lambda: events.append("flush"))
    db.commit = AsyncMock(side_effect=lambda: events.append("commit"))
    db.refresh = AsyncMock(side_effect=lambda _obj: events.append("refresh"))
    service = SuperadminService(db)
    service._find_existing_user = AsyncMock(return_value=existing)
    service._sync_user_role = AsyncMock()

    user, invite = await service.create_admin(
        tenant_id,
        AdminCreate(
            email="methodologist@example.com",
            first_name="After",
            last_name="User",
            role="methodologist",
            is_active=True,
            send_invite=False,
        ),
        superadmin_id=uuid4(),
    )

    assert events == ["flush", "refresh", "commit"]
    assert invite is None
    assert user is existing
    assert user.role == "methodologist"
