"""Regression tests for public kiosk RLS bootstrap."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_public_kiosk_token_establishes_tenant_context():
    from app.modules.users.kiosk_service import establish_public_kiosk_tenant_context

    tenant_id = uuid4()
    lookup = MagicMock()
    lookup.scalar_one_or_none.return_value = tenant_id
    context = MagicMock()
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[lookup, context])

    result = await establish_public_kiosk_tenant_context(db, "opaque-token")

    assert result == tenant_id
    assert db.execute.await_count == 2
    second_params = db.execute.await_args_list[1].args[1]
    assert second_params == {"tenant_id": str(tenant_id)}


@pytest.mark.asyncio
async def test_unknown_public_kiosk_token_does_not_set_context():
    from app.modules.users.kiosk_service import establish_public_kiosk_tenant_context

    lookup = MagicMock()
    lookup.scalar_one_or_none.return_value = None
    db = MagicMock()
    db.execute = AsyncMock(return_value=lookup)

    result = await establish_public_kiosk_tenant_context(db, "unknown-token")

    assert result is None
    db.execute.assert_awaited_once()
