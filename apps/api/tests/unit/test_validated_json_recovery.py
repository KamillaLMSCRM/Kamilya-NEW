"""Bounded syntax-only recovery for validated LLM calls."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app.modules.ai.llm_client import (
    AllProvidersFailedError,
    LLMClient,
    LLMProviderConfig,
    ProviderFailedError,
    ResilientLLMClient,
    _LLMResponse,
)


def _client(name: str) -> LLMClient:
    return LLMClient(LLMProviderConfig(name=name, base_url="http://test", api_key="test", model="test"))


@pytest.mark.asyncio
async def test_validated_call_repairs_json_syntax_once_on_the_same_provider() -> None:
    """A JSONDecodeError gets one provider-local correction before failover."""

    primary = _client("primary")
    fallback = _client("fallback")
    primary.ainvoke = AsyncMock(side_effect=[
        _LLMResponse('{"items": [1 2]}'),
        _LLMResponse('{"items": [1, 2]}'),
    ])  # type: ignore[assignment]
    fallback.ainvoke = AsyncMock()  # type: ignore[assignment]
    chain = ResilientLLMClient([primary.config, fallback.config])
    chain._clients = [primary, fallback]

    result = await chain.ainvoke_validated(
        [{"role": "user", "content": "Return JSON."}],
        json.loads,
        config={"max_tokens": 64},
        response_format={"type": "json_object"},
        repair_json_syntax=True,
    )

    assert result.provider == "primary"
    assert result.value == {"items": [1, 2]}
    assert result.attempt_count == 2
    assert primary.ainvoke.await_count == 2
    assert fallback.ainvoke.await_count == 0
    assert primary.ainvoke.await_args_list[1].kwargs == {
        "config": {"max_tokens": 64},
        "response_format": {"type": "json_object"},
    }


@pytest.mark.asyncio
async def test_validated_call_does_not_correct_schema_or_transport_failures() -> None:
    """Only JSON syntax gets a correction request; validation and transport do not."""

    primary = _client("primary")
    fallback = _client("fallback")
    primary.ainvoke = AsyncMock(return_value=_LLMResponse('{"items": []}'))  # type: ignore[assignment]
    fallback.ainvoke = AsyncMock(return_value=_LLMResponse('{"items": [1]}'))  # type: ignore[assignment]
    chain = ResilientLLMClient([primary.config, fallback.config])
    chain._clients = [primary, fallback]

    def schema_parser(raw: str) -> dict[str, list[int]]:
        value = json.loads(raw)
        if not value["items"]:
            raise ValueError("semantic contract rejected")
        return value

    result = await chain.ainvoke_validated("Return JSON.", schema_parser)

    assert result.provider == "fallback"
    assert primary.ainvoke.await_count == 1
    assert fallback.ainvoke.await_count == 1

    request = httpx.Request("POST", "https://provider.test/v1/chat/completions")
    for transport_error in (
        TimeoutError(),
        httpx.HTTPStatusError("401", request=request, response=httpx.Response(401, request=request)),
        httpx.HTTPStatusError("429", request=request, response=httpx.Response(429, request=request)),
    ):
        primary.ainvoke = AsyncMock(side_effect=ProviderFailedError("primary", transport_error))  # type: ignore[assignment]
        fallback.ainvoke = AsyncMock(return_value=_LLMResponse('{"items": [1]}'))  # type: ignore[assignment]

        result = await chain.ainvoke_validated("Return JSON.", json.loads)

        assert result.provider == "fallback"
        assert primary.ainvoke.await_count == 1
        assert fallback.ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_json_syntax_recovery_is_disabled_by_default() -> None:
    primary = _client("primary")
    fallback = _client("fallback")
    primary.ainvoke = AsyncMock(return_value=_LLMResponse('{"items": [1 2]}'))  # type: ignore[assignment]
    fallback.ainvoke = AsyncMock(return_value=_LLMResponse('{"items": [5]}'))  # type: ignore[assignment]
    chain = ResilientLLMClient([primary.config, fallback.config])
    chain._clients = [primary, fallback]

    result = await chain.ainvoke_validated("Return JSON.", json.loads)

    assert result.provider == "fallback"
    assert result.value == {"items": [5]}
    assert result.attempt_count == 2
    assert primary.ainvoke.await_count == 1
    assert fallback.ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_json_syntax_recovery_is_used_once_across_all_providers() -> None:
    primary = _client("primary")
    fallback = _client("fallback")
    primary.ainvoke = AsyncMock(side_effect=[
        _LLMResponse('{"items": [1 2]}'),
        _LLMResponse('{"items": [3 4]}'),
    ])  # type: ignore[assignment]
    fallback.ainvoke = AsyncMock(return_value=_LLMResponse('{"items": [5 6]}'))  # type: ignore[assignment]
    chain = ResilientLLMClient([primary.config, fallback.config])
    chain._clients = [primary, fallback]

    with pytest.raises(AllProvidersFailedError):
        await chain.ainvoke_validated("Return JSON.", json.loads, repair_json_syntax=True)

    assert primary.ainvoke.await_count == 2
    assert fallback.ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_transport_json_decode_error_does_not_enter_syntax_recovery() -> None:
    primary = _client("primary")
    fallback = _client("fallback")
    primary.ainvoke = AsyncMock(side_effect=json.JSONDecodeError("transport", "not provider output", 0))  # type: ignore[assignment]
    fallback.ainvoke = AsyncMock(return_value=_LLMResponse('{"items": [5]}'))  # type: ignore[assignment]
    chain = ResilientLLMClient([primary.config, fallback.config])
    chain._clients = [primary, fallback]

    result = await chain.ainvoke_validated("Return JSON.", json.loads, repair_json_syntax=True)

    assert result.provider == "fallback"
    assert primary.ainvoke.await_count == 1
    assert fallback.ainvoke.await_count == 1
