"""Behavior at the public exact-token lookup seam; no live credentials."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.users import invitations_service as service


@pytest.mark.asyncio
@pytest.mark.parametrize("row", [None, SimpleNamespace(status="pending")])
async def test_lookup_scopes_then_clears_exact_bound_token_without_committing(row):
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db = SimpleNamespace(execute=AsyncMock(side_effect=[None, result, None]), commit=AsyncMock())
    token = "literal' OR true --"
    assert await service._lookup_public_invitation(db, token) is row
    calls = db.execute.call_args_list
    assert str(calls[0].args[0]) == "SELECT set_config('app.invitation_token', :token, true)"
    assert calls[0].args[1] == {"token": token}
    assert token not in str(calls[1].args[0])
    assert calls[1].args[0].compile().params == {"token_1": token}
    assert str(calls[2].args[0]) == "SELECT set_config('app.invitation_token', '', true)"
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_both_public_paths_use_shared_scoped_lookup(monkeypatch):
    monkeypatch.setattr(service, "_lookup_public_invitation", AsyncMock(return_value=None))
    db = object()
    result = await service.get_public_invitation(db, "missing")
    assert result["reason_if_invalid"] == "invitation_not_found"
    with pytest.raises(service.HTTPException) as error:
        await service._get_pending_invitation(db, "missing")
    assert error.value.status_code == 404
    assert service._lookup_public_invitation.await_args_list[0].args == (db, "missing")
    assert service._lookup_public_invitation.await_count == 2


@pytest.mark.asyncio
async def test_sql_failure_propagates_for_request_transaction_rollback():
    failure = RuntimeError("synthetic query failure")
    db = SimpleNamespace(execute=AsyncMock(side_effect=[None, failure]), commit=AsyncMock())
    with pytest.raises(RuntimeError, match="synthetic query failure"):
        await service._lookup_public_invitation(db, "synthetic")
    db.commit.assert_not_awaited()
    assert db.execute.await_count == 2


@pytest.fixture
def migration():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/0170_invitation_exact_token_rls.py"
    spec = importlib.util.spec_from_file_location("invitation_migration_contract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_scopes_only_owned_table_and_preserves_tenant_policy(migration, monkeypatch):
    statements = []
    monkeypatch.setattr(
        migration.op, "get_context", lambda: SimpleNamespace(opts={"version_table_schema": "invitation_123456789abc"})
    )
    monkeypatch.setattr(migration.op, "execute", statements.append)
    migration.upgrade()
    assert len(statements) == 3
    assert all('ON "invitation_123456789abc".user_invitations' in sql for sql in statements)
    policy = statements[-1]
    assert "FOR SELECT TO lms_app" in policy
    assert "NULLIF(current_setting('app.tenant_id', true), '') IS NULL" in policy
    assert "token = NULLIF(current_setting('app.invitation_token', true), '')" in policy
    assert "status" not in policy
    assert not any("tenant_isolation" in sql or "GRANT" in sql or "DISABLE" in sql for sql in statements)


def test_migration_rejects_unsafe_schema_and_broad_policy_downgrade(migration, monkeypatch):
    monkeypatch.setattr(
        migration.op, "get_context", lambda: SimpleNamespace(opts={"version_table_schema": "public;unsafe"})
    )
    with pytest.raises(ValueError, match="Unsafe invitation schema"):
        migration.upgrade()
    with pytest.raises(RuntimeError, match="roll-forward only"):
        migration.downgrade()
