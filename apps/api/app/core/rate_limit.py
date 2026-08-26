"""Rate limiting middleware — Redis-based token bucket."""
from __future__ import annotations

import hashlib
import logging
import secrets
import time
from collections.abc import Callable

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class RateLimitConfig:
    """Rate limit configuration."""

    def __init__(
        self,
        requests_per_minute: int = 60,
        requests_per_hour: int = 1000,
        burst_size: int = 20,
    ):
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        self.burst_size = burst_size


# Default rate limits per endpoint pattern
RATE_LIMITS: dict[str, RateLimitConfig] = {
    "/api/v1/auth/login": RateLimitConfig(requests_per_minute=5, requests_per_hour=20, burst_size=3),
    "/api/v1/auth/register": RateLimitConfig(requests_per_minute=3, requests_per_hour=10, burst_size=2),
    "/api/v1/auth/refresh": RateLimitConfig(requests_per_minute=10, requests_per_hour=100, burst_size=5),
    "/api/v1/auth/check-code": RateLimitConfig(requests_per_minute=30, requests_per_hour=120, burst_size=15),
    "/api/v1/auth/superadmin-login": RateLimitConfig(requests_per_minute=5, requests_per_hour=20, burst_size=3),
    "/api/v1/auth/register-by-telegram": RateLimitConfig(requests_per_minute=3, requests_per_hour=10, burst_size=2),
    "/api/v1/auth/demo-login": RateLimitConfig(requests_per_minute=3, requests_per_hour=10, burst_size=2),
    "/api/v1/tenants/register/request-code": RateLimitConfig(requests_per_minute=3, requests_per_hour=10, burst_size=2),
    "/api/v1/tenants/register": RateLimitConfig(requests_per_minute=3, requests_per_hour=10, burst_size=2),
    "/api/v1/auth/generate-code": RateLimitConfig(requests_per_minute=10, requests_per_hour=60, burst_size=5),
    "/api/v1/auth/email/request-code": RateLimitConfig(requests_per_minute=5, requests_per_hour=20, burst_size=3),
    "/api/v1/auth/email/verify-code": RateLimitConfig(requests_per_minute=10, requests_per_hour=60, burst_size=5),
    "/api/v1/invitations/": RateLimitConfig(requests_per_minute=10, requests_per_hour=60, burst_size=5),
    "/api/v1/kiosks/": RateLimitConfig(requests_per_minute=20, requests_per_hour=200, burst_size=5),
    "/api/v1/assignment-access/": RateLimitConfig(requests_per_minute=10, requests_per_hour=60, burst_size=5),
    "/api/v1/candidate-assessment/": RateLimitConfig(requests_per_minute=20, requests_per_hour=120, burst_size=5),
    "/api/v1/public/leads": RateLimitConfig(requests_per_minute=5, requests_per_hour=20, burst_size=3),
    "/api/v1/ai/generate-course": RateLimitConfig(requests_per_minute=2, requests_per_hour=10, burst_size=1),
    "/api/v1/quizzes": RateLimitConfig(requests_per_minute=30, requests_per_hour=500, burst_size=10),
    "/api/v1/documents/upload": RateLimitConfig(requests_per_minute=10, requests_per_hour=100, burst_size=5),
    "default": RateLimitConfig(requests_per_minute=60, requests_per_hour=1000, burst_size=20),
}

# These endpoints can be called before a user has an authenticated session.
# When Valkey is unavailable they must fail closed so an outage cannot turn
# brute-force protection off. Authenticated/internal routes keep operating.
PUBLIC_AUTH_ENDPOINTS = frozenset(
    {
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/refresh",
        "/api/v1/auth/check-code",
        "/api/v1/auth/superadmin-login",
        "/api/v1/auth/register-by-telegram",
        "/api/v1/auth/demo-login",
        "/api/v1/auth/generate-code",
        "/api/v1/auth/email/request-code",
        "/api/v1/auth/email/verify-code",
        "/api/v1/tenants/register",
        "/api/v1/tenants/register/request-code",
    }
)
PUBLIC_AUTH_PREFIXES = ("/api/v1/invitations/",)
PUBLIC_CAPABILITY_PREFIXES = (
    "/api/v1/assignment-access/",
    "/api/v1/candidate-assessment/",
)


