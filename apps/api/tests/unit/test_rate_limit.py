"""Unit coverage for Valkey-backed rate limiting and degraded behavior."""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.core.rate_limit import PUBLIC_AUTH_ENDPOINTS, RATE_LIMITS, RateLimiter, RateLimitMiddleware


def test_every_public_auth_endpoint_has_an_explicit_rate_limit():
    assert PUBLIC_AUTH_ENDPOINTS <= RATE_LIMITS.keys()


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


class RecoveringRedis(FakeRedis):
    async def ping(self):
        return True


class FailingPipeline(FakePipeline):
    async def execute(self):
        raise RuntimeError("Valkey unavailable")


class FailingRedis(FakeRedis):
    def pipeline(self):
        return FailingPipeline(self)


def _request(path: str, *, authorization: str | None = None) -> Request:
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode()))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
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
    limiter._retry_after = time.monotonic() + 60

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
async def test_rate_limiter_reconnects_after_unavailable_cooldown():
    limiter = RateLimiter(unavailable_retry_seconds=5)
    limiter._available = False
    limiter._retry_after = time.monotonic() - 1
    recovered = RecoveringRedis()

    with patch("redis.asyncio.from_url", return_value=recovered):
        allowed, info = await limiter.check_rate_limit("test", max_requests=5, window_seconds=60)

    assert allowed is True
    assert info["current"] == 1
    assert limiter._available is True
    assert limiter._redis is recovered


@pytest.mark.asyncio
@pytest.mark.parametrize("path", sorted(PUBLIC_AUTH_ENDPOINTS))
async def test_every_public_auth_endpoint_fails_closed_on_valkey_outage(path):
    middleware = RateLimitMiddleware(lambda scope, receive, send: None)
    middleware.limiter._available = False
    middleware.limiter._retry_after = time.monotonic() + 60
    settings = SimpleNamespace(APP_ENV="production")

    async def call_next(request):
        return Response("ok")

    with patch("app.core.config.get_settings", return_value=settings):
        response = await middleware.dispatch(_request(path), call_next)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"


@pytest.mark.asyncio
async def test_non_auth_route_stays_available_on_valkey_outage():
    middleware = RateLimitMiddleware(lambda scope, receive, send: None)
    middleware.limiter._available = False
    middleware.limiter._retry_after = time.monotonic() + 60
    settings = SimpleNamespace(APP_ENV="production")
    calls = []

    async def call_next(request):
        calls.append(request.url.path)
        return Response("ok")

    with patch("app.core.config.get_settings", return_value=settings):
        internal_response = await middleware.dispatch(_request("/api/v1/internal/task"), call_next)

    assert internal_response.status_code == 200
    assert calls == ["/api/v1/internal/task"]


@pytest.mark.asyncio
async def test_public_auth_ignores_forged_tenant_and_enforces_all_windows():
    middleware = RateLimitMiddleware(lambda scope, receive, send: None)
    middleware.limiter.check_rate_limit = AsyncMock(
        side_effect=[
            (True, {"remaining": 1, "reset": 10, "limit": 3, "current": 1}),
            (True, {"remaining": 4, "reset": 60, "limit": 5, "current": 1}),
            (True, {"remaining": 19, "reset": 3600, "limit": 20, "current": 1}),
        ]
    )
    settings = SimpleNamespace(APP_ENV="production")

    async def call_next(request):
        return Response("ok")

    forged_jwt = "e30.eyJ0ZW5hbnRfaWQiOiJmb3JnZWQtdGVuYW50In0.signature"
    with patch("app.core.config.get_settings", return_value=settings):
        response = await middleware.dispatch(
            _request("/api/v1/auth/login", authorization=f"Bearer {forged_jwt}"),
            call_next,
        )

    assert response.status_code == 200
    assert middleware.limiter.check_rate_limit.await_count == 3
    assert middleware.limiter.check_rate_limit.await_args_list == [
        (("rate_limit:/api/v1/auth/login:ip:127.0.0.1:burst", 3, 10),),
        (("rate_limit:/api/v1/auth/login:ip:127.0.0.1:minute", 5, 60),),
        (("rate_limit:/api/v1/auth/login:ip:127.0.0.1:hour", 20, 3600),),
    ]
