"""Unwired Responses payload/count contract; no transport, claims or model calls.

Count and generation share immutable input-affecting fields; generation also reserves output. The caller must
validate current official API support and preserve tenant/data-flow authority.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, cast

from app.modules.ai.direct_luna_api import CONTEXT_WINDOW, MAX_OUTPUT, MODEL
from app.modules.ai.source_first_response import parse_source_first_response

COUNT_ENDPOINT = "https://api.openai.com/v1/responses/input_tokens"
GENERATION_ENDPOINT = "https://api.openai.com/v1/responses"


@dataclass(frozen=True, repr=False)
class ResponsesRequest:
    _canonical: bytes = field(repr=False)
    input_sha256: str
    max_output_tokens: int

    def __repr__(self) -> str:
        return "ResponsesRequest(<redacted>)"

    def count_payload(self) -> dict[str, Any]:
        payload = self.generation_payload()
        del payload["max_output_tokens"]
        del payload["store"]
        return payload

    def generation_payload(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self._canonical))


def build_request(messages: list[dict[str, str]], *, max_output_tokens: int) -> ResponsesRequest:
    if (type(max_output_tokens) is not int or not 1 <= max_output_tokens <= MAX_OUTPUT
            or not isinstance(messages, list) or not messages
            or any(not isinstance(item, dict) or set(item) != {"role", "content"}
                   or item.get("role") not in {"system", "developer", "user", "assistant"}
                   or not isinstance(item.get("content"), str) for item in messages)):
        raise ValueError("luna_responses_request_invalid")
    payload = {"model": MODEL, "input": [{"role": "system", "content": "Return a JSON object."},
                                         *[dict(item) for item in messages]],
               "reasoning": {"effort": "medium"}, "text": {"format": {"type": "json_object"}},
               "max_output_tokens": max_output_tokens, "store": False}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return ResponsesRequest(_canonical=canonical, input_sha256=hashlib.sha256(canonical).hexdigest(),
                            max_output_tokens=max_output_tokens)


def validate_count(request: ResponsesRequest, *, raw_response: str, request_sha256: str) -> int:
    """Validate trusted count for this exact prepared request; no claim of billing."""
    if type(request) is not ResponsesRequest or request_sha256 != request.input_sha256:
        raise ValueError("luna_count_request_mismatch")
    try:
        generation = request.generation_payload()
        if (hashlib.sha256(request._canonical).hexdigest() != request.input_sha256
                or set(generation) != {"model", "input", "reasoning", "text", "max_output_tokens", "store"}
                or generation.get("model") != MODEL or generation.get("reasoning") != {"effort": "medium"}
                or generation.get("text") != {"format": {"type": "json_object"}}
                or generation.get("store") is not False
                or type(request.max_output_tokens) is not int or not 1 <= request.max_output_tokens <= MAX_OUTPUT
                or type(generation.get("max_output_tokens")) is not int
                or generation["max_output_tokens"] != request.max_output_tokens):
            raise ValueError("luna_count_request_mismatch")
        inputs = generation.get("input")
        if (not isinstance(inputs, list) or not inputs
                or inputs[0] != {"role": "system", "content": "Return a JSON object."}):
            raise ValueError("luna_count_request_mismatch")
        reconstructed = build_request(inputs[1:], max_output_tokens=request.max_output_tokens)
        if reconstructed._canonical != request._canonical:
            raise ValueError("luna_count_request_mismatch")
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        raise ValueError("luna_count_request_mismatch") from exc
    try:
        response = parse_source_first_response(raw_response)
    except (TypeError, ValueError) as exc:
        raise ValueError("luna_count_invalid") from exc
    count = response.get("input_tokens")
    if response.get("object") != "response.input_tokens" or type(count) is not int or count < 0:
        raise ValueError("luna_count_invalid")
    if count + request.max_output_tokens > CONTEXT_WINDOW:
        raise ValueError("luna_context_limit_exceeded")
    return count
