"""One-attempt managed CLI connector client; local preparation is not token counting."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import httpx

from app.modules.admin.model_routing.chatgpt_reserve import configuration_blocker
from app.modules.ai.direct_luna_api import LunaUsage
from app.modules.ai.direct_luna_responses_client import ResponsesResult
from app.modules.ai.source_first_response import parse_source_first_response

MODEL = "gpt-5.6-luna"
MAX_INPUT_BYTES = 524288
MAX_RESPONSE_BYTES = 2097152
MAX_CONTENT_BYTES = 262144


class ManagedLunaError(RuntimeError):
    """Sanitized connector failure; after dispatch, the outcome is unknown."""


class ManagedLunaClient:
    def __init__(self, *, base_url: str, api_key: str, tenant_id: UUID, user_id: UUID, job_id: str,
                 credential_revision: str, deadline_seconds: float = 60.0):
        config = SimpleNamespace(CHATGPT_RESERVE_URL=base_url, CHATGPT_RESERVE_TOKEN=api_key,
                                 CHATGPT_RESERVE_MODEL=MODEL, CHATGPT_RESERVE_AUTH_MODE="codex_cli")
        if (not isinstance(base_url, str) or not isinstance(api_key, str) or not api_key.strip()
                or not isinstance(tenant_id, UUID) or not isinstance(user_id, UUID)
                or not isinstance(job_id, str) or not job_id.strip()
                or not isinstance(credential_revision, str) or not credential_revision.strip()
                or isinstance(deadline_seconds, bool) or not isinstance(deadline_seconds, int | float)
                or not 0 < deadline_seconds <= 120 or configuration_blocker(cast(Any, config)) is not None):
            raise ValueError("managed_luna_config_invalid")
        base = base_url.rstrip("/")
        self._url = (base if base.endswith("/v1") else base + "/v1") + "/chat/completions"
        self._token = api_key
        self._revision = credential_revision
        self._scope = (tenant_id, user_id, job_id)
        self._deadline = float(deadline_seconds)
        self._prepared: dict[object, bytes] = {}
        self._closed = False

    def __repr__(self) -> str:
        return "ManagedLunaClient(<redacted>)"

    @property
    def generation_deadline_seconds(self) -> float:
        return self._deadline

    def cache_fingerprint(self) -> str:
        policy = json.dumps(["managed-cli-v1", self._url, MODEL, "low", "json-object",
                             self._deadline, self._revision], separators=(",", ":")).encode()
        return hmac.new(self._token.encode(), policy, hashlib.sha256).hexdigest()

    async def _check(self, checkpoint: Callable[[], Awaitable[bool]]) -> None:
        allowed = False
        try:
            allowed = callable(checkpoint) and await checkpoint() is True
        except Exception:
            pass
        if not allowed:
            raise ManagedLunaError("managed_luna_ownership_unverified")

    async def prepare(self, messages: list[dict[str, str]], *, max_output_tokens: int,
                      ownership_checkpoint: Callable[[], Awaitable[bool]]) -> object:
        if self._closed:
            raise ManagedLunaError("managed_luna_closed")
        if (not isinstance(messages, list) or not 1 <= len(messages) <= 100
                or any(not isinstance(m, dict) or set(m) != {"role", "content"}
                       or m.get("role") not in {"system", "developer", "user", "assistant"}
                       or not isinstance(m.get("content"), str) for m in messages)
                or type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 32768):
            raise ValueError("managed_luna_request_invalid")
        request = {"model": MODEL, "messages": messages, "temperature": 0.2,
                   "max_tokens": max_output_tokens, "response_format": {"type": "json_object"}}
        encoded = json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        # The CLI runner reserializes with json.dumps default separators.
        if len(json.dumps(request, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_INPUT_BYTES:
            raise ValueError("managed_luna_request_too_large")
        await self._check(ownership_checkpoint)
        if self._closed:
            raise ManagedLunaError("managed_luna_closed")
        capability = object()
        self._prepared[capability] = encoded
        return capability

    def discard(self, capability: object) -> None:
        try:
            self._prepared.pop(capability, None)
        except TypeError:
            pass

    def close(self) -> None:
        self._prepared.clear()
        self._token = ""
        self._closed = True

    async def invoke(self, capability: object, *, tenant_id: UUID, user_id: UUID, job_id: str,
                     ownership_checkpoint: Callable[[], Awaitable[bool]], stage_id: str | None = None) -> ResponsesResult:
        try:
            payload = self._prepared.pop(capability, None)
        except TypeError:
            payload = None
        if (payload is None or self._closed or (tenant_id, user_id, job_id) != self._scope
                or stage_id is not None and (not isinstance(stage_id, str) or not re.fullmatch(r"[0-9a-f]{64}", stage_id))):
            raise ManagedLunaError("managed_luna_capability_invalid")
        await self._check(ownership_checkpoint)
        if self._closed:
            raise ManagedLunaError("managed_luna_closed")
        failed = False
        raw = bytearray()
        try:
            async with asyncio.timeout(self._deadline):
                async with httpx.AsyncClient(timeout=self._deadline, follow_redirects=False, trust_env=False) as client:
                    if self._closed:
                        raise ManagedLunaError("managed_luna_closed")
                    async with client.stream("POST", self._url, content=payload,
                        headers={"Authorization": "Bearer " + self._token, "Content-Type": "application/json",
                                 "Accept-Encoding": "identity"}) as response:
                        if response.status_code != 200 or response.headers.get("content-encoding", "identity").lower() != "identity":
                            failed = True
                        else:
                            async for chunk in response.aiter_raw():
                                raw.extend(chunk)
                                if len(raw) > MAX_RESPONSE_BYTES:
                                    failed = True
                                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            failed = True
        if failed:
            raise ManagedLunaError("managed_luna_outcome_unknown")
        try:
            body = parse_source_first_response(raw.decode("utf-8"))
            choices = body.get("choices")
            if body.get("model") != MODEL or not isinstance(choices, list) or len(choices) != 1:
                raise ValueError
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if (not isinstance(message, dict) or set(message) not in ({"content"}, {"role", "content"})
                    or message.get("role", "assistant") != "assistant" or not isinstance(message.get("content"), str)):
                raise ValueError
            if len(message["content"].encode("utf-8")) > MAX_CONTENT_BYTES:
                raise ValueError
            content = parse_source_first_response(message["content"])
            usage = body.get("usage")
            if not isinstance(usage, dict):
                raise ValueError
            incoming, outgoing = usage.get("prompt_tokens"), usage.get("completion_tokens")
            limit = json.loads(payload)["max_tokens"]
            if type(incoming) is not int or incoming < 0 or type(outgoing) is not int or not 0 <= outgoing <= limit:
                raise ValueError
            result = ResponsesResult(content=content, model=MODEL, usage=LunaUsage(incoming, outgoing, None, None))
        except Exception:
            raise ManagedLunaError("managed_luna_response_invalid") from None
        return result
