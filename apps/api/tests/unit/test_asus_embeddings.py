"""No-network contract tests for the dedicated ASUS Qwen embeddings adapter."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from app.modules.ai import llm_client
from app.modules.ai.llm_client import (
    EmbeddingsClient,
    LLMProviderConfig,
    ProviderFailedError,
    ResilientEmbeddingsClient,
)


def _asus_config() -> LLMProviderConfig:
    return LLMProviderConfig(
        name="asus-qwen-embedding-8b",
        base_url="http://10.66.66.15:8001/v1",
        api_key="not-needed",
        model="Qwen/Qwen3-Embedding-8B",
        timeout=12.0,
        connect_timeout=3.0,
        max_retries=0,
        embedding_max_input_bytes=8192,
        embedding_batch_size=32,
        embedding_revision="Qwen-Qwen3-Embedding-8B:qprefix-v1:l2:storage4096",
    )


@pytest.mark.asyncio
async def test_asus_qwen_prefixes_only_queries_normalizes_and_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    client = EmbeddingsClient(_asus_config(), max_retries=0)
    payloads: list[dict[str, object]] = []

    async def request(payload: dict[str, object]) -> dict[str, object]:
        payloads.append(payload)
        return {"data": [{"embedding": [3.0, 4.0]} for _ in payload["input"]]}

    monkeypatch.setattr(client, "_request", request)
    documents = [f"document-{index}" for index in range(33)]
    result = await client.embed_documents_with_provenance(documents)
    query = await client.embed_query("where is the exit?")

    assert [len(payload["input"]) for payload in payloads[:2]] == [32, 1]
    assert payloads[0]["input"][0] == "document-0"
    assert payloads[2]["input"] == [
        "Instruct: Given a user question, retrieve relevant passages that answer the question\n"
        "Query: where is the exit?"
    ]
    assert result.revision == "Qwen-Qwen3-Embedding-8B:qprefix-v1:l2:storage4096"
    assert result.vectors[0][:2] == pytest.approx((0.6, 0.8))
    assert math.sqrt(sum(value * value for value in query)) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_asus_qwen_rejects_oversized_zero_and_nonfinite_without_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = EmbeddingsClient(_asus_config(), max_retries=0)
    calls = 0

    async def request(payload: dict[str, object]) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"data": [{"embedding": [0.0, 0.0]} for _ in payload["input"]]}

    monkeypatch.setattr(client, "_request", request)
    with pytest.raises(ProviderFailedError, match="embedding_input_too_large"):
        await client.embed_query("x" * 8192)
    assert calls == 0

    with pytest.raises(ProviderFailedError, match="invalid_embedding_norm"):
        await client.embed_documents(["document"])

    async def nonfinite_request(payload: dict[str, object]) -> dict[str, object]:
        return {"data": [{"embedding": [float("nan"), 1.0]} for _ in payload["input"]]}

    monkeypatch.setattr(client, "_request", nonfinite_request)
    with pytest.raises(ProviderFailedError, match="invalid_embedding_value"):
        await client.embed_documents(["document"])


@pytest.mark.asyncio
async def test_openai_embedding_indices_reorder_or_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    client = EmbeddingsClient(
        LLMProviderConfig(name="voyage", base_url="https://voyage.test/v1", api_key="key", model="voyage"),
        max_retries=0,
    )

    async def shuffled(_payload: dict[str, object]) -> dict[str, object]:
        return {"data": [
            {"index": 2, "embedding": [3.0]},
            {"index": 0, "embedding": [1.0]},
            {"index": 1, "embedding": [2.0]},
        ]}

    monkeypatch.setattr(client, "_request", shuffled)
    assert [vector[0] for vector in await client.embed_documents(["a", "b", "c"])] == [1.0, 2.0, 3.0]

    invalid_responses = [
        [{"index": 0, "embedding": [1.0]}, {"index": 0, "embedding": [2.0]}],
        [{"index": 0, "embedding": [1.0]}, {"index": 2, "embedding": [2.0]}],
        [{"index": 0, "embedding": [1.0]}, {"embedding": [2.0]}],
    ]
    for items in invalid_responses:
        async def invalid(_payload: dict[str, object], values=items) -> dict[str, object]:
            return {"data": values}

        monkeypatch.setattr(client, "_request", invalid)
        with pytest.raises(ProviderFailedError, match="invalid_embedding_response_indices"):
            await client.embed_documents(["a", "b"])

    async def legacy_order(_payload: dict[str, object]) -> dict[str, object]:
        return {"data": [{"embedding": [4.0]}, {"embedding": [5.0]}]}

    monkeypatch.setattr(client, "_request", legacy_order)
    assert [vector[0] for vector in await client.embed_documents(["a", "b"])] == [4.0, 5.0]


@pytest.mark.asyncio
async def test_voyage_and_cohere_queries_remain_unprefixed_and_unbounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = "x" * 9000
    voyage = EmbeddingsClient(
        LLMProviderConfig(name="voyage", base_url="https://voyage.test/v1", api_key="key", model="voyage"),
        max_retries=0,
    )
    cohere = EmbeddingsClient(
        LLMProviderConfig(name="cohere", base_url="https://cohere.test/v2", api_key="key", model="cohere"),
        max_retries=0,
    )
    voyage_payloads: list[dict[str, object]] = []
    cohere_payloads: list[dict[str, object]] = []

    async def voyage_request(payload: dict[str, object]) -> dict[str, object]:
        voyage_payloads.append(payload)
        return {"data": [{"embedding": [1.0]}]}

    async def cohere_request(payload: dict[str, object]) -> dict[str, object]:
        cohere_payloads.append(payload)
        return {"embeddings": {"float": [[1.0]]}}

    monkeypatch.setattr(voyage, "_request", voyage_request)
    monkeypatch.setattr(cohere, "_request", cohere_request)
    await voyage.embed_query(query)
    await cohere.embed_query(query)

    assert voyage_payloads[0]["input"] == [query]
    assert voyage_payloads[0]["input_type"] == "query"
    assert cohere_payloads[0]["texts"] == [query]
    assert cohere_payloads[0]["input_type"] == "search_query"


def test_global_embedding_order_starts_asus_then_managed_and_qwen_has_no_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    asus = _asus_config()
    voyage = LLMProviderConfig(name="voyage", base_url="https://voyage.test", api_key="key", model="voyage")
    cohere = LLMProviderConfig(name="cohere", base_url="https://cohere.test", api_key="key", model="cohere")
    monkeypatch.setattr(llm_client, "_asus_qwen_embed_provider", lambda: asus)
    monkeypatch.setattr(llm_client, "_voyage_embed_provider", lambda: voyage)
    monkeypatch.setattr(llm_client, "_cohere_embed_provider", lambda: cohere)

    chain = ResilientEmbeddingsClient.from_settings()

    assert chain.provider_names == ["asus-qwen-embedding-8b", "voyage", "cohere"]
    assert [client.max_retries for client in chain._clients] == [0, 2, 2]
    assert [client.config.embedding_batch_size for client in chain._clients] == [32, 128, 96]


@pytest.mark.asyncio
async def test_async_global_embedding_order_starts_asus_then_managed(monkeypatch: pytest.MonkeyPatch) -> None:
    asus = _asus_config()
    monkeypatch.setattr(llm_client, "_asus_qwen_embed_provider", lambda: asus)
    monkeypatch.setattr(llm_client, "_voyage_embed_provider", lambda: None)
    monkeypatch.setattr(llm_client, "_cohere_embed_provider", lambda: None)
    monkeypatch.setattr(
        llm_client,
        "get_settings",
        lambda: SimpleNamespace(
            VOYAGE_API_KEY="", VOYAGE_BASE_URL="https://voyage.test/v1", VOYAGE_MODEL="voyage",
            COHERE_API_KEY="", COHERE_BASE_URL="https://cohere.test/v2", COHERE_EMBED_MODEL="cohere",
            EMBEDDING_DIMENSIONS=4096,
        ),
    )

    async def resolve_key(provider: str, _env_key: str) -> str:
        return f"{provider}-key"

    monkeypatch.setattr(llm_client, "_resolve_db_key", resolve_key)
    chain = await ResilientEmbeddingsClient.from_settings_async()

    assert chain.provider_names == ["asus-qwen-embedding-8b", "voyage", "cohere"]
    assert [client.max_retries for client in chain._clients] == [0, 2, 2]
    assert [client.config.embedding_batch_size for client in chain._clients] == [32, 128, 96]


def test_asus_embedding_factory_is_distinct_from_chat_qwen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        llm_client,
        "get_settings",
        lambda: SimpleNamespace(
            ASUS_EMBEDDINGS_ENABLED=True,
            ASUS_EMBEDDINGS_URL="http://10.66.66.15:8001/v1",
            ASUS_EMBEDDINGS_MODEL="Qwen/Qwen3-Embedding-8B",
            ASUS_EMBEDDINGS_REQUEST_TIMEOUT_SECONDS=12.0,
            ASUS_EMBEDDINGS_CONNECT_TIMEOUT_SECONDS=3.0,
            ASUS_EMBEDDINGS_MAX_INPUT_BYTES=8192,
            ASUS_EMBEDDINGS_MAX_BATCH_SIZE=32,
            EMBEDDING_DIMENSIONS=4096,
            QWEN_API_URL="https://chat-qwen.invalid/v1",
            LLM_MODEL="chat-model-must-not-be-used",
        ),
    )

    provider = llm_client._asus_qwen_embed_provider()

    assert provider is not None
    assert (provider.base_url, provider.model, provider.timeout, provider.connect_timeout) == (
        "http://10.66.66.15:8001/v1", "Qwen/Qwen3-Embedding-8B", 12.0, 3.0,
    )
    assert provider.max_retries == 0


@pytest.mark.asyncio
async def test_qwen_batch_failure_restarts_whole_batch_on_one_managed_space(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qwen = EmbeddingsClient(_asus_config(), max_retries=0)
    voyage = EmbeddingsClient(
        LLMProviderConfig(name="voyage", base_url="https://voyage.test/v1", api_key="key", model="voyage"),
        max_retries=0,
    )
    qwen_sizes: list[int] = []
    voyage_sizes: list[int] = []
    progress_events: list[tuple[int, int, str]] = []

    async def on_progress(completed: int, total: int, provider: str) -> None:
        progress_events.append((completed, total, provider))

    async def qwen_request(payload: dict[str, object]) -> dict[str, object]:
        qwen_sizes.append(len(payload["input"]))
        if len(qwen_sizes) == 2:
            raise ProviderFailedError("asus-qwen-embedding-8b", RuntimeError("unavailable"))
        return {"data": [{"embedding": [1.0, 0.0]} for _ in payload["input"]]}

    async def voyage_request(payload: dict[str, object]) -> dict[str, object]:
        voyage_sizes.append(len(payload["input"]))
        return {"data": [{"embedding": [0.25, 0.5]} for _ in payload["input"]]}

    monkeypatch.setattr(qwen, "_request", qwen_request)
    monkeypatch.setattr(voyage, "_request", voyage_request)
    chain = ResilientEmbeddingsClient([_asus_config(), voyage.config], max_retries_per_provider=0)
    chain._clients = [qwen, voyage]

    result = await chain.embed_documents_with_provenance(
        [f"chunk-{index}" for index in range(33)],
        on_progress=on_progress,
    )

    assert qwen_sizes == [32, 1]
    assert voyage_sizes == [33]
    assert result.provider == "voyage"
    assert result.revision == "voyage"
    assert all(vector[:2] == pytest.approx((0.25, 0.5)) for vector in result.vectors)
    assert progress_events == [
        (0, 33, "asus-qwen-embedding-8b"),
        (32, 33, "asus-qwen-embedding-8b"),
        (0, 33, "voyage"),
        (33, 33, "voyage"),
    ]


@pytest.mark.asyncio
async def test_explicit_tenant_override_never_constructs_global_asus_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_provider = LLMProviderConfig(
        name="tenant-provider", base_url="https://tenant.test", api_key="tenant-key", model="tenant-model",
    )
    monkeypatch.setattr(llm_client, "_asus_qwen_embed_provider", lambda: _asus_config())

    async def resolve_tenant_provider(*_args: object) -> LLMProviderConfig:
        return tenant_provider

    async def resolve_global_key(*_args: object) -> str:
        raise AssertionError("global credentials must not be resolved")

    from app.modules.admin.tenant_ai_providers import service

    monkeypatch.setattr(service, "resolve_tenant_provider", resolve_tenant_provider)
    monkeypatch.setattr(llm_client, "_resolve_db_key", resolve_global_key)

    chain = await ResilientEmbeddingsClient.from_settings_async(tenant_id="11111111-1111-1111-1111-111111111111")

    assert chain.provider_names == ["tenant-provider"]


@pytest.mark.asyncio
async def test_explicit_tenant_override_resolution_failure_never_uses_global_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def resolve_tenant_provider(*_args: object) -> LLMProviderConfig:
        raise RuntimeError("tenant provider unavailable")

    async def resolve_global_key(*_args: object) -> str:
        raise AssertionError("global credentials must not be resolved")

    from app.modules.admin.tenant_ai_providers import service

    monkeypatch.setattr(service, "resolve_tenant_provider", resolve_tenant_provider)
    monkeypatch.setattr(llm_client, "_resolve_db_key", resolve_global_key)

    with pytest.raises(RuntimeError, match="tenant provider unavailable"):
        await ResilientEmbeddingsClient.from_settings_async(
            tenant_id="11111111-1111-1111-1111-111111111111"
        )