def _is_public_auth_path(path: str) -> bool:
    return (
        path in PUBLIC_AUTH_ENDPOINTS
        or path.startswith(PUBLIC_AUTH_PREFIXES)
        or path.startswith(PUBLIC_CAPABILITY_PREFIXES)
        or path == "/api/v1/public/leads"
        or path.startswith("/api/v1/kiosks/")
    )


def _rate_limit_bucket_path(path: str) -> str:
    if path.startswith("/api/v1/invitations/"):
        token = path.removeprefix("/api/v1/invitations/").split("/", 1)[0]
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        action = "request-code" if path.endswith("/request-code") else "accept" if path.endswith("/accept") else "view"
        return f"/api/v1/invitations/{token_hash}/{action}"
    if path.startswith("/api/v1/kiosks/"):
        suffix = path.removeprefix("/api/v1/kiosks/")
        token = suffix.split("/", 1)[0]
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        action = "identify" if suffix.endswith("/identify") else "view"
        return f"/api/v1/kiosks/{token_hash}/{action}"
    if path.startswith("/api/v1/assignment-access/"):
        token = path.removeprefix("/api/v1/assignment-access/").split("/", 1)[0]
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        return f"/api/v1/assignment-access/{token_hash}/exchange"
    if path.startswith("/api/v1/candidate-assessment/"):
        suffix = path.removeprefix("/api/v1/candidate-assessment/")
        if suffix == "submit":
            return "/api/v1/candidate-assessment/submit"
        token = suffix.split("/", 1)[0]
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        return f"/api/v1/candidate-assessment/{token_hash}/exchange"
    return path


