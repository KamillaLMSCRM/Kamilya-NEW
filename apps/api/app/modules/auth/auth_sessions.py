"""Redis-backed Telegram auth sessions with an explicit non-production fallback."""

from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any
from uuid import UUID

from app.core.config import get_settings

logger = logging.getLogger(__name__)

CODE_TTL_SECONDS = 300
CODE_LENGTH = 6
MAX_CODE_ALLOCATION_ATTEMPTS = 32

_ALLOCATE_CODE_SCRIPT = """
-- kamilya-auth-allocate-v1
if redis.call("EXISTS", KEYS[1]) == 1 or redis.call("EXISTS", KEYS[2]) == 1 then
    return 0
end
local stored = redis.call("SET", KEYS[1], ARGV[1], "EX", ARGV[2], "NX")
if stored then
    return 1
end
return 0
"""

_VERIFY_CODE_SCRIPT = """
-- kamilya-auth-verify-v1
if redis.call("EXISTS", KEYS[2]) == 1 then
    return 2
end
local pending = redis.call("GET", KEYS[1])
if not pending then
    return 0
end
local ttl = redis.call("TTL", KEYS[1])
if ttl <= 0 then
    return 0
end
local stored = redis.call("SET", KEYS[2], ARGV[1], "EX", ttl, "NX")
if not stored then
    return 2
end
redis.call("DEL", KEYS[1])
return 1
"""

_CONSUME_CODE_SCRIPT = """
-- kamilya-auth-consume-v1
local verified = redis.call("GET", KEYS[2])
if verified then
    redis.call("DEL", KEYS[2])
    return {1, verified}
end
if redis.call("EXISTS", KEYS[1]) == 1 then
    return {0, "pending"}
end
return {0, "not_found"}
"""


class AuthSessionStoreUnavailableError(RuntimeError):
    """Raised when the shared auth-session store cannot be used."""


class _SessionEncoder(json.JSONEncoder):
    """Encode the UUID values that can occur in the resolved user payload."""

    def default(self, o):
        if isinstance(o, UUID):
            return str(o)
        return super().default(o)


def _dumps(obj) -> str:
    return json.dumps(obj, cls=_SessionEncoder)


# Deliberately process-local and only reachable from development/test code.
_memory_store: dict[str, dict[str, Any]] = {}
_redis_client = None


def _memory_fallback_allowed() -> bool:
    return get_settings().APP_ENV.lower() in {"development", "test"}


def _new_code() -> str:
    first = 10 ** (CODE_LENGTH - 1)
    return str(secrets.randbelow(10**CODE_LENGTH - first) + first)


def _pending_key(code: str) -> str:
    return f"auth:code:{code}:pending"


def _verified_key(code: str) -> str:
    return f"auth:code:{code}:verified"


def _memory_generate(now: float) -> tuple[str, float]:
    for _ in range(MAX_CODE_ALLOCATION_ATTEMPTS):
        code = _new_code()
        if code in _memory_store:
            continue
        _memory_store[code] = {
            "code": code,
            "created_at": now,
            "expires_at": now + CODE_TTL_SECONDS,
            "verified": False,
            "user_data": None,
        }
        return code, CODE_TTL_SECONDS
    raise AuthSessionStoreUnavailableError("Unable to allocate authentication code")


def _memory_verify(code: str, user_data: dict) -> bool:
    session = _memory_store.get(code)
    if not session:
        return False
    if time.time() > session["expires_at"]:
        del _memory_store[code]
        return False
    if session["verified"]:
        return True
    session["verified"] = True
    session["user_data"] = user_data
    return True


def _memory_check(code: str) -> dict:
    session = _memory_store.get(code)
    if not session:
        return {"verified": False, "error": "not_found"}
    now = time.time()
    if now > session["expires_at"]:
        del _memory_store[code]
        return {"verified": False, "error": "expired"}
    if not session["verified"]:
        return {"verified": False}
    user_data = session["user_data"]
    del _memory_store[code]
    return {"verified": True, "user": user_data}


async def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis.asyncio as aioredis

        settings = get_settings()
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await _redis_client.ping()
        return _redis_client
    except Exception:
        logger.warning("auth_sessions_redis_unavailable")
        _redis_client = None
        return None


async def generate_auth_code() -> tuple[str, float]:
    """Allocate a new six-digit code without reusing another browser's code."""
    now = time.time()
    redis = await _get_redis()

    if redis is None:
        if _memory_fallback_allowed():
            return _memory_generate(now)
        raise AuthSessionStoreUnavailableError("Authentication service temporarily unavailable")

    try:
        for _ in range(MAX_CODE_ALLOCATION_ATTEMPTS):
            code = _new_code()
            session = {
                "code": code,
                "created_at": now,
                "expires_at": now + CODE_TTL_SECONDS,
                "verified": False,
                "user_data": None,
            }
            # Reserve against both lifecycle keys atomically. A code cannot be
            # reused while either a pending or verified session still exists.
            stored = await redis.eval(
                _ALLOCATE_CODE_SCRIPT,
                2,
                _pending_key(code),
                _verified_key(code),
                _dumps(session),
                CODE_TTL_SECONDS,
            )
            if int(stored) == 1:
                return code, CODE_TTL_SECONDS
        raise AuthSessionStoreUnavailableError("Unable to allocate authentication code")
    except AuthSessionStoreUnavailableError:
        raise
    except Exception:
        logger.warning("auth_code_redis_generate_failed")
        if _memory_fallback_allowed():
            return _memory_generate(now)
        raise AuthSessionStoreUnavailableError("Authentication service temporarily unavailable") from None


async def verify_code(code: str, telegram_id: str, user_data: dict) -> bool:
    """Mark a code as verified; never combine Redis and memory sessions."""
    redis = await _get_redis()

    if redis is None:
        return _memory_verify(code, user_data) if _memory_fallback_allowed() else False

    try:
        verified_session = {
            "code": code,
            "verified": True,
            "user_data": user_data,
        }
        transition = await redis.eval(
            _VERIFY_CODE_SCRIPT,
            2,
            _pending_key(code),
            _verified_key(code),
            _dumps(verified_session),
        )
        # 1 = transitioned now; 2 = already verified by an earlier duplicate
        # webhook delivery. The first payload remains authoritative.
        return int(transition) in {1, 2}
    except Exception:
        logger.warning("auth_code_redis_verify_failed")
        return _memory_verify(code, user_data) if _memory_fallback_allowed() else False


async def check_code(code: str) -> dict:
    """Read and consume a verified code, with production fail-closed behavior."""
    redis = await _get_redis()

    if redis is None:
        if _memory_fallback_allowed():
            return _memory_check(code)
        return {"verified": False, "error": "unavailable"}

    try:
        consumed = await redis.eval(
            _CONSUME_CODE_SCRIPT,
            2,
            _pending_key(code),
            _verified_key(code),
        )
        state = int(consumed[0])
        if state == 0 and consumed[1] == "pending":
            return {"verified": False}
        if state == 0:
            return {"verified": False, "error": "not_found"}
        session = json.loads(consumed[1])
        return {"verified": True, "user": session["user_data"]}
    except Exception:
        logger.warning("auth_code_redis_check_failed")
        if _memory_fallback_allowed():
            return _memory_check(code)
        return {"verified": False, "error": "unavailable"}
