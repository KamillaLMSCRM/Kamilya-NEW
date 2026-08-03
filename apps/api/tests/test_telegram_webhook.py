"""Smoke tests for the Telegram bot webhook.

These exist because two consecutive deploys broke the bot:
  - 821c7bc inverted resolution order → tenant candidates now reach
    user_data construction, which crashed on user.tenant (no such
    relationship) and then on UUID being non-JSON-serialisable.
  - The old happy path (superadmin candidate, tenant_id=None) hid
    both bugs because the failing branches were skipped.

These tests pin the three paths the webhook must NOT 500 on, and
exercise the REAL auth_sessions.verify_code (with Redis mocked as
an in-memory dict) — not a mock of verify_code itself. Otherwise the
tests pass on broken code.
"""
from __future__ import annotations

import json as _json
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import RateLimitMiddleware
from app.main import app
from app.modules.auth import auth_sessions
from app.modules.auth.auth_sessions import (
    AuthSessionStoreUnavailableError,
    _dumps,
    _memory_store,
)

WEBHOOK_HEADERS = {
    "X-Telegram-Bot-Api-Secret-Token": "test-telegram-webhook-secret"
}


# --- shared rate limit disabler (matches existing test_integration.py) ---
def _disable_rate_limit():
    from unittest import mock

    async def fake_dispatch(self, request, call_next):
        response = await call_next(request)
        return response

    return mock.patch.object(RateLimitMiddleware, "dispatch", fake_dispatch)


def _set_telegram_integration(monkeypatch, enabled: bool) -> None:
    from app.modules.auth.telegram import settings

    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "test-bot-token" if enabled else "")
    monkeypatch.setattr(
        settings,
        "TELEGRAM_WEBHOOK_SECRET",
        "test-telegram-webhook-secret" if enabled else "",
    )


def _telegram_update(text: str, telegram_id: int = 349746594) -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": 0,
            "chat": {"id": telegram_id, "type": "private"},
            "from": {"id": telegram_id, "is_bot": False, "first_name": "X"},
            "text": text,
        },
    }


def _fake_user(*, tenant_id, role="admin", telegram_id=349746594):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        telegram_id=telegram_id,
        first_name="Askar",
        last_name="Amirkhanov",
        role=role,
        is_active=True,
    )


def _fake_tenant_row(tenant_id, *, slug="kamilya-demo", name="Kamilya Demo"):
    return SimpleNamespace(
        id=tenant_id,
        name=name,
        slug=slug,
        is_demo=False,
        plan="enterprise",
    )