class RateLimiter:
    """Redis-based rate limiter using sliding window."""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/1",
        unavailable_retry_seconds: float = 5.0,
    ):
        self.redis_url = redis_url
        self.unavailable_retry_seconds = unavailable_retry_seconds
        self._redis = None
        self._available = True
        self._retry_after = 0.0

    def _mark_unavailable(self) -> None:
        self._available = False
        self._redis = None
        self._retry_after = time.monotonic() + self.unavailable_retry_seconds

    async def _get_redis(self):
        if not self._available and time.monotonic() < self._retry_after:
            return None
        if self._redis is not None:
            return self._redis
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(self.redis_url, decode_responses=True)
            await client.ping()
            self._redis = client
            self._available = True
            self._retry_after = 0.0
            return client
        except Exception:
            logger.warning("Valkey unavailable; rate limiting state cannot be read")
            self._mark_unavailable()
            return None

    async def check_rate_limit(
        self, key: str, max_requests: int, window_seconds: int
    ) -> tuple[bool, dict]:
        """
        Check rate limit using sliding window.
        Returns (is_allowed, info_dict).
        """
        redis = await self._get_redis()
        if redis is None:
            return False, {
                "remaining": 0,
                "reset": int(time.time() + window_seconds),
                "limit": max_requests,
                "current": 0,
                "unavailable": True,
            }

        try:
            now = time.time()
            window_start = now - window_seconds

            pipe = redis.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zadd(key, {f"{now}:{secrets.token_hex(8)}": now})
            pipe.zcard(key)
            pipe.expire(key, window_seconds)
            results = await pipe.execute()

            current_count = results[2]
            remaining = max(0, max_requests - current_count)
            reset_at = int(now + window_seconds)

            is_allowed = current_count <= max_requests

            return is_allowed, {
                "remaining": remaining,
                "reset": reset_at,
                "limit": max_requests,
                "current": current_count,
            }
        except Exception:
            logger.warning("Valkey rate limit check failed; limiter state unavailable")
            self._mark_unavailable()
            return False, {
                "remaining": 0,
                "reset": int(time.time() + window_seconds),
                "limit": max_requests,
                "current": 0,
                "unavailable": True,
            }

    async def get_rate_limit_config(self, path: str) -> RateLimitConfig:
        """Get rate limit config for a path."""
        exact_config = RATE_LIMITS.get(path)
        if exact_config is not None:
            return exact_config

        for pattern, config in RATE_LIMITS.items():
            if pattern != "default" and pattern not in PUBLIC_AUTH_ENDPOINTS and path.startswith(pattern):
                return config
        return RATE_LIMITS["default"]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware for FastAPI."""

    def __init__(self, app, redis_url: str = "redis://localhost:6379/1"):
        super().__init__(app)
        self.limiter = RateLimiter(redis_url)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        from app.core.config import get_settings

        # Rate-limit behavior has focused unit coverage. Integration tests use
        # many logins from one synthetic IP and must remain deterministic.
        if get_settings().APP_ENV == "test":
            return await call_next(request)

        # Fast-path: skip rate limiting for docs/health
        if request.url.path in ("/health", "/api/v1/health", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path
        info = {"remaining": 0, "reset": 0, "limit": 0, "current": 0}

        principal_bucket = _verified_principal_bucket(request)
        is_public_auth = _is_public_auth_path(path)

        try:
            config = await self.limiter.get_rate_limit_config(path)
            if is_public_auth or not principal_bucket:
                # Public authentication must always use the network identity.
                # Never trust a tenant_id peeked from an unsigned JWT here:
                # attackers could forge it to split a brute-force quota.
                key = f"rate_limit:{_rate_limit_bucket_path(path)}:ip:{client_ip}"
            else:
                key = f"rate_limit:{path}:principal:{principal_bucket}"

            checks = (
                ("burst", config.burst_size, 10),
                ("minute", config.requests_per_minute, 60),
                ("hour", config.requests_per_hour, 3600),
            )
            results: list[tuple[str, bool, dict]] = []
            for window_name, limit, window_seconds in checks:
                allowed, window_info = await self.limiter.check_rate_limit(
                    f"{key}:{window_name}",
                    limit,
                    window_seconds,
                )
                results.append((window_name, allowed, window_info))

            unavailable = next(
                (window_info for _, _, window_info in results if window_info.get("unavailable")),
                None,
            )
            denied = next(
                (window_info for _, allowed, window_info in results if not allowed),
                None,
            )
            minute_info = next(
                window_info for window_name, _, window_info in results if window_name == "minute"
            )
            if unavailable is not None:
                is_allowed = False
                info = unavailable
            elif denied is not None:
                is_allowed = False
                info = denied
            else:
                is_allowed = True
                info = minute_info
        except Exception:
            # A configuration or Redis failure must not disable brute-force
            # protection on public auth endpoints. Other routes remain
            # available while the limiter is degraded.
            is_allowed = not is_public_auth
            info["unavailable"] = True

        if is_public_auth and info.get("unavailable"):
            retry_after = 5
            return JSONResponse(
                status_code=503,
                content={"detail": "Authentication service temporarily unavailable"},
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(info.get("limit", 0)),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(info.get("reset", 0)),
                },
            )

        if info.get("unavailable") and not is_public_auth:
            is_allowed = True

        if not is_allowed:
            logger.warning(
                "Rate limit exceeded for tenant=%s ip=%s on %s",
                "verified" if principal_bucket else "<none>",
                client_ip,
                path,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded",
                    "retry_after": max(1, info.get("reset", 0) - int(time.time())),
                },
                headers={
                    "X-RateLimit-Limit": str(info.get("limit", 0)),
                    "X-RateLimit-Remaining": str(info.get("remaining", 0)),
                    "X-RateLimit-Reset": str(info.get("reset", 0)),
                    "Retry-After": str(max(1, info.get("reset", 0) - int(time.time()))),
                },
            )

        response = await call_next(request)

        response.headers["X-RateLimit-Limit"] = str(info.get("limit", 0))
        response.headers["X-RateLimit-Remaining"] = str(info.get("remaining", 0))
        response.headers["X-RateLimit-Reset"] = str(info.get("reset", 0))

        return response


def _verified_principal_bucket(request: Request) -> str | None:
    """Return an opaque bucket only for a cryptographically valid access JWT."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[len("Bearer ") :].strip()
    try:
        from app.core.auth import decode_token

        payload = decode_token(token)
    except HTTPException:
        return None
    if payload.get("type") not in {"access", "kiosk_access"}:
        return None
    subject = payload.get("sub")
    if not subject:
        return None
    tenant_id = payload.get("tenant_id") or "global"
    canonical = f"{tenant_id}:{subject}:{payload.get('type')}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
