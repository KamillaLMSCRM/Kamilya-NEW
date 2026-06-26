"""Auth sessions for Telegram bot login — Redis-backed with fallback to in-memory."""
import time
import random
import json
import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

COOLDOWN_SECONDS = 25
CODE_TTL_SECONDS = 300  # 5 minutes


class _SessionEncoder(json.JSONEncoder):
    """JSON encoder that knows about UUID and datetime, the two types
    that routinely sneak into AuthUser / Tenant payloads.

    Without this, ``json.dumps(user_data)`` would raise TypeError when
    ``user_data`` contains a UUID ``tenant_id`` — which happens whenever
    a non-superadmin Telegram candidate is resolved. The old code path
    only ever saw superadmin candidates whose tenant_id was None, so
    JSON-serialisation never tripped; inverting the resolution order
    surfaced the latent bug.
    """
    def default(self, o):
        if isinstance(o, UUID):
            return str(o)
        # Fall back to default behaviour for datetime, etc. — and to
        # raise TypeError loudly for anything else we don't expect.
        return super().default(o)


def _dumps(obj) -> str:
    return json.dumps(obj, cls=_SessionEncoder)

# Fallback in-memory store if Redis unavailable
_memory_store: dict[str, dict[str, Any]] = {}

_redis_client = None


async def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis.asyncio as aioredis
        from app.core.config import get_settings
        settings = get_settings()
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await _redis_client.ping()
        return _redis_client
    except Exception as e:
        logger.warning(f"Redis unavailable for auth sessions ({e}), using in-memory fallback")
        _redis_client = None
        return None


async def generate_auth_code() -> tuple[str, float]:
    """Generate a 6-digit code with cooldown. Returns (code, expires_in)."""
    now = time.time()
    redis = await _get_redis()

    if redis:
        # Check cooldown via Redis
        keys = await redis.keys("auth:code:*")
        for key in keys:
            raw = await redis.get(key)
            if raw:
                session = json.loads(raw)
                if now - session["created_at"] < COOLDOWN_SECONDS:
                    expires_in = max(0, int(session["expires_at"] - now))
                    return key.split(":")[-1], expires_in

        # Generate new code
        code = f"{random.randint(100000, 999999)}"
        session = {
            "code": code,
            "created_at": now,
            "expires_at": now + CODE_TTL_SECONDS,
            "verified": False,
            "user_data": None,
        }
        await redis.setex(f"auth:code:{code}", CODE_TTL_SECONDS, _dumps(session))
        return code, CODE_TTL_SECONDS
    else:
        # In-memory fallback
        for existing_code, session in _memory_store.items():
            if now - session["created_at"] < COOLDOWN_SECONDS:
                expires_in = max(0, int(session["expires_at"] - now))
                return existing_code, expires_in

        code = f"{random.randint(100000, 999999)}"
        _memory_store[code] = {
            "code": code,
            "created_at": now,
            "expires_at": now + CODE_TTL_SECONDS,
            "verified": False,
            "user_data": None,
        }
        return code, CODE_TTL_SECONDS


async def verify_code(code: str, telegram_id: str, user_data: dict) -> bool:
    """Mark a code as verified with user data. Returns True if code found."""
    redis = await _get_redis()

    if redis:
        key = f"auth:code:{code}"
        raw = await redis.get(key)
        if not raw:
            return False
        session = json.loads(raw)
        if time.time() > session["expires_at"]:
            await redis.delete(key)
            return False
        session["verified"] = True
        session["user_data"] = user_data
        await redis.setex(key, CODE_TTL_SECONDS, _dumps(session))
        return True
    else:
        session = _memory_store.get(code)
        if not session:
            return False
        if time.time() > session["expires_at"]:
            del _memory_store[code]
            return False
        session["verified"] = True
        session["user_data"] = user_data
        return True


async def check_code(code: str) -> dict:
    """Check code status. Returns dict with verified, user, error."""
    redis = await _get_redis()

    if redis:
        key = f"auth:code:{code}"
        raw = await redis.get(key)
        if not raw:
            return {"verified": False, "error": "not_found"}
        session = json.loads(raw)
        now = time.time()
        if now > session["expires_at"]:
            await redis.delete(key)
            return {"verified": False, "error": "expired"}
        if not session["verified"]:
            return {"verified": False}
        user_data = session["user_data"]
        await redis.delete(key)
        return {"verified": True, "user": user_data}
    else:
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