class FakeRedis:
    """Minimal Redis stub for the auth-session lifecycle scripts."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def setex(self, key, ttl, value):
        self.store[key] = value

    async def set(self, key, value, *, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def eval(self, script, numkeys, *args):
        keys = args[:numkeys]
        argv = args[numkeys:]

        if "kamilya-auth-allocate-v1" in script:
            pending_key, verified_key = keys
            if pending_key in self.store or verified_key in self.store:
                return 0
            self.store[pending_key] = argv[0]
            return 1

        if "kamilya-auth-verify-v1" in script:
            pending_key, verified_key = keys
            if verified_key in self.store:
                return 2
            if pending_key not in self.store:
                return 0
            self.store[verified_key] = argv[0]
            self.store.pop(pending_key, None)
            return 1

        if "kamilya-auth-consume-v1" in script:
            pending_key, verified_key = keys
            if verified_key in self.store:
                return [1, self.store.pop(verified_key)]
            if pending_key in self.store:
                return [0, "pending"]
            return [0, "not_found"]

        raise AssertionError("Unexpected Lua script")

    async def delete(self, key):
        self.store.pop(key, None)

    async def keys(self, pattern):
        # pattern like "auth:code:*"
        import fnmatch
        return [k for k in self.store if fnmatch.fnmatchcase(k, pattern)]

    async def ping(self):
        return True


class FailingRedis(FakeRedis):
    async def eval(self, script, numkeys, *args):
        raise RuntimeError("max requests limit exceeded")

    async def get(self, key):
        raise RuntimeError("max requests limit exceeded")

    async def setex(self, key, ttl, value):
        raise RuntimeError("max requests limit exceeded")

    async def set(self, key, value, *, ex=None, nx=False):
        raise RuntimeError("max requests limit exceeded")

    async def delete(self, key):
        raise RuntimeError("max requests limit exceeded")


@pytest.fixture
def client(monkeypatch):
    _set_telegram_integration(monkeypatch, True)
    c = TestClient(app)
    with _disable_rate_limit():
        yield c


@pytest.fixture(autouse=True)
def reset_auth_sessions():
    """Wipe in-memory store and the cached Redis client between tests."""
    _memory_store.clear()
    auth_sessions._redis_client = None
    yield
    _memory_store.clear()
    auth_sessions._redis_client = None


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def patched_redis(fake_redis):
    """Patch auth_sessions._get_redis to return our fake. Tests using
    this fixture can drive verify_code end-to-end without touching
    real Redis."""
    async def _get():
        return fake_redis
    with patch.object(auth_sessions, "_get_redis", _get):
        yield fake_redis


class TestTelegramWebhook:
    def test_capabilities_expose_only_safe_enabled_flag(self, client, monkeypatch):
        _set_telegram_integration(monkeypatch, True)

        response = client.get("/api/v1/auth/capabilities")

        assert response.status_code == 200
        assert response.json() == {"telegram_login_enabled": True}
        assert "test-bot-token" not in response.text
        assert "test-telegram-webhook-secret" not in response.text

    def test_capabilities_hide_telegram_when_incomplete(self, client, monkeypatch):
        _set_telegram_integration(monkeypatch, False)
        from app.modules.auth.telegram import settings
        monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "test-bot-token")

        response = client.get("/api/v1/auth/capabilities")

        assert response.status_code == 200
        assert response.json() == {"telegram_login_enabled": False}

    def test_generate_code_never_logs_one_time_code(self, client, caplog, monkeypatch):
        _set_telegram_integration(monkeypatch, True)
        generated_code = "123456"
        with patch(
            "app.modules.auth.router.generate_auth_code",
            new=AsyncMock(return_value=(generated_code, 300)),
        ):
            with caplog.at_level(logging.INFO):
                response = client.post("/api/v1/auth/generate-code")

        assert response.status_code == 200
        assert response.json()["code"] == generated_code
        assert generated_code not in caplog.text

    def test_generate_code_returns_503_when_session_store_is_unavailable(self, client, monkeypatch):
        _set_telegram_integration(monkeypatch, True)
        with patch(
            "app.modules.auth.router.generate_auth_code",
            new=AsyncMock(side_effect=AuthSessionStoreUnavailableError),
        ):
            response = client.post("/api/v1/auth/generate-code")

        assert response.status_code == 503
        assert response.json()["message"] == "Authentication service temporarily unavailable"

    def test_check_code_returns_503_when_session_store_is_unavailable(self, client):
        with patch(
            "app.modules.auth.router.check_code",
            new=AsyncMock(return_value={"verified": False, "error": "unavailable"}),
        ):
            response = client.post(
                "/api/v1/auth/check-code",
                json={"code": "123456"},
            )

        assert response.status_code == 503
        assert response.json() == {
            "verified": False,
            "error": "Authentication service temporarily unavailable",
        }

    def test_generate_code_fails_closed_when_telegram_is_disabled(
        self, client, caplog, monkeypatch
    ):
        _set_telegram_integration(monkeypatch, False)
        from app.modules.auth.telegram import settings
        monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "test-bot-token")
        generated_code = "654321"
        generator = AsyncMock(return_value=(generated_code, 300))

        with patch("app.modules.auth.router.generate_auth_code", new=generator):
            with caplog.at_level(logging.INFO):
                response = client.post("/api/v1/auth/generate-code")

        assert response.status_code == 503
        assert response.json()["details"]["code"] == "telegram_unavailable"
        assert generated_code not in caplog.text
        generator.assert_not_awaited()

    def test_webhook_does_not_log_raw_message_or_code(
        self, client, caplog, capsys, monkeypatch
    ):
        _set_telegram_integration(monkeypatch, True)
        raw_message = "private Telegram message 654321"

        with patch(
            "app.modules.auth.telegram.send_telegram_message",
            AsyncMock(return_value=None),
        ):
            with caplog.at_level(logging.INFO):
                response = client.post(
                    "/api/v1/telegram/webhook",
                    json=_telegram_update(raw_message),
                    headers=WEBHOOK_HEADERS,
                )

        captured = capsys.readouterr()
        assert response.status_code == 200
        assert raw_message not in caplog.text
        assert raw_message not in captured.out + captured.err
        assert "654321" not in caplog.text
        assert "654321" not in captured.out + captured.err

    @pytest.mark.asyncio
    async def test_auth_sessions_fall_back_when_redis_operations_fail(self):
        async def _get():
            return FailingRedis()

        with patch.object(auth_sessions, "_get_redis", _get):
            code, expires_in = await auth_sessions.generate_auth_code()
            assert len(code) == 6
            assert expires_in == 300
            assert code in _memory_store

            verified = await auth_sessions.verify_code(
                code,
                "349746594",
                {"user_id": str(uuid4()), "telegram_id": "349746594"},
            )
            assert verified is True

            result = await auth_sessions.check_code(code)
            assert result["verified"] is True
            assert result["user"]["telegram_id"] == "349746594"

    def test_start_command_does_not_500(self, client):
        """The /start branch responds 200 before touching the DB."""
        resp = client.post(
            "/api/v1/telegram/webhook",
            json=_telegram_update("/start"),
            headers=WEBHOOK_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_unknown_six_digit_code_replies_not_bound(self, client):
        """When the candidate lookup returns no user, bot replies with
        the 'Telegram not bound' message rather than 500."""
        fake_result = MagicMock()
        fake_result.scalars.return_value.all.return_value = []
        fake_db = AsyncMock()
        fake_db.execute.return_value = fake_result

        async def fake_get_db_override():
            yield fake_db

        from app.core.db import get_db
        app.dependency_overrides[get_db] = fake_get_db_override
        try:
            with patch(
                "app.modules.auth.telegram.send_telegram_message",
                AsyncMock(return_value=None),
            ) as send:
                resp = client.post(
                    "/api/v1/telegram/webhook",
                    json=_telegram_update("123456"),
                    headers=WEBHOOK_HEADERS,
                )
                assert resp.status_code == 200
                assert send.call_count == 1
                msg = send.call_args.args[1]
                assert "привязан" in msg or "⚠" in msg
        finally:
            app.dependency_overrides.clear()

    def test_tenant_admin_candidate_does_not_crash(
        self, client, patched_redis
    ):
        """The regression test: a tenant admin candidate reaches
        verify_code with user_data containing a UUID tenant_id.
        Plain json.dumps would raise TypeError. _dumps() must
        serialise it.

        We seed an auth session (mimicking /generate-code) so
        verify_code has something to look up, then drive the
        webhook with that code and capture the user_data the
        handler passed in.
        """
        import asyncio

        async def drive():
            # Pre-seed the auth session with a known code so verify_code
            # finds it.
            tenant_id = uuid4()
            code = "777777"
            await auth_sessions.verify_code.__wrapped__ if False else None  # noqa
            # We can't easily call verify_code before the candidate is
            # known (chicken-and-egg), so seed via the in-memory store
            # directly + then patch setex to write to fake_redis.

            user = _fake_user(tenant_id=tenant_id, role="admin")
            tenant_row = _fake_tenant_row(tenant_id)

            # Mock DB:
            user_q = MagicMock()
            user_q.scalars.return_value.all.return_value = [user]
            role_q = MagicMock()
            role_q.scalar_one_or_none.return_value = None
            tenant_q = MagicMock()
            tenant_q.scalar_one_or_none.return_value = tenant_row

            fake_db = AsyncMock()
            fake_db.execute.side_effect = [user_q, role_q, tenant_q]

            async def fake_get_db_override():
                yield fake_db

            from app.core.db import get_db
            app.dependency_overrides[get_db] = fake_get_db_override

            # Pre-create the pending auth session under the code we send.
            import time
            patched_redis.store[auth_sessions._pending_key(code)] = _dumps({
                "code": code,
                "created_at": time.time(),
                "expires_at": time.time() + 300,
                "verified": False,
                "user_data": None,
            })

            try:
                with patch(
                    "app.modules.auth.telegram.send_telegram_message",
                    AsyncMock(return_value=None),
                ):
                    resp = client.post(
                        "/api/v1/telegram/webhook",
                        json=_telegram_update(code),
                        headers=WEBHOOK_HEADERS,
                    )
            finally:
                app.dependency_overrides.clear()

            assert resp.status_code == 200, resp.text
            # If the broken json.dumps is back, the session would still
            # be in fake_redis but verify_code would have raised; the
            # HTTP path would 500. The 200 + the fact that the session
            # was rewritten with user_data is the assertion.

            assert auth_sessions._pending_key(code) not in patched_redis.store
            stored = patched_redis.store.get(auth_sessions._verified_key(code))
            assert stored is not None
            # The session was rewritten with verified=True + user_data.
            assert '"verified": true' in stored or '"verified":true' in stored
            # The user_data was serialised. tenant_id in the stored
            # session must be a string (UUID-safe encoder), not the
            # literal 'UUID("...")' or omitted.
            assert '"tenant_id"' in stored

        asyncio.run(drive())


class TestSessionEncoder:
    """Direct unit tests for the UUID-aware encoder."""

    def test_uuid_serialised_as_string(self):
        out = _dumps({"tenant_id": UUID("12345678-1234-5678-1234-567812345678")})
        parsed = _json.loads(out)
        assert parsed["tenant_id"] == "12345678-1234-5678-1234-567812345678"

    def test_none_serialised_as_null(self):
        import json as _json

        out = _dumps({"tenant_id": None, "role": "superadmin"})
        parsed = _json.loads(out)
        assert parsed["tenant_id"] is None
        assert parsed["role"] == "superadmin"

    def test_unknown_type_still_raises(self):
        with pytest.raises(TypeError):
            _dumps({"weird": object()})

    def test_round_trip_with_real_session_shape(self):
        """The exact shape verify_code writes to Redis: verified=True,
        user_data with UUID tenant_id. _dumps must not raise."""
        session = {
            "code": "111111",
            "created_at": time.time(),
            "expires_at": time.time() + 300,
            "verified": True,
            "user_data": {
                "user_id": str(uuid4()),
                "tenant_id": UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
                "telegram_id": "349746594",
                "role": "admin",
                "full_name": "Askar Amirkhanov",
                "tenant": {
                    "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "name": "Kamilya Demo",
                    "slug": "kamilya-demo",
                    "is_demo": False,
                    "plan": "enterprise",
                },
            },
        }
        raw = _dumps(session)
        # And the result must be JSON-parseable.
        parsed = _json.loads(raw)
        assert parsed["verified"] is True
        assert parsed["user_data"]["tenant_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
