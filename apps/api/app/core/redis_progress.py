"""Redis-backed progress tracking for inline background tasks.

Used by `staff_import_service.commit_import` to publish the
state of an inline `apply_rules_for_users` run so the UI can
poll `GET /admin/staff/apply-rules/status/{task_id}`.

Storage format — single Redis hash at key
`apply_rules:task:{task_id}`:

    {
      "state": "PENDING" | "STARTED" | "SUCCESS" | "FAILURE",
      "total": "<int>",
      "done": "<int>",
      "failed": "<int>",
      "result": "<json>" | "",
      "error": "<str>" | "",
      "started_at": "<iso8601>",
      "updated_at": "<iso8601>",
    }

TTL: 24 hours. The task is a one-shot; after 24h the UI has
either succeeded or the user has moved on. A new apply-rules
call gets a new task_id.

Why Redis (not in-process dict): on Render free tier, the API
process and the Celery worker (if any) are different. The
status endpoint must be readable from any process. Redis is
already a project dependency (rate limiting, sessions).

Why not Celery result backend: TZ §2.6 explicitly says
"Без Celery — inline asyncio ... Celery = premature
optimization для v1.0". This module is the lightweight
replacement.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

# 24h — long enough for the UI to come back and re-poll, short
# enough to avoid Redis bloat from forgotten tasks.
TASK_TTL_SECONDS = 24 * 60 * 60


def _redis():
    """Lazy import + connect. Same pattern as core/rate_limit.py
    and core/demo_limits.py so we don't pay the cost when
    nothing in this request needs Redis.
    """
    import redis.asyncio as aioredis

    from app.core.config import get_settings

    settings = get_settings()
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(task_id: str) -> str:
    return f"apply_rules:task:{task_id}"


def new_task_id() -> str:
    """Mint a fresh task_id. We don't use a UUID4 to keep the
    string short (UI displays it in some places). 16 random
    hex chars are 64 bits — collision probability is
    negligible for our scale.
    """
    return uuid4().hex[:16]


async def init_task(task_id: str, total: int) -> None:
    """Set the task to PENDING with the total user count."""
    r = _redis()
    try:
        await r.hset(
            _key(task_id),
            mapping={
                "state": "PENDING",
                "total": str(total),
                "done": "0",
                "failed": "0",
                "result": "",
                "error": "",
                "started_at": _now_iso(),
                "updated_at": _now_iso(),
            },
        )
        await r.expire(_key(task_id), TASK_TTL_SECONDS)
    finally:
        await r.aclose()


async def mark_started(task_id: str) -> None:
    r = _redis()
    try:
        await r.hset(_key(task_id), "state", "STARTED")
        await r.hset(_key(task_id), "updated_at", _now_iso())
    finally:
        await r.aclose()


async def increment_done(task_id: str, added: int = 0, removed: int = 0) -> None:
    """Bump done by 1 (one user processed). `added` and `removed`
    are accumulators; we keep the running totals so the status
    endpoint can return them without a second round-trip.
    """
    r = _redis()
    try:
        # HINCRBY on the counter fields. Wrap in a small pipeline
        # to keep the round-trips tight.
        async with r.pipeline(transaction=True) as pipe:
            pipe.hincrby(_key(task_id), "done", 1)
            pipe.hincrby(_key(task_id), "added", added)
            pipe.hincrby(_key(task_id), "removed", removed)
            pipe.hset(_key(task_id), "updated_at", _now_iso())
            await pipe.execute()
    finally:
        await r.aclose()


async def increment_failed(task_id: str) -> None:
    r = _redis()
    try:
        async with r.pipeline(transaction=True) as pipe:
            pipe.hincrby(_key(task_id), "failed", 1)
            pipe.hset(_key(task_id), "updated_at", _now_iso())
            await pipe.execute()
    finally:
        await r.aclose()


async def mark_success(task_id: str, result: dict[str, Any]) -> None:
    r = _redis()
    try:
        await r.hset(
            _key(task_id),
            mapping={
                "state": "SUCCESS",
                "result": json.dumps(result, default=str),
                "updated_at": _now_iso(),
            },
        )
    finally:
        await r.aclose()


async def mark_failure(task_id: str, error: str) -> None:
    r = _redis()
    try:
        await r.hset(
            _key(task_id),
            mapping={
                "state": "FAILURE",
                "error": error[:1000],  # cap, don't blow up Redis
                "updated_at": _now_iso(),
            },
        )
    finally:
        await r.aclose()


async def get_task(task_id: str) -> dict[str, Any] | None:
    """Return the task state hash, or None if the task_id is
    unknown (expired, never existed, or was a Celery task —
    see status endpoint for the Celery fallback).
    """
    r = _redis()
    try:
        data = await r.hgetall(_key(task_id))
        if not data:
            return None
        # Coerce numeric fields back to int for the status response.
        for k in ("total", "done", "failed", "added", "removed"):
            if k in data and data[k] != "":
                try:
                    data[k] = int(data[k])
                except (TypeError, ValueError):
                    pass
        # Decode the result JSON if present.
        if data.get("result"):
            try:
                data["result"] = json.loads(data["result"])
            except (TypeError, ValueError):
                pass
        return data
    finally:
        await r.aclose()
