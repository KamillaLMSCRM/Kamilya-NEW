"""Regression tests for public kiosk RLS bootstrap."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_public_kiosk_token_establishes_tenant_context():
    from app.modules.users.kiosk_service import establish_public_kiosk_tenant_context

    tenant_id = uuid4()
    token_context = MagicMock()
    lookup = MagicMock()
    lookup.scalar_one_or_none.return_value = tenant_id
    context = MagicMock()
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[token_context, lookup, context])

    result = await establish_public_kiosk_tenant_context(db, "opaque-token")

    assert result == tenant_id
    assert db.execute.await_count == 3
    first_sql = str(db.execute.await_args_list[0].args[0])
    first_params = db.execute.await_args_list[0].args[1]
    assert "app.kiosk_token" in first_sql
    assert first_params == {"token": "opaque-token"}
    lookup_sql = str(db.execute.await_args_list[1].args[0])
    lookup_params = db.execute.await_args_list[1].args[1]
    assert "FROM kiosk_links" in lookup_sql
    assert lookup_params == {"token": "opaque-token"}
    tenant_params = db.execute.await_args_list[2].args[1]
    assert tenant_params == {"tenant_id": str(tenant_id)}


@pytest.mark.asyncio
async def test_unknown_public_kiosk_token_does_not_set_context():
    from app.modules.users.kiosk_service import establish_public_kiosk_tenant_context

    token_context = MagicMock()
    lookup = MagicMock()
    lookup.scalar_one_or_none.return_value = None
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[token_context, lookup])

    result = await establish_public_kiosk_tenant_context(db, "unknown-token")

    assert result is None
    assert db.execute.await_count == 2


def test_public_kiosk_rls_migration_is_token_scoped():
    from pathlib import Path

    source = Path("alembic/versions/0119_public_kiosk_token_rls.py").read_text(
        encoding="utf-8"
    )

    assert "kiosk_links_public_token_lookup" in source
    assert "FOR SELECT TO lms_app" in source
    assert "current_setting('app.kiosk_token', true)" in source
    assert "token = NULLIF" in source
    assert "DROP FUNCTION IF EXISTS lookup_kiosk_tenant_by_token(text)" in source
