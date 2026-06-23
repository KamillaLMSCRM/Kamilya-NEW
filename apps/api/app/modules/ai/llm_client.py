"""LLM Client — adapter for Qwen 3.5 via OpenAI-compatible API."""
from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def _default_llm_url() -> str:
    return get_settings().QWEN_API_URL


def _default_embedding_url() -> str:
    return get_settings().QWEN_EMBEDDING_URL


class LLMClient:
    """Unified LLM client for Qwen 3.5 (OpenAI-compatible endpoint)."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 8192,
    ):
        settings = get_settings()
        if base_url is None:
            base_url = settings.QWEN_API_URL
        if api_key is None:
            api_key = settings.LLM_API_KEY or "not-needed"
        if model is None:
            model = settings.LLM_MODEL or "llama-3.3-70b-versatile"
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def ainvoke(
        self,
        messages: str | list[dict],
        config: dict | None = None,
        response_format: dict | None = None,
    ) -> Any:
        """Send completion request to LLM. Returns object with .content attribute."""
        import httpx

        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        async with httpx.AsyncClient(timeout=300) as client:
            print(f"[LLM_REQ] {self.base_url}/chat/completions model={self.model} msgs={len(messages)}", flush=True)
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            if response.status_code != 200:
                print(f"[LLM_ERROR] {response.status_code}: {response.text[:500]}", flush=True)
            response.raise_for_status()
            data = response.json()

        msg = data["choices"][0]["message"]
        content = msg.get("content") or msg.get("reasoning") or ""
        if not content:
            logger.warning(f"LLM returned empty content: {data['choices'][0].get('finish_reason')}")
        return _LLMResponse(content=content)


class _LLMResponse:
    """Simple response wrapper matching LangChain's .content attribute."""

    def __init__(self, content: str):
        self.content = content


class EmbeddingsClient:
    """Embeddings client for Qwen Embeddings (OpenAI-compatible)."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str = "not-needed",
        model: str = "Qwen3-Embedding-8B",
    ):
        if base_url is None:
            base_url = _default_embedding_url()
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents."""
        import httpx

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self.base_url}/embeddings",
                json={"model": self.model, "input": texts},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            data = response.json()

        return [item["embedding"] for item in data["data"]]

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""
        results = await self.embed_documents([text])
        return results[0]


def create_llm(
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 8192,
    response_format: dict | None = None,
    callbacks: list | None = None,
) -> LLMClient:
    """Factory for creating LLM client instances."""
    return LLMClient(
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def create_embeddings(
    base_url: str | None = None,
    api_key: str = "not-needed",
    model: str = "Qwen3-Embedding-8B",
    callbacks: list | None = None,
) -> EmbeddingsClient:
    """Factory for creating embeddings client instances."""
    return EmbeddingsClient(
        base_url=base_url,
        api_key=api_key,
        model=model,
    )


async def embed_queries(
    client: EmbeddingsClient, queries: list[str]
) -> list[list[float]]:
    """Embed multiple queries."""
    return await client.embed_documents(queries)
