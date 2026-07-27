"""Unit coverage for Valkey-backed rate limiting and degraded behavior."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.core.rate_limit import RateLimiter, RateLimitMiddleware


class FakePipeline:
    def __init__(self, redis: FakeRedis):
        self.redis = redis

    def zremrangebyscore(self, *args):
        return self

    def zadd(self, *args):
        return self

    def zcard(self, *args):
        return self

    def expire(self, *args):
        return self

    async def execute(self):
        self.redis.current += 1
        return [0, True, self.redis.current, True]


class FakeRedis:
    def __init__(self):
        self.current = 0

    def pipeline(self):
        return FakePipeline(self)


class FailingPipeline(FakePipeline):
    async def execute(self):
        raise RuntimeError("Valkey unavailable")


class FailingRedis(FakeRedis):
    def pipeline(self):
        return FailingPipeline(self)


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 443),
        }
    )


@pytest.mark.asyncio
async def test_rate_limiter_enforces_normal_window():
    limiter = RateLimiter()
    limiter._redis = FakeRedis()

    allowed, first = await limiter.check_rate_limit("test", max_requests=1, window_seconds=60)
    denied, second = await limiter.check_rate_limit("test", max_requests=1, window_seconds=60)

    assert allowed is True
    assert first["current"] == 1
    assert denied is False
    assert second["current"] == 2
    assert "unavailable" not in second


@pytest.mark.asyncio
async def test_rate_limiter_rejects_when_valkey_is_unavailable(caplog):
    limiter = RateLimiter()
    limiter._available = False

    allowed, info = await limiter.check_rate_limit("test", max_requests=5, window_seconds=60)

    assert allowed is False
    assert info["unavailable"] is True
    assert "allowing request" not in caplog.text


@pytest.mark.asyncio
async def test_rate_limiter_rejects_when_valkey_operation_fails(caplog):
    limiter = RateLimiter()
    limiter._redis = FailingRedis()

    allowed, info = await limiter.check_rate_limit("test", max_requests=5, window_seconds=60)

    assert allowed is False
    assert info["unavailable"] is True
    assert "limiter state unavailable" in caplog.text


@pytest.mark.asyncio
async def test_public_auth_fails_closed_but_internal_route_stays_available():
    middleware = RateLimitMiddleware(lambda scope, receive, send: None)
    middleware.limiter._available = False
    settings = SimpleNamespace(APP_ENV="production")
    calls = []

    async def call_next(request):
        calls.append(request.url.path)
        return Response("ok")

    with patch("app.core.config.get_settings", return_value=settings):
        public_response = await middleware.dispatch(_request("/api/v1/auth/login"), call_next)
        internal_response = await middleware.dispatch(_request("/api/v1/internal/task"), call_next)

    assert public_response.status_code == 503
    assert public_response.headers["Retry-After"] == "5"
    assert internal_response.status_code == 200
    assert calls == ["/api/v1/internal/task"]
