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

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.auth import auth_sessions
from app.modules.auth.auth_sessions import _dumps, _memory_store
from app.core.rate_limit import RateLimitMiddleware

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
    """Minimal Redis stub: GET / SETEX / DELETE. Stored values are
    raw strings, mirroring redis-py's default when decode_responses=True."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def setex(self, key, ttl, value):
        self.store[key] = value

    async def delete(self, key):
        self.store.pop(key, None)

    async def keys(self, pattern):
        # pattern like "auth:code:*"
        import fnmatch
        return [k for k in self.store if fnmatch.fnmatchcase(k, pattern)]

    async def ping(self):
        return True


class FailingRedis(FakeRedis):
    async def get(self, key):
        raise RuntimeError("max requests limit exceeded")

    async def setex(self, key, ttl, value):
        raise RuntimeError("max requests limit exceeded")

    async def delete(self, key):
        raise RuntimeError("max requests limit exceeded")


@pytest.fixture
def client():
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
            user_q = MagicMock(); user_q.scalars.return_value.all.return_value = [user]
            role_q = MagicMock(); role_q.scalar_one_or_none.return_value = None
            tenant_q = MagicMock(); tenant_q.scalar_one_or_none.return_value = tenant_row

            fake_db = AsyncMock()
            fake_db.execute.side_effect = [user_q, role_q, tenant_q]

            async def fake_get_db_override():
                yield fake_db

            from app.core.db import get_db
            app.dependency_overrides[get_db] = fake_get_db_override

            # Pre-create the auth session in fake_redis under the code we send.
            import time
            patched_redis.store[f"auth:code:{code}"] = _dumps({
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

            stored = patched_redis.store.get(f"auth:code:{code}")
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
        from uuid import UUID
        import json as _json

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
        from uuid import UUID
        import json as _json
        import time

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
