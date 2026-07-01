from __future__ import annotations

import json
import logging
import random
import time
from typing import Any


logger = logging.getLogger(__name__)

EMAIL_CODE_TTL_SECONDS = 300
EMAIL_CODE_COOLDOWN_SECONDS = 25

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
    except Exception as exc:
        logger.warning("Redis unavailable for email OTP (%s), using in-memory fallback", exc)
        _redis_client = None
        return None


def _key(email: str) -> str:
    return f"auth:email:{email.lower().strip()}"


async def create_email_code(*, email: str, user_id: str, tenant_id: str | None, role: str) -> tuple[str, int]:
    now = time.time()
    normalized_email = email.lower().strip()
    payload = {
        "email": normalized_email,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "created_at": now,
        "expires_at": now + EMAIL_CODE_TTL_SECONDS,
    }

    redis = await _get_redis()
    if redis:
        key = _key(normalized_email)
        raw = await redis.get(key)
        if raw:
            existing = json.loads(raw)
            if now - existing.get("created_at", 0) < EMAIL_CODE_COOLDOWN_SECONDS:
                return existing["code"], max(0, int(existing["expires_at"] - now))

        payload["code"] = f"{random.randint(100000, 999999)}"
        await redis.setex(key, EMAIL_CODE_TTL_SECONDS, json.dumps(payload))
        return payload["code"], EMAIL_CODE_TTL_SECONDS

    existing = _memory_store.get(normalized_email)
    if existing and now - existing.get("created_at", 0) < EMAIL_CODE_COOLDOWN_SECONDS:
        return existing["code"], max(0, int(existing["expires_at"] - now))

    payload["code"] = f"{random.randint(100000, 999999)}"
    _memory_store[normalized_email] = payload
    return payload["code"], EMAIL_CODE_TTL_SECONDS


async def consume_email_code(*, email: str, code: str) -> dict[str, Any] | None:
    normalized_email = email.lower().strip()
    redis = await _get_redis()
    now = time.time()

    if redis:
        key = _key(normalized_email)
        raw = await redis.get(key)
        if not raw:
            return None
        payload = json.loads(raw)
        if now > payload["expires_at"] or payload["code"] != code:
            if now > payload["expires_at"]:
                await redis.delete(key)
            return None
        await redis.delete(key)
        return payload

    payload = _memory_store.get(normalized_email)
    if not payload:
        return None
    if now > payload["expires_at"] or payload["code"] != code:
        if now > payload["expires_at"]:
            _memory_store.pop(normalized_email, None)
        return None
    _memory_store.pop(normalized_email, None)
    return payload
