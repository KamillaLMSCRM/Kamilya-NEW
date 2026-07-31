"""Purpose-bound OTP step-up authentication for learner evidence.

The challenge is deliberately separate from login and invitation OTPs. It is
bound to one tenant, one evidence subject, one event, and the exact action
text/version that the learner saw. Redis stores only hashes and is consumed by
an atomic Lua operation. No OTP value is written to logs or persistent data.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, NoReturn
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select

from app.core.config import get_settings
from app.core.email import EmailService
from app.core.rate_limit import RateLimiter
from app.models.tenants import Tenant
from app.modules.training_evidence.models import TrainingEvidenceEvent, TrainingEvidenceStepUpConfirmation
from app.modules.training_evidence.service import canonical_json_sha256, confirm_step_up, get_event

logger = logging.getLogger(__name__)

STEP_UP_TTL_SECONDS = 300
STEP_UP_RESEND_COOLDOWN_SECONDS = 60
STEP_UP_MAX_ATTEMPTS = 5
STEP_UP_RATE_LIMIT = 5
STEP_UP_RATE_WINDOW_SECONDS = 300

_memory_challenges: dict[str, dict[str, Any]] = {}
_memory_rate_limits: dict[str, list[float]] = {}
_memory_lock = asyncio.Lock()
_redis_client = None
_rate_limiter: RateLimiter | None = None


def _confirmation_not_configured(message: str = "Confirmation configuration is missing") -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": "confirmation_not_configured", "message": message},
    )


def _snapshot_object_version(snapshot: Mapping[str, Any]) -> str | None:
    """Return the only version marker accepted by the event contract.

    ``confirmation.object_version`` is intentionally checked against an
    independent release/snapshot marker.  A value that only repeats itself is
    not a canonical version and is therefore rejected.
    """

    release_version = snapshot.get("release_version")
    if release_version not in (None, ""):
        return f"release:{release_version}"

    for key in ("content_release_sha256", "release_sha256", "snapshot_sha256"):
        digest = snapshot.get(key)
        if digest not in (None, ""):
            return f"snapshot-sha256:{digest}"

    release = snapshot.get("release")
    if isinstance(release, Mapping):
        version = release.get("version")
        if version not in (None, ""):
            return f"release:{version}"
        digest = release.get("snapshot_sha256") or release.get("sha256")
        if digest not in (None, ""):
            return f"snapshot-sha256:{digest}"

    release_id = snapshot.get("content_release_id") or snapshot.get("release_id")
    if release_id not in (None, ""):
        return f"release-id:{release_id}"
    return None


def _canonical_confirmation(event: TrainingEvidenceEvent) -> tuple[str, str]:
    """Read purpose and version only from the immutable event snapshot."""

    snapshot = event.payload_snapshot
    if not isinstance(snapshot, Mapping):
        _confirmation_not_configured()
    if canonical_json_sha256(dict(snapshot)) != event.payload_sha256:
        _confirmation_not_configured("Evidence snapshot integrity is invalid")
    confirmation = snapshot.get("confirmation")
    if not isinstance(confirmation, Mapping):
        _confirmation_not_configured()

    statement = confirmation.get("statement")
    object_version = confirmation.get("object_version")
    expected_version = _snapshot_object_version(snapshot)
    if (
        not isinstance(statement, str)
        or not statement.strip()
        or not isinstance(object_version, str)
        or not object_version.strip()
        or expected_version is None
        or object_version != expected_version
    ):
        _confirmation_not_configured()
    return statement, object_version


async def _chain_has_revocation(
    db,
    *,
    tenant_id: UUID,
    event: TrainingEvidenceEvent,
) -> bool:
    """Check the complete correction tree, not only a direct child."""

    root = event
    seen = {root.id}
    while root.related_event_id is not None:
        if root.related_event_id in seen:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "invalid_event_chain", "message": "Evidence chain contains a cycle"},
            )
        parent = await db.scalar(
            select(TrainingEvidenceEvent).where(
                TrainingEvidenceEvent.id == root.related_event_id,
                TrainingEvidenceEvent.tenant_id == tenant_id,
            )
        )
        if parent is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "invalid_event_chain", "message": "Evidence chain is incomplete"},
            )
        seen.add(parent.id)
        root = parent
        if len(seen) > 200:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "invalid_event_chain", "message": "Evidence chain is too long"},
            )

    descendants = (
        select(TrainingEvidenceEvent.id, TrainingEvidenceEvent.record_type)
        .where(
            TrainingEvidenceEvent.id == root.id,
            TrainingEvidenceEvent.tenant_id == tenant_id,
        )
        .cte("evidence_descendants", recursive=True)
    )
    child = TrainingEvidenceEvent.__table__.alias("evidence_child")
    descendants = descendants.union_all(
        select(child.c.id, child.c.record_type).where(
            child.c.tenant_id == tenant_id,
            child.c.related_event_id == descendants.c.id,
        )
    )
    revocation = await db.scalar(
        select(descendants.c.id)
        .where(descendants.c.record_type == "revocation")
        .limit(1)
    )
    return revocation is not None


async def _event_for_step_up(db, tenant_id: UUID, event_id: UUID, user_id: UUID, *, lock: bool = False):
    """Re-read the tenant-scoped event and apply revocation/duplicate gates."""

    event = await get_event(db, tenant_id, event_id)
    if event.user_id != user_id:
        raise HTTPException(status_code=403, detail="Only the learner can confirm this action")
    if lock:
        locked_event = await db.scalar(
            select(TrainingEvidenceEvent)
            .where(TrainingEvidenceEvent.id == event_id, TrainingEvidenceEvent.tenant_id == tenant_id)
            .with_for_update()
        )
        event = locked_event or event
        if event.user_id != user_id:
            raise HTTPException(status_code=403, detail="Only the learner can confirm this action")

    if await _chain_has_revocation(db, tenant_id=tenant_id, event=event):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "event_revoked", "message": "Revoked evidence cannot be confirmed"},
        )

    duplicate = await db.scalar(
        select(TrainingEvidenceStepUpConfirmation.id).where(
            TrainingEvidenceStepUpConfirmation.tenant_id == tenant_id,
            TrainingEvidenceStepUpConfirmation.event_id == event.id,
            TrainingEvidenceStepUpConfirmation.user_id == user_id,
        )
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "confirmation_already_exists",
                "message": "This evidence event has already been confirmed",
            },
        )
    return event, _canonical_confirmation(event)


def _now() -> float:
    return time.time()


def _hash_otp(code: str) -> str:
    settings = get_settings()
    return hmac.new(
        settings.JWT_SECRET.encode("utf-8"),
        code.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _binding_hash(*, action_text: str, object_version: str) -> str:
    payload = json.dumps(
        {"action_text": action_text, "object_version": object_version},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _challenge_key(challenge_id: str) -> str:
    return f"training:evidence:step-up:challenge:{challenge_id}"


def _scope_key(tenant_id: UUID, event_id: UUID, user_id: UUID) -> str:
    return f"training:evidence:step-up:scope:{tenant_id}:{event_id}:{user_id}"


def _rate_key(*, tenant_id: UUID, event_id: UUID, user_id: UUID, ip_address: str | None, action: str) -> str:
    ip_hash = hashlib.sha256((ip_address or "unknown").encode("utf-8")).hexdigest()[:32]
    return f"training:evidence:step-up:rate:{action}:{tenant_id}:{event_id}:{user_id}:{ip_hash}"


async def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
        await client.ping()
        _redis_client = client
        return client
    except Exception:
        # Do not log connection details, URLs, or provider exceptions.
        logger.warning("Step-up Valkey unavailable")
        _redis_client = None
        return None


async def _check_rate_limit(key: str) -> None:
    """Fail closed in production, while keeping local tests self-contained."""

    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(get_settings().REDIS_URL)
    allowed, info = await _rate_limiter.check_rate_limit(
        key,
        STEP_UP_RATE_LIMIT,
        STEP_UP_RATE_WINDOW_SECONDS,
    )
    if info.get("unavailable"):
        if get_settings().APP_ENV.lower() == "production":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service temporarily unavailable",
            )
        now = _now()
        async with _memory_lock:
            bucket = [t for t in _memory_rate_limits.get(key, []) if now - t < STEP_UP_RATE_WINDOW_SECONDS]
            if len(bucket) >= STEP_UP_RATE_LIMIT:
                _memory_rate_limits[key] = bucket
                raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts")
            bucket.append(now)
            _memory_rate_limits[key] = bucket
        return
    if not allowed:
        retry_after = max(1, int(info.get("reset", _now() + 1) - _now()))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts",
            headers={"Retry-After": str(retry_after)},
        )


_CREATE_CHALLENGE_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if current then
  local old_key = 'training:evidence:step-up:challenge:' .. current
  local created = redis.call('HGET', old_key, 'created_at')
  if created and (tonumber(ARGV[1]) - tonumber(created)) < tonumber(ARGV[2]) then
    return {0, current, tonumber(ARGV[2]) - (tonumber(ARGV[1]) - tonumber(created))}
  end
  redis.call('DEL', KEYS[1])
  redis.call('DEL', old_key)
end
redis.call('HSET', KEYS[2],
  'tenant_id', ARGV[3],
  'event_id', ARGV[4],
  'user_id', ARGV[5],
  'binding_hash', ARGV[6],
  'otp_hash', ARGV[7],
  'created_at', ARGV[1],
  'expires_at', ARGV[8],
  'attempts', '0')
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[9]))
redis.call('SET', KEYS[1], ARGV[10], 'EX', tonumber(ARGV[9]))
return {1, ARGV[10], 0}
"""

