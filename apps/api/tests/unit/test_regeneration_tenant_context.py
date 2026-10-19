"""Fresh worker transactions must bind RLS before touching regeneration state."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.ai import router


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", [False, True])
@pytest.mark.parametrize("visible", [False, True])
async def test_regeneration_binds_exact_tenant_before_update(monkeypatch, finish, visible):
    tenant_id = uuid4()
    calls = []
    bound = None

    async def execute(statement, parameters=None):
        nonlocal bound
        sql = str(statement)
        if sql.startswith("SELECT set_current_tenant"):
            bound = parameters["tid"]
            calls.append("context")
            return None
        assert bound == str(tenant_id), "fresh worker transaction has no tenant context"
        assert statement.compile().params["tenant_id_1"] == tenant_id
        calls.append("update")
        return SimpleNamespace(rowcount=int(visible))

    session = MagicMock()
    session.execute = AsyncMock(side_effect=execute)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("app.core.db.async_session_factory", lambda: context)
    if finish:
        result = await router._finish_regeneration_job(session, "owned-job", tenant_id, status="completed")
    else:
        result = await router._set_regeneration_job_state("owned-job", tenant_id, status="running")
    assert result is visible
    assert calls == ["context", "update"]
    if finish and not visible:
        session.rollback.assert_awaited_once()
        session.commit.assert_not_awaited()
    else:
        session.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", [False, True])
async def test_failed_tenant_binding_never_updates_regeneration(monkeypatch, finish):
    from fastapi import HTTPException

    session = MagicMock()
    session.execute = AsyncMock(side_effect=RuntimeError("binding rejected"))
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("app.core.db.async_session_factory", lambda: context)
    with pytest.raises(HTTPException) as error:
        if finish:
            await router._finish_regeneration_job(session, "owned-job", uuid4(), status="completed")
        else:
            await router._set_regeneration_job_state("owned-job", uuid4(), status="running")
    assert error.value.status_code == 503
    session.execute.assert_awaited_once()
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
