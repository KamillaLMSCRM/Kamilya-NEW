"""Bounded, job-scoped Redis checkpoints for validated source-map batches."""
from __future__ import annotations

import asyncio
import re
from typing import Any
from uuid import UUID

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_NAMESPACE = "ai:source-map-checkpoint:v1"
_MAX_BATCHES = 64
_TTL_SECONDS = 60 * 60
_OPERATION_TIMEOUT_SECONDS = 1.0
_MAX_CONTENT_BYTES = 32 * 1024
_WRITE_LUA = """
local exists = redis.call('HEXISTS', KEYS[1], ARGV[1])
if exists == 1 or redis.call('HLEN', KEYS[1]) < tonumber(ARGV[3]) then
    redis.call('HSET', KEYS[1], ARGV[1], ARGV[2])
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4]))
    return 1
end
return 0
"""


class SourceMapCheckpointStore:
    """Store same-job batch checkpoints in one bounded Redis hash."""

    def __init__(
        self,
        tenant_id: str,
        job_id: str,
        config_digest: str,
        client: Any | None = None,
    ) -> None:
        self._tenant_id = self._validate_uuid("tenant_id", tenant_id)
        self._job_id = self._validate_uuid("job_id", job_id)
        self._config_digest = self._validate_digest("config_digest", config_digest)
        self._client = client
        self._owns_client = client is None
        self._unavailable = False

    @staticmethod
    def _validate_uuid(name: str, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a canonical UUID")
        try:
            parsed = UUID(value)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError(f"{name} must be a canonical UUID") from exc
        if str(parsed) != value:
            raise ValueError(f"{name} must be a canonical UUID")
        return value

    @staticmethod
    def _validate_digest(name: str, value: str) -> str:
        if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
            raise ValueError(f"{name} must be a lowercase SHA256 digest")
        return value

    def _key(self) -> str:
        return (
            f"{_NAMESPACE}:{self._tenant_id}:{self._job_id}:"
            f"{self._config_digest}"
        )

    def _redis(self) -> Any:
        if self._client is None:
            import redis.asyncio as aioredis

            from app.core.config import get_settings

            self._client = aioredis.Redis.from_url(
                get_settings().REDIS_URL,
                decode_responses=False,
                socket_connect_timeout=_OPERATION_TIMEOUT_SECONDS,
                socket_timeout=_OPERATION_TIMEOUT_SECONDS,
            )
        return self._client

    async def load(self, batch_digest: str) -> str | None:
        """Return an opaque matching checkpoint, or a safe miss."""
        batch_digest = self._validate_digest("batch_digest", batch_digest)
        if self._unavailable:
            return None
        try:
            raw = await asyncio.wait_for(
                self._redis().hget(self._key(), batch_digest),
                timeout=_OPERATION_TIMEOUT_SECONDS,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            self._unavailable = True
            return None

        if isinstance(raw, str):
            try:
                raw = raw.encode("utf-8")
            except UnicodeEncodeError:
                return None
        if not isinstance(raw, bytes) or len(raw) > _MAX_CONTENT_BYTES + 65:
            return None
        expected_prefix = batch_digest.encode("ascii") + b"\n"
        if not raw.startswith(expected_prefix):
            return None
        try:
            content = raw[len(expected_prefix) :].decode("utf-8")
        except UnicodeDecodeError:
            return None
        if len(content.encode("utf-8")) > _MAX_CONTENT_BYTES:
            return None
        return content

    async def save(self, batch_digest: str, content: str) -> None:
        """Atomically write a field if the bounded hash admits it."""
        batch_digest = self._validate_digest("batch_digest", batch_digest)
        if self._unavailable:
            return
        if not isinstance(content, str):
            raise ValueError("content must be text")
        encoded_content = content.encode("utf-8")
        if len(encoded_content) > _MAX_CONTENT_BYTES:
            raise ValueError("content exceeds the 32 KiB checkpoint limit")
        payload = batch_digest.encode("ascii") + b"\n" + encoded_content
        try:
            await asyncio.wait_for(
                self._redis().eval(
                    _WRITE_LUA,
                    1,
                    self._key(),
                    batch_digest,
                    payload,
                    _MAX_BATCHES,
                    _TTL_SECONDS,
                ),
                timeout=_OPERATION_TIMEOUT_SECONDS,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            self._unavailable = True
            return

    async def clear(self) -> None:
        """Best-effort cleanup of this job/config's exact hash key."""
        try:
            await asyncio.wait_for(
                self._redis().delete(self._key()), timeout=_OPERATION_TIMEOUT_SECONDS
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def aclose(self) -> None:
        """Close only a lazily created client; injected clients remain caller-owned."""
        if not self._owns_client or self._client is None:
            return
        try:
            await asyncio.wait_for(
                self._client.aclose(), timeout=_OPERATION_TIMEOUT_SECONDS
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return
        finally:
            self._client = None
