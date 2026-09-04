from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import Request, Response

from app.modules.auth.router import logout
from app.modules.auth.schemas import RefreshRequest


@pytest.mark.asyncio
async def test_logout_audits_owner_of_valid_refresh_token():
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    query_result = SimpleNamespace(scalar_one_or_none=lambda: user)
    db = AsyncMock()
    db.execute.return_value = query_result
    token = "valid-refresh-token"
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/logout",
            "headers": [(b"cookie", f"kamilya_refresh={token}".encode())],
            "client": ("127.0.0.1", 1234),
        }
    )
    response = Response()

    with (
        patch(
            "app.modules.auth.router.decode_token",
            return_value={"type": "refresh", "sub": str(user.id)},
        ) as decode,
        patch(
            "app.modules.auth.router.blacklist_refresh_token",
            new=AsyncMock(),
        ) as blacklist,
        patch("app.modules.auth.router.log_action", new=AsyncMock()) as audit,
    ):
        result = await logout(
            RefreshRequest(),
            request,
            response,
            db,
        )

    assert result == {"status": "ok"}
    decode.assert_called_once_with(token)
    blacklist.assert_awaited_once_with(db, token)
    audit.assert_awaited_once()
    assert audit.await_args.args[:4] == (db, user.tenant_id, "logout", "user")
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_logout_clears_cookie_when_refresh_token_is_invalid():
    db = AsyncMock()
    token = "invalid-refresh-token"
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/logout",
            "headers": [(b"cookie", f"kamilya_refresh={token}".encode())],
            "client": ("127.0.0.1", 1234),
        }
    )
    response = Response()

    with patch(
        "app.modules.auth.router.decode_token",
        side_effect=ValueError("malformed"),
    ):
        result = await logout(
            RefreshRequest(),
            request,
            response,
            db,
        )

    assert result == {"status": "ok"}
    assert "kamilya_refresh=" in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_superadmin_logout_uses_platform_audit_scope():
    user = SimpleNamespace(id=uuid4(), tenant_id=None)
    query_result = SimpleNamespace(scalar_one_or_none=lambda: user)
    db = AsyncMock()
    db.execute.return_value = query_result
    response = Response()
    token = "valid-platform-refresh-token"
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/logout",
            "headers": [(b"cookie", f"kamilya_refresh={token}".encode())],
            "client": ("127.0.0.1", 1234),
        }
    )

    with (
        patch(
            "app.modules.auth.router.decode_token",
            return_value={"type": "refresh", "sub": str(user.id), "platform": True},
        ),
        patch("app.modules.auth.router.blacklist_refresh_token", new=AsyncMock()) as blacklist,
        patch("app.modules.auth.router.log_action", new=AsyncMock()) as audit,
    ):
        result = await logout(RefreshRequest(), request, response, db)

    assert result == {"status": "ok"}
    blacklist.assert_awaited_once_with(db, token)
    audit.assert_awaited_once()
    assert audit.await_args.args[:4] == (db, UUID(int=0), "logout", "user")
    db.commit.assert_awaited_once()