_CONSUME_CHALLENGE_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 0 then return {0, 'missing'} end
local expires = tonumber(redis.call('HGET', KEYS[1], 'expires_at') or '0')
if tonumber(ARGV[1]) > expires then
  redis.call('DEL', KEYS[1])
  return {0, 'expired'}
end
if redis.call('HGET', KEYS[1], 'tenant_id') ~= ARGV[2]
   or redis.call('HGET', KEYS[1], 'event_id') ~= ARGV[3]
   or redis.call('HGET', KEYS[1], 'user_id') ~= ARGV[4]
   or redis.call('HGET', KEYS[1], 'binding_hash') ~= ARGV[5] then
  return {0, 'mismatch'}
end
local attempts = tonumber(redis.call('HGET', KEYS[1], 'attempts') or '0')
if attempts >= tonumber(ARGV[7]) then
  redis.call('DEL', KEYS[1])
  return {0, 'attempts'}
end
if redis.call('HGET', KEYS[1], 'otp_hash') ~= ARGV[6] then
  attempts = redis.call('HINCRBY', KEYS[1], 'attempts', 1)
  if attempts >= tonumber(ARGV[7]) then redis.call('DEL', KEYS[1]) end
  return {0, 'invalid'}
end
redis.call('DEL', KEYS[1])
return {1, 'consumed'}
"""


async def _create_challenge(
    *,
    tenant_id: UUID,
    event_id: UUID,
    user_id: UUID,
    action_text: str,
    object_version: str,
) -> tuple[str, str, int]:
    now = _now()
    challenge_id = secrets.token_urlsafe(32)
    code = f"{100000 + secrets.randbelow(900000)}"
    binding_hash = _binding_hash(action_text=action_text, object_version=object_version)
    payload = {
        "tenant_id": str(tenant_id),
        "event_id": str(event_id),
        "user_id": str(user_id),
        "binding_hash": binding_hash,
        "otp_hash": _hash_otp(code),
        "created_at": now,
        "expires_at": now + STEP_UP_TTL_SECONDS,
        "attempts": 0,
    }
    redis = await _get_redis()
    if redis is None:
        if get_settings().APP_ENV.lower() == "production":
            raise HTTPException(status_code=503, detail="Authentication service temporarily unavailable")
        scope = _scope_key(tenant_id, event_id, user_id)
        async with _memory_lock:
            existing_id = next(
                (key for key, item in _memory_challenges.items() if item.get("scope") == scope and item["expires_at"] > now),
                None,
            )
            if existing_id:
                existing = _memory_challenges[existing_id]
                remaining = STEP_UP_RESEND_COOLDOWN_SECONDS - int(now - existing["created_at"])
                if remaining > 0:
                    raise HTTPException(
                        status_code=429,
                        detail="Please wait before requesting another code",
                        headers={"Retry-After": str(remaining)},
                    )
                _memory_challenges.pop(existing_id, None)
            payload["scope"] = scope
            _memory_challenges[challenge_id] = payload
        return challenge_id, code, STEP_UP_TTL_SECONDS

    scope_key = _scope_key(tenant_id, event_id, user_id)
    try:
        result = await redis.eval(
            _CREATE_CHALLENGE_SCRIPT,
            2,
            scope_key,
            _challenge_key(challenge_id),
            str(now),
            str(STEP_UP_RESEND_COOLDOWN_SECONDS),
            str(tenant_id),
            str(event_id),
            str(user_id),
            binding_hash,
            payload["otp_hash"],
            str(payload["expires_at"]),
            str(STEP_UP_TTL_SECONDS),
            challenge_id,
        )
    except Exception:
        logger.warning("Step-up challenge storage failed")
        raise HTTPException(status_code=503, detail="Authentication service temporarily unavailable") from None
    if int(result[0]) == 0:
        retry_after = max(1, int(result[2]))
        raise HTTPException(
            status_code=429,
            detail="Please wait before requesting another code",
            headers={"Retry-After": str(retry_after)},
        )
    return challenge_id, code, STEP_UP_TTL_SECONDS


async def _consume_challenge(
    *,
    challenge_id: str,
    tenant_id: UUID,
    event_id: UUID,
    user_id: UUID,
    action_text: str,
    object_version: str,
    code: str,
) -> None:
    now = _now()
    binding_hash = _binding_hash(action_text=action_text, object_version=object_version)
    redis = await _get_redis()
    if redis is None:
        if get_settings().APP_ENV.lower() == "production":
            raise HTTPException(status_code=503, detail="Authentication service temporarily unavailable")
        async with _memory_lock:
            payload = _memory_challenges.get(challenge_id)
            if not payload or payload["expires_at"] < now:
                _memory_challenges.pop(challenge_id, None)
                raise HTTPException(status_code=401, detail="Invalid or expired confirmation code")
            if not (
                payload["tenant_id"] == str(tenant_id)
                and payload["event_id"] == str(event_id)
                and payload["user_id"] == str(user_id)
                and hmac.compare_digest(payload["binding_hash"], binding_hash)
            ):
                raise HTTPException(status_code=401, detail="Invalid or expired confirmation code")
            if payload["attempts"] >= STEP_UP_MAX_ATTEMPTS:
                _memory_challenges.pop(challenge_id, None)
                raise HTTPException(status_code=401, detail="Invalid or expired confirmation code")
            if not hmac.compare_digest(payload["otp_hash"], _hash_otp(code)):
                payload["attempts"] += 1
                if payload["attempts"] >= STEP_UP_MAX_ATTEMPTS:
                    _memory_challenges.pop(challenge_id, None)
                raise HTTPException(status_code=401, detail="Invalid or expired confirmation code")
            _memory_challenges.pop(challenge_id, None)
        return

    try:
        result = await redis.eval(
            _CONSUME_CHALLENGE_SCRIPT,
            1,
            _challenge_key(challenge_id),
            str(now),
            str(tenant_id),
            str(event_id),
            str(user_id),
            binding_hash,
            _hash_otp(code),
            str(STEP_UP_MAX_ATTEMPTS),
        )
    except Exception:
        logger.warning("Step-up challenge consume failed")
        raise HTTPException(status_code=503, detail="Authentication service temporarily unavailable") from None
    if not result or int(result[0]) != 1:
        raise HTTPException(status_code=401, detail="Invalid or expired confirmation code")


async def request_step_up(
    *,
    db,
    tenant_id: UUID,
    event_id: UUID,
    user,
    ip_address: str | None,
) -> dict[str, Any]:
    if user.role != "student":
        raise HTTPException(status_code=403, detail="Only the learner can confirm this action")
    event, (action_text, object_version) = await _event_for_step_up(db, tenant_id, event_id, user.id)
    if not user.email:
        raise HTTPException(status_code=409, detail="Learner email is required for confirmation")

    await _check_rate_limit(
        _rate_key(
            tenant_id=tenant_id,
            event_id=event_id,
            user_id=user.id,
            ip_address=ip_address,
            action="request",
        )
    )
    challenge_id, code, expires_in = await _create_challenge(
        tenant_id=tenant_id,
        event_id=event_id,
        user_id=user.id,
        action_text=action_text,
        object_version=object_version,
    )
    try:
        tenant_name = await db.scalar(select(Tenant.name).where(Tenant.id == tenant_id)) or "вашей организации"
        await EmailService().send_training_confirmation_code(
            to_email=user.email,
            code=code,
            company_name=tenant_name,
        )
    except Exception:
        await _delete_challenge(challenge_id)
        logger.warning("Step-up email delivery failed")
        raise HTTPException(status_code=503, detail="Unable to send confirmation code") from None
    return {
        "challenge_id": challenge_id,
        "event_id": event_id,
        "expires_in": expires_in,
        "retry_after": STEP_UP_RESEND_COOLDOWN_SECONDS,
    }


async def _delete_challenge(challenge_id: str) -> None:
    redis = await _get_redis()
    if redis is None:
        async with _memory_lock:
            _memory_challenges.pop(challenge_id, None)
        return
    try:
        await redis.delete(_challenge_key(challenge_id))
    except Exception:
        logger.warning("Step-up challenge cleanup failed")


async def verify_step_up(
    *,
    db,
    tenant_id: UUID,
    event_id: UUID,
    user,
    challenge_id: str,
    code: str,
    ip_address: str | None,
    user_agent: str | None,
) -> Any:
    if user.role != "student":
        raise HTTPException(status_code=403, detail="Only the learner can confirm this action")
    # Re-read and lock the event before checking duplicate/revocation state.
    # The canonical values below are never accepted from the browser.
    event, (action_text, object_version) = await _event_for_step_up(
        db, tenant_id, event_id, user.id, lock=True
    )
    await _check_rate_limit(
        _rate_key(
            tenant_id=tenant_id,
            event_id=event_id,
            user_id=user.id,
            ip_address=ip_address,
            action="verify",
        )
    )
    await _consume_challenge(
        challenge_id=challenge_id,
        tenant_id=tenant_id,
        event_id=event_id,
        user_id=user.id,
        action_text=action_text,
        object_version=object_version,
        code=code,
    )
    # The challenge is consumed before this call. The confirmation service
    # receives only server-captured request metadata and canonical values
    # re-read from the immutable event snapshot.
    return await confirm_step_up(
        db,
        tenant_id=tenant_id,
        event_id=event_id,
        user_id=user.id,
        action_text=action_text,
        object_version=object_version,
        reauth_method="email_otp",
        ip_address=ip_address,
        user_agent=user_agent,
        confirmed_at=datetime.now(UTC),
    )
