"""Unwired GPT-6 Luna adapter. No retry, routing or context-fit guarantee."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.modules.ai.source_first_response import parse_source_first_response

ENDPOINT = "https://api.openai.com/v1/chat/completions"
MODEL = "gpt-6-luna"
CONTEXT_WINDOW = 1_050_000
MAX_OUTPUT = 128_000
TIMEOUT = 600.0
MAX_RESPONSE_BYTES = 64 * 1024 * 1024


class LunaAdapterError(RuntimeError):
    """Sanitized failure; transport outcomes must be treated as unknown."""


@dataclass(frozen=True)
class LunaUsage:
    input_tokens: int | None
    output_tokens: int | None
    cached_input_tokens: int | None
    reasoning_tokens: int | None


@dataclass(frozen=True, repr=False)
class LunaResult:
    model: str
    response: dict[str, Any]
    usage: LunaUsage

    def __repr__(self) -> str:
        return "LunaResult(<redacted>)"


def _count(container: Any, name: str) -> int | None:
    value = container.get(name) if isinstance(container, dict) else None
    return value if type(value) is int and value >= 0 else None


@dataclass(repr=False)
class DirectLunaAdapter:
    api_key: str = field(repr=False)
    deadline_seconds: float = 600.0

    def __repr__(self) -> str:
        return "DirectLunaAdapter(<redacted>)"

    async def invoke(self, messages: list[dict[str, str]], *, max_completion_tokens: int) -> LunaResult:
        if (not isinstance(self.api_key, str) or not self.api_key.strip()
                or isinstance(self.deadline_seconds, bool)
                or not isinstance(self.deadline_seconds, int | float) or not 0 < self.deadline_seconds <= 3600
                or type(max_completion_tokens) is not int or not 1 <= max_completion_tokens <= MAX_OUTPUT
                or not isinstance(messages, list) or not messages
                or any(not isinstance(row, dict) or set(row) != {"role", "content"}
                       or row.get("role") not in {"system", "developer", "user", "assistant"}
                       or not isinstance(row.get("content"), str) for row in messages)):
            raise LunaAdapterError("luna_request_invalid")
        payload = {"model": MODEL, "messages": [{"role": "system", "content": "Return a JSON object."},
                                              *[dict(row) for row in messages]], "reasoning_effort": "medium",
                   "max_completion_tokens": max_completion_tokens, "store": False,
                   "response_format": {"type": "json_object"}}
        failure: str | None = None
        data: Any = None
        try:
            async with asyncio.timeout(self.deadline_seconds):
                async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False, follow_redirects=False) as client:
                    async with client.stream("POST", ENDPOINT, headers={"Authorization": f"Bearer {self.api_key}",
                                                                  "Accept-Encoding": "identity"},
                                             json=payload) as response:
                        if response.status_code != 200:
                            failure = "luna_transport_outcome_unknown"
                        elif response.headers.get("Content-Encoding", "identity").strip().lower() != "identity":
                            failure = "luna_response_encoding_unknown"
                        else:
                            chunks: list[bytes] = []
                            size = 0
                            async for chunk in response.aiter_raw():
                                size += len(chunk)
                                if size > MAX_RESPONSE_BYTES:
                                    failure = "luna_response_too_large_outcome_unknown"
                                    break
                                chunks.append(chunk)
                            if failure is None:
                                data = parse_source_first_response(b"".join(chunks).decode("utf-8"))
        except (Exception, asyncio.CancelledError):
            failure = "luna_transport_outcome_unknown"
        if failure is not None:
            raise LunaAdapterError(failure)
        invalid = False
        result: LunaResult | None = None
        try:
            if not isinstance(data, dict) or data.get("model") != MODEL:
                raise ValueError
            choices = data.get("choices")
            if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                raise ValueError
            choice = choices[0]
            message = choice.get("message")
            if (choice.get("finish_reason") != "stop" or not isinstance(message, dict)
                    or message.get("refusal") or not isinstance(message.get("content"), str)):
                raise ValueError
            parsed = parse_source_first_response(message["content"])
            usage = data.get("usage")
            details_in = usage.get("prompt_tokens_details") if isinstance(usage, dict) else None
            details_out = usage.get("completion_tokens_details") if isinstance(usage, dict) else None
            result = LunaResult(model=MODEL, response=parsed, usage=LunaUsage(
                _count(usage, "prompt_tokens"), _count(usage, "completion_tokens"),
                _count(details_in, "cached_tokens"), _count(details_out, "reasoning_tokens")))
        except Exception:
            invalid = True
        if invalid or result is None:
            raise LunaAdapterError("luna_response_invalid")
        return result
