from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any

logger = logging.getLogger(__name__)

EMAIL_CODE_TTL_SECONDS = 300
EMAIL_CODE_COOLDOWN_SECONDS = 25
INVITATION_CODE_COOLDOWN_SECONDS = 60
EMAIL_CODE_MAX_ATTEMPTS = 5

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


def _key(email: str, *, purpose: str = "login", subject_id: str | None = None) -> str:
    scope = purpose.strip().lower() or "login"
    subject = f":{subject_id}" if subject_id else ""
    return f"auth:email:{scope}{subject}:{email.lower().strip()}"


async def _create_scoped_email_code(
    *,
    email: str,
    user_id: str,
    tenant_id: str | None,
    role: str,
    purpose: str,
    subject_id: str | None,
    cooldown_seconds: int,
) -> tuple[str, int, bool]:
    now = time.time()
    normalized_email = email.lower().strip()
    payload = {
        "email": normalized_email,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "purpose": purpose,
        "subject_id": subject_id,
        "failed_attempts": 0,
        "created_at": now,
        "expires_at": now + EMAIL_CODE_TTL_SECONDS,
    }

    redis = await _get_redis()
    if redis:
        key = _key(normalized_email, purpose=purpose, subject_id=subject_id)
        raw = await redis.get(key)
        if raw:
            existing = json.loads(raw)
            if now - existing.get("created_at", 0) < cooldown_seconds:
                return existing["code"], max(0, int(existing["expires_at"] - now)), False

        payload["code"] = f"{100000 + secrets.randbelow(900000)}"
        await redis.setex(key, EMAIL_CODE_TTL_SECONDS, json.dumps(payload))
        return payload["code"], EMAIL_CODE_TTL_SECONDS, True

    key = _key(normalized_email, purpose=purpose, subject_id=subject_id)
    existing = _memory_store.get(key)
    if existing and now - existing.get("created_at", 0) < cooldown_seconds:
        return existing["code"], max(0, int(existing["expires_at"] - now)), False

    payload["code"] = f"{100000 + secrets.randbelow(900000)}"
    _memory_store[key] = payload
    return payload["code"], EMAIL_CODE_TTL_SECONDS, True


async def create_email_code(*, email: str, user_id: str, tenant_id: str | None, role: str) -> tuple[str, int]:
    code, expires_in, _ = await _create_scoped_email_code(
        email=email,
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        purpose="login",
        subject_id=None,
        cooldown_seconds=EMAIL_CODE_COOLDOWN_SECONDS,
    )
    return code, expires_in


async def create_invitation_email_code(
    *,
    email: str,
    user_id: str,
    tenant_id: str,
    role: str,
    invitation_id: str,
) -> tuple[str, int, bool]:
    return await _create_scoped_email_code(
        email=email,
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        purpose="invitation",
        subject_id=invitation_id,
        cooldown_seconds=INVITATION_CODE_COOLDOWN_SECONDS,
    )


async def consume_email_code(
    *,
    email: str,
    code: str,
    purpose: str = "login",
    subject_id: str | None = None,
) -> dict[str, Any] | None:
    normalized_email = email.lower().strip()
    redis = await _get_redis()
    now = time.time()
    key = _key(normalized_email, purpose=purpose, subject_id=subject_id)

    if redis:
        raw = await redis.get(key)
        if not raw:
            return None
        payload = json.loads(raw)
        if now > payload["expires_at"]:
            await redis.delete(key)
            return None
        if payload["code"] != code:
            payload["failed_attempts"] = int(payload.get("failed_attempts", 0)) + 1
            if payload["failed_attempts"] >= EMAIL_CODE_MAX_ATTEMPTS:
                await redis.delete(key)
            else:
                remaining = max(1, int(payload["expires_at"] - now))
                await redis.setex(key, remaining, json.dumps(payload))
            return None
        await redis.delete(key)
        return payload

    payload = _memory_store.get(key)
    if not payload:
        return None
    if now > payload["expires_at"]:
        _memory_store.pop(key, None)
        return None
    if payload["code"] != code:
        payload["failed_attempts"] = int(payload.get("failed_attempts", 0)) + 1
        if payload["failed_attempts"] >= EMAIL_CODE_MAX_ATTEMPTS:
            _memory_store.pop(key, None)
        return None
    _memory_store.pop(key, None)
    return payload


async def invalidate_email_code(
    *,
    email: str,
    purpose: str = "login",
    subject_id: str | None = None,
) -> None:
    """Remove an OTP that could not be delivered or must be revoked."""
    normalized_email = email.lower().strip()
    key = _key(normalized_email, purpose=purpose, subject_id=subject_id)
    redis = await _get_redis()
    if redis:
        await redis.delete(key)
        return
    _memory_store.pop(key, None)
