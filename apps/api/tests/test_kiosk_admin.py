"""Regression tests for authenticated kiosk administration."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_create_kiosk_link_keeps_rls_transaction_open():
    from app.modules.users.kiosk_service import create_kiosk_link

    db = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    async def populate_server_defaults():
        link = db.add.call_args.args[0]
        link.created_at = datetime.now(timezone.utc)

    db.flush.side_effect = populate_server_defaults

    result = await create_kiosk_link(
        db,
        tenant_id=uuid4(),
        created_by=uuid4(),
        name="Warehouse kiosk",
        location="Almaty warehouse",
    )

    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()
    db.refresh.assert_not_awaited()
    assert result["name"] == "Warehouse kiosk"
    assert result["kiosk_url"].startswith("https://app.kml.kz/kiosk/")
    assert result["created_at"] is not None


@pytest.mark.asyncio
async def test_admin_can_list_positions_for_kiosk_scope():
    from app.modules.users.kiosk_router import list_kiosk_scope_positions

    tenant_id = uuid4()
    position = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Warehouse trainee",
        department="QA Warehouse",
    )
    rows = MagicMock()
    rows.__iter__.return_value = iter([position])
    db = MagicMock()
    db.execute = AsyncMock(return_value=rows)
    user = SimpleNamespace(tenant_id=tenant_id, role="admin")

    result = await list_kiosk_scope_positions(db=db, user=user)

    assert result == [
        {
            "id": position.id,
            "name": "Warehouse trainee",
            "department": "QA Warehouse",
        }
    ]
