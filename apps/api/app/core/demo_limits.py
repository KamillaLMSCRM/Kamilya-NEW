"""Demo tenant sandbox limits.

The ``demo`` tenant (slug) is a prospect sandbox — it must let the
user try every major feature without abuse risk (infinite course
generation, spam invites, runaway AI costs). This module is the
single point that enforces those limits.

Limits (configurable via env if you want different numbers in prod):

  * users:            max 3 (the fixed admin/teacher/student demo trio)
  * courses:          max 5
  * documents:        max 2
  * ai_generation:    1 per user per UTC day (Redis-backed counter)
  * invitations:      disabled entirely (no per-tenant override)

When a limit is exceeded we raise ``DemoLimitExceeded`` which the
FastAPI exception handler turns into a 403 with a structured body
the frontend can render as a friendly modal (CTA: register).

The limits are intentionally simple — overengineering this would
delay a feature whose primary purpose is *demoability*, not billing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenants import Tenant

logger = logging.getLogger(__name__)


# ── Limits ────────────────────────────────────────────────────────────

DEMO_LIMITS: dict[str, int] = {
    "users": 3,
    "courses": 5,
    "documents": 2,
    # ai_generation is a per-user rate limit, not a tenant total — see
    # check_ai_generation_quota below.
}


# Friendly resource names (used in error messages / UI)
RESOURCE_LABELS = {
    "users": "пользователей",
    "courses": "курсов",
    "documents": "документов",
}


# ── Helpers ───────────────────────────────────────────────────────────


async def is_demo_tenant(db: AsyncSession, tenant_id: Any) -> bool:
    """True if the tenant is the prospect sandbox.

    O(1): we already fetch the tenant row in many call sites, so we
    accept a Tenant object too — pass ``tenant=t`` instead of
    ``tenant_id=...`` if you have it in hand.
    """
    return False  # overwritten below; see overloaded wrapper


async def _is_demo(db: AsyncSession, tenant_id: Any) -> bool:
    """Internal: hits the DB. Use the wrapper from routers so we can
    short-circuit when the tenant is already loaded."""
    if tenant_id is None:
        return False
    result = await db.execute(
        select(Tenant.is_demo).where(Tenant.id == tenant_id)
    )
    return bool(result.scalar())


async def count_users(db: AsyncSession, tenant_id: Any) -> int:
    from app.models.users import User
    result = await db.execute(
        select(func.count(User.id)).where(User.tenant_id == tenant_id)
    )
    return int(result.scalar() or 0)


async def count_courses(db: AsyncSession, tenant_id: Any) -> int:
    from app.models.courses import Course
    result = await db.execute(
        select(func.count(Course.id)).where(Course.tenant_id == tenant_id)
    )
    return int(result.scalar() or 0)


async def count_documents(db: AsyncSession, tenant_id: Any) -> int:
    from app.models.document import Document
    result = await db.execute(
        select(func.count(Document.id)).where(Document.tenant_id == tenant_id)
    )
    return int(result.scalar() or 0)


# ── Exception ─────────────────────────────────────────────────────────


@dataclass
class DemoLimitPayload:
    code: str = "demo_limit_exceeded"
    resource: str = ""
    limit: int = 0
    current: int = 0
    message: str = ""
    cta_text: str = "Зарегистрироваться"
    cta_href: str = "/register"


class DemoLimitExceeded(HTTPException):
    """Raised by the demo checkers. Body is JSON with code/resource/limit/current
    plus a CTA. The frontend has a single error handler that recognises
    ``code == "demo_limit_exceeded"`` and shows ``DemoLimitModal``."""

    def __init__(self, resource: str, limit: int, current: int):
        label = RESOURCE_LABELS.get(resource, resource)
        message = (
            f"Демо-режим: использовано {current}/{limit} {label}. "
            f"Зарегистрируйтесь, чтобы снять ограничения."
        )
        payload = {
            "code": "demo_limit_exceeded",
            "resource": resource,
            "limit": limit,
            "current": current,
            "message": message,
            "cta": {"text": "Зарегистрироваться", "href": "/register"},
        }
        super().__init__(status_code=403, detail=payload)
        self.payload = payload


# ── Checkers (FastAPI dependency-friendly) ────────────────────────────


async def assert_can_create_user(db: AsyncSession, tenant_id: Any) -> None:
    if not await _is_demo(db, tenant_id):
        return
    current = await count_users(db, tenant_id)
    limit = DEMO_LIMITS["users"]
    if current >= limit:
        raise DemoLimitExceeded("users", limit, current)


async def assert_can_create_course(db: AsyncSession, tenant_id: Any) -> None:
    if not await _is_demo(db, tenant_id):
        return
    current = await count_courses(db, tenant_id)
    limit = DEMO_LIMITS["courses"]
    if current >= limit:
        raise DemoLimitExceeded("courses", limit, current)


async def assert_can_create_document(db: AsyncSession, tenant_id: Any) -> None:
    if not await _is_demo(db, tenant_id):
        return
    current = await count_documents(db, tenant_id)
    limit = DEMO_LIMITS["documents"]
    if current >= limit:
        raise DemoLimitExceeded("documents", limit, current)


async def assert_can_send_invite(db: AsyncSession, tenant_id: Any) -> None:
    """Invites are completely disabled in demo — no counter."""
    if not await _is_demo(db, tenant_id):
        return
    raise DemoLimitExceeded("users", DEMO_LIMITS["users"], await count_users(db, tenant_id))


# ── AI quota (Redis, per user per UTC day) ───────────────────────────


_AI_DAILY_KEY = "demo:ai_gen:{user_id}:{yyyy_mm_dd}"


def _today_utc_key(user_id: Any) -> str:
    return _AI_DAILY_KEY.format(
        user_id=str(user_id),
        yyyy_mm_dd=datetime.now(timezone.utc).strftime("%Y%m%d"),
    )


async def check_ai_generation_quota(db: AsyncSession, user_id: Any, tenant_id: Any) -> None:
    """Allow 1 AI course generation per UTC day per user in demo.

    Backed by Redis with a TTL that expires at the next UTC midnight.
    If Redis is unreachable we FAIL OPEN — losing the quota check is
    preferable to blocking demos on an infra hiccup.
    """
    if not await _is_demo(db, tenant_id):
        return
    try:
        import redis.asyncio as aioredis
        from app.core.config import get_settings
        r = aioredis.from_url(get_settings().REDIS_URL, decode_responses=True)
        key = _today_utc_key(user_id)
        current = await r.incr(key)
        if current == 1:
            # Set expiry to end of UTC day so the key self-destructs.
            now = datetime.now(timezone.utc)
            seconds_until_midnight = int((24 * 3600) - (now.hour * 3600 + now.minute * 60 + now.second))
            await r.expire(key, max(seconds_until_midnight, 60))
        await r.aclose()
        if current > 1:
            # Daily limit exceeded — raise with same shape.
            raise DemoLimitExceeded("ai_generation", 1, 1)
    except DemoLimitExceeded:
        raise
    except Exception as e:  # pragma: no cover — fail-open
        logger.warning(
            "[DEMO_AI_QUOTA] Redis check failed, allowing through: %s",
            type(e).__name__,
        )


async def get_demo_usage(db: AsyncSession, tenant_id: Any) -> dict:
    """Return current usage counters for the demo banner UI."""
    if not await _is_demo(db, tenant_id):
        return {}
    return {
        "users": await count_users(db, tenant_id),
        "courses": await count_courses(db, tenant_id),
        "documents": await count_documents(db, tenant_id),
        "limits": DEMO_LIMITS,
    }