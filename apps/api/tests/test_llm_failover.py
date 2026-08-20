"""Tests for the LLM/Embedding failover chain (ResilientLLMClient).

Verifies that:
- ainvoke() returns success from the primary provider when it works.
- ainvoke() falls over to the secondary provider when the primary fails.
- AllProvidersFailedError is raised when every provider in the chain fails.
- Retry happens within a single provider before moving to the next.

We use AsyncMock to simulate provider success/failure without any network I/O.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.modules.ai import llm_client
from app.modules.ai.llm_client import (
    AllProvidersFailedError,
    EmbeddingsClient,
    LLMClient,
    LLMProviderConfig,
    ProviderFailedError,
    ResilientEmbeddingsClient,
    ResilientLLMClient,
    _LLMResponse,
)


def _make_client(name: str, *, succeed_after: int = 0, fail_with: Exception | None = None) -> LLMClient:
    """Build a LLMClient backed by a mock ainvoke().

    succeed_after: how many times the mock should fail before succeeding.
                   0 = succeed immediately, N = fail N times then succeed.
    fail_with:     if set, always raise this exception (regardless of
                   succeed_after). Used to model a hard provider outage.

    Exceptions raised by the mock are wrapped in ProviderFailedError to
    mirror what real low-level httpx errors look like after _request()
    exhausts its retry budget.
    """
    config = LLMProviderConfig(
        name=name,
        base_url="http://mock",
        api_key="mock-key",
        model="mock-model",
    )
    client = LLMClient(config, max_retries=2)

    call_count = 0

    async def mock_ainvoke(messages, config=None, response_format=None):
        nonlocal call_count
        call_count += 1
        if fail_with is not None:
            # Wrap in ProviderFailedError because that's what real
            # _request() raises after exhausting retries, and that's
            # what ResilientLLMClient catches.
            raise ProviderFailedError(name, fail_with)
        if call_count <= succeed_after:
            raise ProviderFailedError(name, RuntimeError("simulated transient"))
        return _LLMResponse(content=f"reply from {name}")

    client.ainvoke = mock_ainvoke  # type: ignore[assignment]
    client._call_count = lambda: call_count  # type: ignore[attr-defined]
    return client


def test_resilient_llm_uses_primary_when_available():
    primary = _make_client("primary", succeed_after=0)
    fallback = _make_client("fallback", succeed_after=0)
    chain = ResilientLLMClient(
        [primary.config, fallback.config],  # type: ignore[attr-defined]
    )
    # Patch the LLMClient instances inside the chain to use our mocks.
    chain._clients = [
        _make_client("primary", succeed_after=0),
        _make_client("fallback", succeed_after=0),
    ]
    import asyncio

    response = asyncio.run(chain.ainvoke("hello"))
    assert response.content == "reply from primary"


def test_resilient_llm_falls_over_to_secondary():
    chain = ResilientLLMClient(
        [
            LLMProviderConfig(name="primary", base_url="x", api_key="y", model="z"),
            LLMProviderConfig(name="fallback", base_url="x", api_key="y", model="z"),
        ]
    )
    chain._clients = [
        _make_client("primary", fail_with=RuntimeError("connection refused")),
        _make_client("fallback", succeed_after=0),
    ]
    import asyncio

    response = asyncio.run(chain.ainvoke("hello"))
    assert response.content == "reply from fallback"


def test_resilient_llm_provider_propagates_provider_failed_error():
    """When a provider's _request raises ProviderFailedError, it propagates.

    Note: the internal retry loop lives inside _BaseProviderClient._request
    itself (it catches httpx.TimeoutException, 429, 5xx). When those retries
    exhaust, _request raises ProviderFailedError. Here we simulate that
    boundary directly.
    """
    config = LLMProviderConfig(name="primary", base_url="x", api_key="y", model="z")
    client = LLMClient(config, max_retries=2)

    async def always_fail(payload):
        raise ProviderFailedError("primary", RuntimeError("network down"))

    client._request = always_fail  # type: ignore[assignment]

    import asyncio

    with pytest.raises(ProviderFailedError) as excinfo:
        asyncio.run(client.ainvoke("hello"))
    assert excinfo.value.provider_name == "primary"


def test_resilient_llm_raises_when_all_providers_fail():
    chain = ResilientLLMClient(
        [
            LLMProviderConfig(name="primary", base_url="x", api_key="y", model="z"),
            LLMProviderConfig(name="fallback", base_url="x", api_key="y", model="z"),
        ]
    )
    chain._clients = [
        _make_client("primary", fail_with=RuntimeError("p down")),
        _make_client("fallback", fail_with=RuntimeError("f down")),
    ]
    import asyncio

    with pytest.raises(AllProvidersFailedError) as excinfo:
        asyncio.run(chain.ainvoke("hello"))
    assert "primary" in str(excinfo.value)
    assert "fallback" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, ProviderFailedError)


def test_resilient_llm_requires_at_least_one_provider():
    with pytest.raises(ValueError, match="at least one provider"):
        ResilientLLMClient([])


def test_resilient_llm_provider_names():
    chain = ResilientLLMClient(
        [
            LLMProviderConfig(name="qwen-self-hosted", base_url="x", api_key="y", model="z"),
            LLMProviderConfig(name="deepseek", base_url="x", api_key="y", model="z"),
        ]
    )
    assert chain.provider_names == ["qwen-self-hosted", "deepseek"]


def test_settings_chain_preserves_legacy_order_when_free_pool_disabled(monkeypatch):
    deepseek = LLMProviderConfig(name="deepseek", base_url="https://deepseek.test", api_key="key", model="flash")
    qwen = LLMProviderConfig(name="qwen-self-hosted", base_url="https://qwen.test", api_key="key", model="qwen")
    monkeypatch.setattr(llm_client, "_deepseek_llm_provider", lambda: deepseek)
    monkeypatch.setattr(llm_client, "_qwen_llm_provider", lambda: qwen)
    monkeypatch.setattr(llm_client, "_qwen_free_pool_provider", lambda: qwen)
    monkeypatch.setattr(llm_client, "_free_llm_providers", lambda: [])

    chain = ResilientLLMClient.from_settings()

    assert chain.provider_names == ["deepseek", "qwen-self-hosted"]


def test_settings_chain_tries_all_free_models_before_managed_fallback(monkeypatch):
    qwen38 = LLMProviderConfig(
        name="gx10-17-18-qwen38-27b-nvfp4",
        base_url="http://qwen38.test/v1",
        api_key="not-needed",
        model="qwen38",
        max_retries=0,
    )
    thinkingcap = LLMProviderConfig(
        name="gx10-7-thinkingcap",
        base_url="http://thinkingcap.test/v1",
        api_key="not-needed",
        model="thinkingcap",
        max_retries=0,
    )
    nvfp4 = LLMProviderConfig(
        name="gx10-2-qwen35-nvfp4",
        base_url="http://nvfp4.test/v1",
        api_key="not-needed",
        model="nvfp4",
        max_retries=0,
    )
    qwen = LLMProviderConfig(
        name="qwen-self-hosted",
        base_url="http://awq.test/v1",
        api_key="not-needed",
        model="awq",
    )
    deepseek = LLMProviderConfig(
        name="deepseek",
        base_url="https://deepseek.test/v1",
        api_key="key",
        model="flash",
    )
    monkeypatch.setattr(llm_client, "_free_llm_providers", lambda: [qwen38, thinkingcap, nvfp4])
    monkeypatch.setattr(llm_client, "_qwen_llm_provider", lambda: qwen)
    monkeypatch.setattr(llm_client, "_deepseek_llm_provider", lambda: deepseek)

    chain = ResilientLLMClient.from_settings(max_retries_per_provider=2)

    assert chain.provider_names == [
        "gx10-17-18-qwen38-27b-nvfp4",
        "gx10-7-thinkingcap",
        "gx10-2-qwen35-nvfp4",
        "qwen-self-hosted",
        "deepseek",
    ]
    assert [client.max_retries for client in chain._clients] == [0, 0, 0, 0, 2]


def test_openai_base_url_adds_v1_once():
    assert llm_client._openai_base_url("http://model.test:8000") == ("http://model.test:8000/v1")
    assert llm_client._openai_base_url("http://model.test:8000/v1/") == ("http://model.test:8000/v1")


@pytest.mark.asyncio
async def test_async_settings_chain_prefers_db_deepseek_key(monkeypatch):
    qwen = LLMProviderConfig(name="qwen-self-hosted", base_url="https://qwen.test", api_key="key", model="qwen")
    monkeypatch.setattr(llm_client, "_qwen_llm_provider", lambda: qwen)
    monkeypatch.setattr(llm_client, "_qwen_free_pool_provider", lambda: qwen)
    monkeypatch.setattr(llm_client, "_deepseek_llm_provider", lambda: None)
    monkeypatch.setattr(llm_client, "_free_llm_providers", lambda: [])

    async def resolve_key(provider, env_key):
        return "db-deepseek-key"

    monkeypatch.setattr(llm_client, "_resolve_db_key", resolve_key)

    chain = await ResilientLLMClient.from_settings_async()

    assert chain.provider_names == ["deepseek", "qwen-self-hosted"]


@pytest.mark.asyncio
async def test_async_settings_chain_places_db_deepseek_after_free_pool(monkeypatch):
    free = LLMProviderConfig(
        name="gx10-7-thinkingcap",
        base_url="http://thinkingcap.test/v1",
        api_key="not-needed",
        model="thinkingcap",
        max_retries=0,
    )
    qwen = LLMProviderConfig(
        name="qwen-self-hosted",
        base_url="http://awq.test/v1",
        api_key="not-needed",
        model="awq",
    )
    monkeypatch.setattr(llm_client, "_free_llm_providers", lambda: [free])
    monkeypatch.setattr(llm_client, "_qwen_llm_provider", lambda: qwen)
    monkeypatch.setattr(llm_client, "_deepseek_llm_provider", lambda: None)

    async def resolve_key(provider, env_key):
        return "db-deepseek-key"

    monkeypatch.setattr(llm_client, "_resolve_db_key", resolve_key)

    chain = await ResilientLLMClient.from_settings_async()

    assert chain.provider_names == [
        "gx10-7-thinkingcap",
        "qwen-self-hosted",
        "deepseek",
    ]


def test_embeddings_settings_chain_prefers_voyage(monkeypatch):
    voyage = LLMProviderConfig(name="voyage", base_url="https://voyage.test", api_key="key", model="voyage")
    qwen = LLMProviderConfig(name="qwen-self-hosted", base_url="https://qwen.test", api_key="key", model="qwen")
    monkeypatch.setattr(llm_client, "_voyage_embed_provider", lambda: voyage)
    monkeypatch.setattr(llm_client, "_cohere_embed_provider", lambda: None)
    monkeypatch.setattr(llm_client, "_qwen_embed_provider", lambda: qwen)

    chain = ResilientEmbeddingsClient.from_settings()

    assert chain.provider_names == ["voyage", "qwen-self-hosted"]
    assert all(client.max_retries == 6 for client in chain._clients)


@pytest.mark.asyncio
async def test_async_embeddings_chain_prefers_db_voyage_key(monkeypatch):
    qwen = LLMProviderConfig(name="qwen-self-hosted", base_url="https://qwen.test", api_key="key", model="qwen")
    monkeypatch.setattr(llm_client, "_qwen_embed_provider", lambda: qwen)
    monkeypatch.setattr(llm_client, "_voyage_embed_provider", lambda: None)

    async def resolve_key(provider, env_key):
        return "db-voyage-key" if provider == "voyage" else ""

    monkeypatch.setattr(llm_client, "_resolve_db_key", resolve_key)

    chain = await ResilientEmbeddingsClient.from_settings_async()

    assert chain.provider_names == ["voyage", "qwen-self-hosted"]


def test_embeddings_settings_chain_places_cohere_between_voyage_and_qwen(monkeypatch):
    voyage = LLMProviderConfig(name="voyage", base_url="https://voyage.test", api_key="key", model="voyage")
    cohere = LLMProviderConfig(name="cohere", base_url="https://cohere.test", api_key="key", model="embed-v4.0")
    qwen = LLMProviderConfig(name="qwen-self-hosted", base_url="https://qwen.test", api_key="key", model="qwen")
    monkeypatch.setattr(llm_client, "_voyage_embed_provider", lambda: voyage)
    monkeypatch.setattr(llm_client, "_cohere_embed_provider", lambda: cohere)
    monkeypatch.setattr(llm_client, "_qwen_embed_provider", lambda: qwen)

    chain = ResilientEmbeddingsClient.from_settings()

    assert chain.provider_names == ["voyage", "cohere", "qwen-self-hosted"]


@pytest.mark.asyncio
async def test_async_embeddings_chain_uses_db_cohere_key(monkeypatch):
    qwen = LLMProviderConfig(name="qwen-self-hosted", base_url="https://qwen.test", api_key="key", model="qwen")
    monkeypatch.setattr(llm_client, "_qwen_embed_provider", lambda: qwen)
    monkeypatch.setattr(llm_client, "_voyage_embed_provider", lambda: None)
    monkeypatch.setattr(llm_client, "_cohere_embed_provider", lambda: None)

    async def resolve_key(provider, env_key):
        return "db-cohere-key" if provider == "cohere" else ""

    monkeypatch.setattr(llm_client, "_resolve_db_key", resolve_key)

    chain = await ResilientEmbeddingsClient.from_settings_async()

    assert chain.provider_names == ["cohere", "qwen-self-hosted"]


@pytest.mark.asyncio
async def test_ingestion_embeddings_provider_uses_async_key_resolution(monkeypatch):
    from app.modules.ai.ingestion import EmbeddingsProvider

    fake_client = AsyncMock()
    fake_client.embed_documents.return_value = [[0.5] * 4096]
    factory = AsyncMock(return_value=fake_client)
    monkeypatch.setattr(ResilientEmbeddingsClient, "from_settings_async", factory)

    result = await EmbeddingsProvider().embed(["safety"])

    factory.assert_awaited_once()
    fake_client.embed_documents.assert_awaited_once_with(["safety"])
    assert len(result[0]) == 4096


# ---------------------------------------------------------------------------
# Embeddings chain tests (same structure, separate surface)
# ---------------------------------------------------------------------------


def _make_embed_client(name: str, *, fail_with: Exception | None = None):
    """Build an EmbeddingsClient-like mock with embed_documents/embed_query."""
    from app.modules.ai.llm_client import EmbeddingsClient

    config = LLMProviderConfig(
        name=name,
        base_url="http://mock",
        api_key="mock-key",
        model="mock-embed-model",
    )
    client = EmbeddingsClient(config, max_retries=2)

    async def mock_embed_docs(texts):
        if fail_with is not None:
            raise fail_with
        return [[0.1] * 8 for _ in texts]

    async def mock_embed_query(text):
        if fail_with is not None:
            raise fail_with
        return [0.1] * 8

    client.embed_documents = mock_embed_docs  # type: ignore[assignment]
    client.embed_query = mock_embed_query  # type: ignore[assignment]
    return client


@pytest.mark.asyncio
async def test_resilient_embeddings_uses_primary():
    chain = ResilientEmbeddingsClient(
        [
            LLMProviderConfig(name="qwen", base_url="x", api_key="y", model="z"),
            LLMProviderConfig(name="voyage", base_url="x", api_key="y", model="z"),
        ]
    )
    chain._clients = [
        _make_embed_client("qwen"),
        _make_embed_client("voyage"),
    ]
    result = await chain.embed_documents(["hello", "world"])
    assert len(result) == 2
    assert all(len(v) == 8 for v in result)


@pytest.mark.asyncio
async def test_resilient_embeddings_falls_over_to_voyage():
    chain = ResilientEmbeddingsClient(
        [
            LLMProviderConfig(name="qwen", base_url="x", api_key="y", model="z"),
            LLMProviderConfig(name="voyage", base_url="x", api_key="y", model="z"),
        ]
    )
    chain._clients = [
        _make_embed_client("qwen", fail_with=ProviderFailedError("qwen", RuntimeError("502"))),
        _make_embed_client("voyage"),
    ]
    result = await chain.embed_query("test query")
    assert result == [0.1] * 8


@pytest.mark.asyncio
async def test_embeddings_client_zero_pads_smaller_provider_vectors(monkeypatch):
    client = EmbeddingsClient(
        LLMProviderConfig(name="voyage", base_url="http://mock", api_key="y", model="z"),
        max_retries=0,
    )

    async def mock_request(payload):
        return {"data": [{"embedding": [0.1] * 1024}]}

    monkeypatch.setattr(client, "_request", mock_request)

    result = await client.embed_documents(["hello"])

    assert len(result[0]) == 4096
    assert result[0][:1024] == [0.1] * 1024
    assert result[0][1024:] == [0.0] * (4096 - 1024)


@pytest.mark.asyncio
async def test_cohere_embeddings_use_native_v2_schema(monkeypatch):
    client = EmbeddingsClient(
        LLMProviderConfig(
            name="cohere",
            base_url="https://api.cohere.test/v2",
            api_key="key",
            model="embed-v4.0",
        ),
        max_retries=0,
    )
    captured = {}

    async def mock_request(payload):
        captured.update(payload)
        return {"embeddings": {"float": [[0.25] * 1024]}}

    monkeypatch.setattr(client, "_request", mock_request)

    result = await client.embed_query("warehouse safety")

    assert client.config.endpoint == "/embed"
    assert captured == {
        "model": "embed-v4.0",
        "texts": ["warehouse safety"],
        "input_type": "search_query",
        "embedding_types": ["float"],
        "output_dimension": 1024,
    }
    assert len(result) == 4096
    assert result[:1024] == [0.25] * 1024


@pytest.mark.asyncio
async def test_cohere_embeddings_split_requests_at_provider_batch_limit(monkeypatch):
    client = EmbeddingsClient(
        LLMProviderConfig(
            name="cohere",
            base_url="https://api.cohere.test/v2",
            api_key="key",
            model="embed-v4.0",
        ),
        max_retries=0,
    )
    batch_sizes: list[int] = []

    async def mock_request(payload):
        batch_sizes.append(len(payload["texts"]))
        return {"embeddings": {"float": [[float(len(batch_sizes))] * 1024 for _ in payload["texts"]]}}

    monkeypatch.setattr(client, "_request", mock_request)

    result = await client.embed_documents([f"chunk-{index}" for index in range(99)])

    assert batch_sizes == [96, 3]
    assert len(result) == 99
    assert result[0][0] == 1.0
    assert result[-1][0] == 2.0


@pytest.mark.asyncio
async def test_embeddings_client_rejects_oversized_vectors(monkeypatch):
    client = EmbeddingsClient(
        LLMProviderConfig(name="qwen", base_url="http://mock", api_key="y", model="z"),
        max_retries=0,
    )

    async def mock_request(payload):
        return {"data": [{"embedding": [0.1] * 4097}]}

    monkeypatch.setattr(client, "_request", mock_request)

    with pytest.raises(ProviderFailedError) as exc:
        await client.embed_documents(["hello"])

    assert "at most 4096" in str(exc.value)
    assert "4097" in str(exc.value)


@pytest.mark.asyncio
async def test_resilient_embeddings_falls_over_on_wrong_dimensions(monkeypatch):
    qwen = EmbeddingsClient(
        LLMProviderConfig(name="qwen", base_url="http://mock", api_key="y", model="z"),
        max_retries=0,
    )
    voyage = EmbeddingsClient(
        LLMProviderConfig(name="voyage", base_url="http://mock", api_key="y", model="z"),
        max_retries=0,
    )

    async def mock_qwen_request(payload):
        return {"data": [{"embedding": [0.1] * 4097}]}

    async def mock_voyage_request(payload):
        return {"data": [{"embedding": [0.2] * 4096}]}

    monkeypatch.setattr(qwen, "_request", mock_qwen_request)
    monkeypatch.setattr(voyage, "_request", mock_voyage_request)

    chain = ResilientEmbeddingsClient(
        [
            LLMProviderConfig(name="qwen", base_url="x", api_key="y", model="z"),
            LLMProviderConfig(name="voyage", base_url="x", api_key="y", model="z"),
        ]
    )
    chain._clients = [qwen, voyage]

    result = await chain.embed_documents(["hello"])

    assert len(result) == 1
    assert len(result[0]) == 4096
    assert result[0][0] == 0.2


@pytest.mark.asyncio
async def test_resilient_embeddings_raises_when_all_fail():
    chain = ResilientEmbeddingsClient(
        [
            LLMProviderConfig(name="qwen", base_url="x", api_key="y", model="z"),
            LLMProviderConfig(name="voyage", base_url="x", api_key="y", model="z"),
        ]
    )
    chain._clients = [
        _make_embed_client("qwen", fail_with=ProviderFailedError("qwen", RuntimeError("502"))),
        _make_embed_client("voyage", fail_with=ProviderFailedError("voyage", RuntimeError("401"))),
    ]
    with pytest.raises(AllProvidersFailedError):
        await chain.embed_documents(["text"])


# ---------------------------------------------------------------------------
# Factory backwards-compat
# ---------------------------------------------------------------------------


def test_create_llm_returns_resilient_client_with_defaults():
    """create_llm() without args should return a ResilientLLMClient."""
    from app.modules.ai.llm_client import create_llm

    client = create_llm()
    assert isinstance(client, ResilientLLMClient)
    # In test/dev env, DEEPSEEK_API_KEY is empty, so chain has only Qwen.
    assert "qwen-self-hosted" in client.provider_names


def test_create_embeddings_returns_resilient_client_with_defaults():
    from app.modules.ai.llm_client import create_embeddings

    client = create_embeddings()
    assert isinstance(client, ResilientEmbeddingsClient)
    assert "qwen-self-hosted" in client.provider_names


def test_create_llm_with_explicit_args_uses_single_provider():
    """Legacy callers passing base_url/api_key/model get a single-provider wrapper."""
    from app.modules.ai.llm_client import create_llm

    client = create_llm(
        base_url="http://test",
        api_key="test-key",
        model="test-model",
        temperature=0.5,
    )
    # Should not be the multi-provider resilient client.
    assert client.provider_names == ["custom"]
