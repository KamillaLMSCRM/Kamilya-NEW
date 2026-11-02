"""Unwired two-phase Responses client; count capability is process-local and one-use.

The caller must provide an authenticated ownership checkpoint before invocation.
No routing, persistence, accounting or retry policy is supplied by this module.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from app.modules.ai.direct_luna_api import MAX_RESPONSE_BYTES, TIMEOUT, LunaUsage, _count
from app.modules.ai.direct_luna_responses_contract import (
    COUNT_ENDPOINT,
    GENERATION_ENDPOINT,
    build_request,
    validate_count,
)
from app.modules.ai.source_first_response import parse_source_first_response

logger = logging.getLogger(__name__)


class ResponsesClientError(RuntimeError):
    """Sanitized error; generation errors indicate an unknown outcome."""


@dataclass(frozen=True, repr=False)
class ResponsesResult:
    content: dict[str, Any]
    model: str
    usage: LunaUsage

    def __repr__(self) -> str:
        return "ResponsesResult(<redacted>)"


class DirectLunaResponsesClient:
    def __init__(self, *, api_key: str, tenant_id: UUID, user_id: UUID, job_id: str,
                 deadline_seconds: float = 600.0, credential_revision: str = "synthetic-unset"):
        if (not isinstance(api_key, str) or not api_key.strip() or not isinstance(tenant_id, UUID)
                or not isinstance(user_id, UUID) or not isinstance(job_id, str) or not job_id.strip()
                or isinstance(deadline_seconds, bool) or not isinstance(deadline_seconds, int | float)
                or not 0 < deadline_seconds <= 3600 or not isinstance(credential_revision, str)
                or not credential_revision.strip()):
            raise ValueError("luna_responses_config_invalid")
        self._key = api_key
        self._credential_revision = credential_revision
        self._scope = (tenant_id, user_id, job_id)
        self._deadline = deadline_seconds
        self._prepared: dict[object, Any] = {}
        self._closed = False

    def cache_fingerprint(self) -> str:
        policy = ('responses-v1|gpt-6-luna|medium|json-object|store-false|max-output-8192|'
                  + self._credential_revision).encode('utf-8')
        return hmac.new(self._key.encode('utf-8'), policy, hashlib.sha256).hexdigest()

    def __repr__(self) -> str:
        return "DirectLunaResponsesClient(<redacted>)"

    async def _post(self, endpoint: str, payload: dict[str, Any], *, stage_id: str | None = None) -> str:
        failed = False
        raw: bytes = b""
        phase = "count" if endpoint == COUNT_ENDPOINT else "generation"
        status: int | None = None
        classification = "transport_unknown"
        try:
            job = str(UUID(self._scope[2]))
        except ValueError:
            job = "unknown"
        def record(event: str) -> None:
            try:
                logger.info("luna_transport job=%s stage=%s phase=%s event=%s status=%s classification=%s",
                            job, stage_id or "unknown", phase, event, status, classification)
            except Exception:
                pass
        record("attempt")
        try:
            async with asyncio.timeout(self._deadline):
                async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False, follow_redirects=False) as client:
                    if self._closed:
                        raise ResponsesClientError("luna_responses_client_closed")
                    async with client.stream("POST", endpoint, headers={"Authorization": f"Bearer {self._key}",
                        "Accept-Encoding": "identity"}, json=payload) as response:
                        status = response.status_code
                        classification = "http_status" if status != 200 else "invalid_or_incomplete_response"
                        if response.status_code != 200 or response.headers.get("content-encoding", "identity").strip().lower() != "identity":
                            failed = True
                        else:
                            parts: list[bytes] = []
                            size = 0
                            async for chunk in response.aiter_raw():
                                size += len(chunk)
                                if size > MAX_RESPONSE_BYTES:
                                    failed = True
                                    break
                                parts.append(chunk)
                            if not failed:
                                raw = b"".join(parts)
        except (Exception, asyncio.CancelledError):
            failed = True
        if failed:
            record("failed")
            raise ResponsesClientError("luna_responses_transport_unknown")
        try:
            text = raw.decode("utf-8")
        except UnicodeError:
            text = ""
        if not text:
            record("failed")
            raise ResponsesClientError("luna_responses_transport_unknown")
        classification = "body_received"
        record("received")
        return text

    async def _verify_ownership(self, checkpoint: Callable[[], Awaitable[bool]]) -> None:
        allowed = False
        try:
            if callable(checkpoint):
                allowed = await checkpoint() is True
        except (Exception, asyncio.CancelledError):
            pass
        if not allowed:
            raise ResponsesClientError("luna_responses_ownership_unverified")

    async def prepare(self, messages: list[dict[str, str]], *, max_output_tokens: int,
                      ownership_checkpoint: Callable[[], Awaitable[bool]]) -> object:
        if self._closed:
            raise ResponsesClientError("luna_responses_client_closed")
        request = build_request(messages, max_output_tokens=max_output_tokens)
        await self._verify_ownership(ownership_checkpoint)
        if self._closed:
            raise ResponsesClientError("luna_responses_client_closed")
        raw = await self._post(COUNT_ENDPOINT, request.count_payload())
        count_valid = True
        try:
            validate_count(request, raw_response=raw, request_sha256=request.input_sha256)
        except (TypeError, ValueError):
            count_valid = False
        if not count_valid:
            raise ResponsesClientError("luna_responses_count_unverified")
        if self._closed:
            raise ResponsesClientError("luna_responses_client_closed")
        capability = object()
        self._prepared[capability] = (request, self._scope)
        return capability

    def discard(self, capability: object) -> None:
        """Forget a prepared request without invoking generation."""
        try:
            self._prepared.pop(capability, None)
        except TypeError:
            pass

    def close(self) -> None:
        """Forget every unconsumed request and erase the in-process key reference."""
        self._prepared.clear()
        self._key = ""
        self._closed = True

    async def invoke(self, capability: object, *, tenant_id: UUID, user_id: UUID, job_id: str,
                     ownership_checkpoint: Callable[[], Awaitable[bool]], stage_id: str | None = None) -> ResponsesResult:
        # Pop before any await: concurrent callers cannot spend the same count twice.
        prepared = self._prepared.pop(capability, None)
        if prepared is None:
            raise ResponsesClientError("luna_responses_capability_invalid")
        request, scope = prepared
        if scope != self._scope or (tenant_id, user_id, job_id) != scope or not callable(ownership_checkpoint):
            raise ResponsesClientError("luna_responses_capability_invalid")
        if stage_id is not None and (not isinstance(stage_id, str) or not re.fullmatch(r"[0-9a-f]{64}", stage_id)):
            raise ResponsesClientError("luna_responses_stage_identity_invalid")
        await self._verify_ownership(ownership_checkpoint)
        if self._closed:
            raise ResponsesClientError("luna_responses_client_closed")
        if stage_id is None:
            raw = await self._post(GENERATION_ENDPOINT, request.generation_payload())
        else:
            raw = await self._post(GENERATION_ENDPOINT, request.generation_payload(), stage_id=stage_id)
        invalid = False
        result: ResponsesResult | None = None
        validation_stage = "envelope_schema"
        try:
            body = parse_source_first_response(raw)
            validation_stage = "model"
            if body.get("model") != "gpt-6-luna":
                raise ValueError
            validation_stage = "completion_status"
            if body.get("status") != "completed":
                raise ValueError
            validation_stage = "output_shape"
            outputs = body.get("output")
            if not isinstance(outputs, list) or not outputs:
                raise ValueError
            messages = []
            for part in outputs:
                if not isinstance(part, dict):
                    raise ValueError
                if part.get("type") == "reasoning":
                    continue
                if (part.get("type") != "message" or part.get("role") != "assistant"
                        or part.get("status") != "completed" or not isinstance(part.get("content"), list)):
                    raise ValueError
                messages.append(part)
            if len(messages) != 1 or len(messages[0]["content"]) != 1:
                raise ValueError
            item = messages[0]["content"][0]
            if isinstance(item, dict) and item.get("type") == "refusal":
                validation_stage = "refusal"
                raise ValueError
            if not isinstance(item, dict) or item.get("type") != "output_text" or not isinstance(item.get("text"), str):
                raise ValueError
            texts = [item["text"]]
            validation_stage = "output_json"
            content = parse_source_first_response(texts[0])
            usage = body.get("usage")
            input_details = usage.get("input_tokens_details") if isinstance(usage, dict) else None
            output_details = usage.get("output_tokens_details") if isinstance(usage, dict) else None
            result = ResponsesResult(content=content, model="gpt-6-luna", usage=LunaUsage(
                _count(usage, "input_tokens"), _count(usage, "output_tokens"),
                _count(input_details, "cached_tokens"), _count(output_details, "reasoning_tokens")))
        except Exception:
            invalid = True
        if invalid or result is None:
            try:
                try:
                    job = str(UUID(job_id))
                except ValueError:
                    job = "unknown"
                logger.info("luna_generation_validation job=%s stage=%s classification=%s", job,
                            stage_id or "unknown", validation_stage)
            except Exception:
                pass
            raise ResponsesClientError("luna_responses_generation_unverified")
        return result
