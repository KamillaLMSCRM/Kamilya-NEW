"""Focused production-safety tests for Telegram auth sessions."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.auth import auth_sessions
from app.modules.auth.auth_sessions import AuthSessionStoreUnavailableError


class FakeRedis:
    def __init__(self, *, occupied: set[str] | None = None):
        self.store: dict[str, str] = {key: "occupied" for key in occupied or set()}
        self.calls: list[dict] = []

    async def eval(self, script, numkeys, *args):
        keys = args[:numkeys]
        argv = args[numkeys:]

        if "kamilya-auth-allocate-v1" in script:
            pending_key, verified_key = keys
            self.calls.append(
                {
                    "operation": "allocate",
                    "pending_key": pending_key,
                    "verified_key": verified_key,
                    "ttl": int(argv[1]),
                }
            )
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


@pytest.fixture(autouse=True)
def clear_memory_store():
    auth_sessions._memory_store.clear()
    auth_sessions._redis_client = None
    yield
    auth_sessions._memory_store.clear()
    auth_sessions._redis_client = None


def _settings(env: str):
    return SimpleNamespace(APP_ENV=env, REDIS_URL="redis://test")


@pytest.mark.asyncio
async def test_generate_allocates_distinct_codes_with_nx_and_ttl():
    redis = FakeRedis()
    with (
        patch.object(auth_sessions, "get_settings", return_value=_settings("production")),
        patch.object(auth_sessions, "_get_redis", new=AsyncMock(return_value=redis)),
        patch.object(auth_sessions.secrets, "randbelow", side_effect=[0, 1]),
    ):
        first, first_ttl = await auth_sessions.generate_auth_code()
        second, second_ttl = await auth_sessions.generate_auth_code()

    assert first == "100000"
    assert second == "100001"
    assert first != second
    assert first_ttl == second_ttl == auth_sessions.CODE_TTL_SECONDS
    assert len(redis.store) == 2
    assert all(call["operation"] == "allocate" for call in redis.calls)
    assert all(call["ttl"] == auth_sessions.CODE_TTL_SECONDS for call in redis.calls)


@pytest.mark.asyncio
async def test_collision_retries_without_overwriting_existing_session():
    redis = FakeRedis(occupied={"auth:code:100000:verified"})
    with (
        patch.object(auth_sessions, "get_settings", return_value=_settings("production")),
        patch.object(auth_sessions, "_get_redis", new=AsyncMock(return_value=redis)),
        patch.object(auth_sessions.secrets, "randbelow", side_effect=[0, 1]),
    ):
        code, _ = await auth_sessions.generate_auth_code()

    assert code == "100001"
    assert redis.store["auth:code:100000:verified"] == "occupied"
    assert len(redis.calls) == 2


@pytest.mark.asyncio
async def test_two_browser_sessions_do_not_share_verification_state():
    redis = FakeRedis()
    with (
        patch.object(auth_sessions, "get_settings", return_value=_settings("production")),
        patch.object(auth_sessions, "_get_redis", new=AsyncMock(return_value=redis)),
        patch.object(auth_sessions.secrets, "randbelow", side_effect=[0, 1]),
    ):
        first, _ = await auth_sessions.generate_auth_code()
        second, _ = await auth_sessions.generate_auth_code()
        assert await auth_sessions.verify_code(second, "telegram-b", {"user_id": "b"})
        first_status = await auth_sessions.check_code(first)
        second_status = await auth_sessions.check_code(second)

    assert first_status == {"verified": False}
    assert second_status == {"verified": True, "user": {"user_id": "b"}}


@pytest.mark.asyncio
async def test_pending_poll_does_not_consume_session_before_verification():
    redis = FakeRedis()
    with (
        patch.object(auth_sessions, "get_settings", return_value=_settings("production")),
        patch.object(auth_sessions, "_get_redis", new=AsyncMock(return_value=redis)),
        patch.object(auth_sessions.secrets, "randbelow", return_value=6),
    ):
        code, _ = await auth_sessions.generate_auth_code()
        assert await auth_sessions.check_code(code) == {"verified": False}
        assert await auth_sessions.verify_code(code, "telegram", {"user_id": "after-poll"})
        result = await auth_sessions.check_code(code)

    assert result == {"verified": True, "user": {"user_id": "after-poll"}}


@pytest.mark.asyncio
async def test_verified_session_is_consumed_once_under_concurrent_polling():
    redis = FakeRedis()
    with (
        patch.object(auth_sessions, "get_settings", return_value=_settings("production")),
        patch.object(auth_sessions, "_get_redis", new=AsyncMock(return_value=redis)),
        patch.object(auth_sessions.secrets, "randbelow", return_value=7),
    ):
        code, _ = await auth_sessions.generate_auth_code()
        assert await auth_sessions.verify_code(code, "telegram", {"user_id": "winner"})
        first, second = await asyncio.gather(
            auth_sessions.check_code(code),
            auth_sessions.check_code(code),
        )
        replay = await auth_sessions.check_code(code)

    responses = [first, second]
    verified = [result for result in responses if result.get("verified")]
    rejected = [result for result in responses if not result.get("verified")]
    assert verified == [{"verified": True, "user": {"user_id": "winner"}}]
    assert rejected == [{"verified": False, "error": "not_found"}]
    assert replay == {"verified": False, "error": "not_found"}


@pytest.mark.asyncio
async def test_duplicate_verification_is_idempotent_and_first_payload_wins():
    redis = FakeRedis()
    with (
        patch.object(auth_sessions, "get_settings", return_value=_settings("production")),
        patch.object(auth_sessions, "_get_redis", new=AsyncMock(return_value=redis)),
        patch.object(auth_sessions.secrets, "randbelow", return_value=8),
    ):
        code, _ = await auth_sessions.generate_auth_code()
        assert await auth_sessions.verify_code(code, "telegram-a", {"user_id": "first"})
        assert await auth_sessions.verify_code(code, "telegram-b", {"user_id": "second"})
        result = await auth_sessions.check_code(code)

    assert result == {"verified": True, "user": {"user_id": "first"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("environment", ["production", "staging"])
async def test_non_dev_redis_failure_fails_closed_without_memory_session(environment):
    redis_failure = AsyncMock(return_value=None)
    with (
        patch.object(auth_sessions, "get_settings", return_value=_settings(environment)),
        patch.object(auth_sessions, "_get_redis", new=redis_failure),
    ):
        with pytest.raises(AuthSessionStoreUnavailableError):
            await auth_sessions.generate_auth_code()
        auth_sessions._memory_store["123456"] = {
            "expires_at": 9999999999,
            "verified": True,
            "user_data": {"user_id": "memory"},
        }
        assert not await auth_sessions.verify_code("123456", "telegram", {"user_id": "new"})
        assert await auth_sessions.check_code("123456") == {
            "verified": False,
            "error": "unavailable",
        }

    assert "123456" in auth_sessions._memory_store


@pytest.mark.asyncio
async def test_development_fallback_is_explicit_and_still_works():
    with (
        patch.object(auth_sessions, "get_settings", return_value=_settings("development")),
        patch.object(auth_sessions, "_get_redis", new=AsyncMock(return_value=None)),
        patch.object(auth_sessions.secrets, "randbelow", return_value=12345),
    ):
        code, ttl = await auth_sessions.generate_auth_code()
        assert code == "112345"
        assert ttl == auth_sessions.CODE_TTL_SECONDS
        assert await auth_sessions.verify_code(code, "telegram", {"user_id": "dev"})
        result = await auth_sessions.check_code(code)

    assert result == {"verified": True, "user": {"user_id": "dev"}}


@pytest.mark.asyncio
async def test_memory_verified_session_is_consumed_once_under_concurrent_polling():
    with (
        patch.object(auth_sessions, "get_settings", return_value=_settings("test")),
        patch.object(auth_sessions, "_get_redis", new=AsyncMock(return_value=None)),
        patch.object(auth_sessions.secrets, "randbelow", return_value=12346),
    ):
        code, _ = await auth_sessions.generate_auth_code()
        assert await auth_sessions.verify_code(code, "telegram", {"user_id": "winner"})
        first, second = await asyncio.gather(
            auth_sessions.check_code(code),
            auth_sessions.check_code(code),
        )
        replay = await auth_sessions.check_code(code)

    responses = [first, second]
    verified = [result for result in responses if result.get("verified")]
    rejected = [result for result in responses if not result.get("verified")]
    assert verified == [{"verified": True, "user": {"user_id": "winner"}}]
    assert rejected == [{"verified": False, "error": "not_found"}]
    assert replay == {"verified": False, "error": "not_found"}


@pytest.mark.asyncio
async def test_redis_healthy_missing_code_never_reads_memory():
    redis = FakeRedis()
    auth_sessions._memory_store["123456"] = {
        "expires_at": 9999999999,
        "verified": True,
        "user_data": {"user_id": "memory"},
    }
    with (
        patch.object(auth_sessions, "get_settings", return_value=_settings("development")),
        patch.object(auth_sessions, "_get_redis", new=AsyncMock(return_value=redis)),
    ):
        result = await auth_sessions.check_code("123456")

    assert result == {"verified": False, "error": "not_found"}
    assert "123456" in auth_sessions._memory_store
