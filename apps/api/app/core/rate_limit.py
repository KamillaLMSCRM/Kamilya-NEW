"""Rate limiting middleware — Redis-based token bucket."""
from __future__ import annotations

import time
import logging
from typing import Callable

from fastapi import Request, Response
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
    "/api/v1/ai/generate-course": RateLimitConfig(requests_per_minute=2, requests_per_hour=10, burst_size=1),
    "/api/v1/quizzes": RateLimitConfig(requests_per_minute=30, requests_per_hour=500, burst_size=10),
    "/api/v1/documents/upload": RateLimitConfig(requests_per_minute=10, requests_per_hour=100, burst_size=5),
    "default": RateLimitConfig(requests_per_minute=60, requests_per_hour=1000, burst_size=20),
}


class RateLimiter:
    """Redis-based rate limiter using sliding window."""

    def __init__(self, redis_url: str = "redis://localhost:6379/1"):
        self.redis_url = redis_url
        self._redis = None

    async def _get_redis(self):
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
            except ImportError:
                logger.warning("Redis not available, rate limiting disabled")
                return None
        return self._redis

    async def check_rate_limit(
        self, key: str, max_requests: int, window_seconds: int
    ) -> tuple[bool, dict]:
        """
        Check rate limit using sliding window.
        Returns (is_allowed, info_dict).
        """
        redis = await self._get_redis()
        if redis is None:
            return True, {"remaining": max_requests, "reset": 0}

        now = time.time()
        window_start = now - window_seconds

        pipe = redis.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zadd(key, {str(now): now})
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

    async def get_rate_limit_config(self, path: str) -> RateLimitConfig:
        """Get rate limit config for a path."""
        for pattern, config in RATE_LIMITS.items():
            if pattern != "default" and path.startswith(pattern):
                return config
        return RATE_LIMITS["default"]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware for FastAPI."""

    def __init__(self, app, redis_url: str = "redis://localhost:6379/1"):
        super().__init__(app)
        self.limiter = RateLimiter(redis_url)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip rate limiting for health checks and static files
        if request.url.path in ("/health", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        # Get client identifier (IP + user ID if available)
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path

        # Check rate limit
        config = await self.limiter.get_rate_limit_config(path)
        key = f"rate_limit:{path}:{client_ip}"

        is_allowed, info = await self.limiter.check_rate_limit(
            key, config.requests_per_minute, 60
        )

        if not is_allowed:
            logger.warning(f"Rate limit exceeded for {client_ip} on {path}")
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded",
                    "retry_after": info["reset"] - int(time.time()),
                },
                headers={
                    "X-RateLimit-Limit": str(info["limit"]),
                    "X-RateLimit-Remaining": str(info["remaining"]),
                    "X-RateLimit-Reset": str(info["reset"]),
                    "Retry-After": str(max(1, info["reset"] - int(time.time()))),
                },
            )

        response = await call_next(request)

        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(info["limit"])
        response.headers["X-RateLimit-Remaining"] = str(info["remaining"])
        response.headers["X-RateLimit-Reset"] = str(info["reset"])

        return response
