from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def test_api_fixture_does_not_invent_local_postgresql() -> None:
    fixture = Path(__file__).parents[1] / "conftest.py"
    source = fixture.read_text(encoding="utf-8")

    assert "postgresql+asyncpg://lms:lms_dev_password_2026@localhost" not in source
    assert "database integration requires explicit approved DATABASE_URL" in source


@pytest.mark.asyncio
async def test_http_fixture_resets_security_context_before_every_request(monkeypatch):
    from fastapi import Depends, FastAPI

    from app.core.db import get_db
    from app.main import app as original_app
    from tests import conftest as fixtures

    application = FastAPI()
    db = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock())
    request_session = Depends(get_db)

    @application.get("/fixture-boundary")
    async def boundary(session=request_session):
        return {"resets": session.execute.await_count}

    # Exercise the real fixture override, without application business operations.
    monkeypatch.setattr("app.main.app", application)
    stream = fixtures.client.__wrapped__(db)
    try:
        client = await anext(stream)
        assert (await client.get("/fixture-boundary")).json() == {"resets": 1}
        assert (await client.get("/fixture-boundary")).json() == {"resets": 2}
        for call in db.execute.await_args_list:
            sql = str(call.args[0])
            assert "set_config('app.tenant_id', '', true)" in sql
            assert "set_config('app.user_id', '', true)" in sql
            assert "set_config('app.is_superadmin', 'false', true)" in sql
            assert "set_config('app.auth_lookup', 'false', true)" in sql
            assert "set_config('app.is_impersonating', 'false', true)" in sql
            assert "set_config('app.impersonating_actor_id', '', true)" in sql
        db.commit.assert_not_awaited()
        db.rollback.assert_not_awaited()
    finally:
        await stream.aclose()
    assert not application.dependency_overrides
    assert not original_app.dependency_overrides
