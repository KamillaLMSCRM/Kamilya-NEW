"""LLM Client — OpenAI-compatible adapters with automatic failover chain.

Chain architecture (June 2026):

  LLM chain:
    1. DeepSeek v4-flash via direct DeepSeek API (api.deepseek.com/v1)
       → primary, reliable managed API. $0.14/M in, $0.28/M out.
    2. Qwen self-hosted (Qwen3.6-35B-A3B-AWQ-4bit via Cloudflare tunnel)
       → fallback, free

  Embeddings chain:
    1. Voyage voyage-4-lite via direct Voyage API (api.voyageai.com/v1)
       → primary managed embeddings. Free up to 200M tokens / account.
    2. Qwen self-hosted (Qwen3-Embedding-8B)
       → fallback, free

OpenRouter is intentionally NOT part of the v1 chain. To add a premium
tier later (Claude Haiku for reviewer), extend the providers list at
runtime through the upcoming superadmin modal — see AGENTS.md.

Failover semantics
------------------
- Each provider has its own retry loop (configurable, defaults to 2).
- If all retries fail on provider N, we move to provider N+1.
- If provider N+1 also fails after retries, we raise
  AllProvidersFailedError. We do NOT silently loop forever.
- A failed primary is logged at WARNING level (provider name + last
  exception class + status code if HTTP) so on-call can spot outages.
  We do NOT log tenant_id, prompt text, or response bodies.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LLMError(Exception):
    """Base error for LLM/embedding operations."""


class ProviderFailedError(LLMError):
    """A single provider failed after exhausting its retries."""

    def __init__(self, provider_name: str, last_exc: BaseException):
        super().__init__(f"{provider_name} failed: {type(last_exc).__name__}: {last_exc}")
        self.provider_name = provider_name
        self.last_exc = last_exc


class AllProvidersFailedError(LLMError):
    """All providers in the chain failed."""


# ---------------------------------------------------------------------------
# Provider config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMProviderConfig:
    """Static config for one LLM/embedding provider."""

    name: str  # human-readable, used in logs and metrics
    base_url: str  # e.g. https://api.deepseek.com/v1
    api_key: str  # empty string for local endpoints that don't need a key
    model: str
    timeout: float = 600.0  # per-request timeout, seconds
    extra_body: dict = field(default_factory=dict)  # vendor-specific extras
    # OpenAI-compatible endpoint path. Default = chat/completions (LLM).
    # EmbeddingsClient overrides this to /embeddings.
    # Bug 2026-06-26: previously hardcoded in _request, which meant
    # POST /v1/embeddings was being sent to /v1/chat/completions on
    # both Qwen-embed and Voyage, both of which responded with an
    # HTTP 4xx/5xx — every ingestion silently fell back to the
    # hash-based embedding and was effectively non-semantic.
    endpoint: str = "/chat/completions"


def _qwen_llm_provider() -> LLMProviderConfig:
    s = get_settings()
    return LLMProviderConfig(
        name="qwen-self-hosted",
        base_url=s.QWEN_API_URL,
        api_key=s.LLM_API_KEY or "not-needed",
        model=s.LLM_MODEL or "cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit",
        # Qwen-specific: disable thinking for snappier responses on
        # structured tasks (course generation). Harmless on providers that
        # ignore unknown chat_template_kwargs.
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )


def _deepseek_llm_provider() -> LLMProviderConfig | None:
    """Return DeepSeek provider only if API key is configured."""
    s = get_settings()
    if not s.DEEPSEEK_API_KEY:
        return None
    # deepseek-v4-flash supports thinking mode but for our use-cases
    # (structured course generation) we want deterministic JSON output —
    # disable thinking to save tokens and reduce latency.
    # deepseek-v4-pro supports thinking — keep it on for the quality
    # tier (when/if we add one). For v1-flash we always disable.
    extra: dict[str, Any] = {"thinking": {"type": "disabled"}}
    return LLMProviderConfig(
        name="deepseek",
        base_url=s.DEEPSEEK_BASE_URL,
        api_key=s.DEEPSEEK_API_KEY,
        model=s.DEEPSEEK_MODEL,
        timeout=120.0,  # DeepSeek p95 ~30s, but cold start can be longer
        extra_body=extra,
    )


async def _resolve_db_key(provider: str, env_key: str) -> str:
    """Resolve an API key: prefer env, otherwise look up the active global
    key from `provider_keys` table.

    The env value is checked first so an operator can always override
    without touching the DB. If neither has a key, the empty string is
    returned and the provider should be skipped by the caller.

    This is intentionally called only when a provider would actually be
    used (i.e. as part of building the chain), so it adds zero DB calls
    on the hot path.
    """
    if env_key:
        return env_key
    # Avoid circular import at module load.
    from app.core.db import async_session_factory
    from app.modules.admin.provider_keys.service import ProviderKeyService

    try:
        async with async_session_factory() as session:
            svc = ProviderKeyService(session)
            return await svc.get_active_key_value(provider) or ""
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            "[KEY_RESOLVE] failed to read provider key for %s: %s",
            provider, type(e).__name__,
        )
        return ""


def _qwen_embed_provider() -> LLMProviderConfig:
    s = get_settings()
    return LLMProviderConfig(
        name="qwen-self-hosted",
        base_url=s.QWEN_EMBEDDING_URL,
        api_key=s.LLM_API_KEY or "not-needed",
        model="Qwen3-Embedding-8B",
        timeout=20.0,
    )


def _voyage_embed_provider() -> LLMProviderConfig | None:
    """Return Voyage provider only if API key is configured."""
    s = get_settings()
    if not s.VOYAGE_API_KEY:
        return None
    return LLMProviderConfig(
        name="voyage",
        base_url=s.VOYAGE_BASE_URL,
        api_key=s.VOYAGE_API_KEY,
        model=s.VOYAGE_MODEL,
        timeout=30.0,
    )


def _cohere_embed_provider() -> LLMProviderConfig | None:
    """Return Cohere provider only if API key is configured."""
    s = get_settings()
    if not s.COHERE_API_KEY:
        return None
    return LLMProviderConfig(
        name="cohere",
        base_url=s.COHERE_BASE_URL,
        api_key=s.COHERE_API_KEY,
        model=s.COHERE_EMBED_MODEL,
        timeout=30.0,
        endpoint="/embed",
    )


# ---------------------------------------------------------------------------
# Low-level provider client
# ---------------------------------------------------------------------------


class _BaseProviderClient:
    """Single-provider client with internal retry loop. No failover logic."""

    def __init__(self, config: LLMProviderConfig, max_retries: int = 2):
        self.config = config
        self.max_retries = max_retries

    @property
    def name(self) -> str:
        return self.config.name

    async def _request(self, payload: dict) -> dict:
        """POST and return parsed JSON. Raises ProviderFailedError after retries."""
        last_exc: BaseException | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                    resp = await client.post(
                        f"{self.config.base_url}{self.config.endpoint}",
                        json=payload,
                        headers={"Authorization": f"Bearer {self.config.api_key}"},
                    )
            except httpx.TimeoutException as e:
                last_exc = e
                wait = min(2 ** attempt, 8)
                logger.warning(
                    f"[{self.config.name}] timeout attempt {attempt+1}/{self.max_retries+1}, "
                    f"retrying in {wait}s"
                )
                await asyncio.sleep(wait)
                continue
            except httpx.HTTPError as e:
                # Connection refused, DNS, etc. — not retryable.
                raise ProviderFailedError(self.config.name, e) from e

            if resp.status_code == 429:
                last_exc = httpx.HTTPStatusError("429", request=resp.request, response=resp)
                retry_after = resp.headers.get("retry-after")
                try:
                    server_wait = float(retry_after) if retry_after else 0.0
                except ValueError:
                    server_wait = 0.0
                wait = max(server_wait, min(2 ** attempt, 60))
                logger.warning(f"[{self.config.name}] 429 rate limited, waiting {wait}s")
                if attempt < self.max_retries:
                    await asyncio.sleep(wait)
                continue
            if resp.status_code in (502, 503, 504):
                last_exc = httpx.HTTPStatusError(
                    str(resp.status_code), request=resp.request, response=resp
                )
                wait = min(2 ** attempt, 8)
                logger.warning(
                    f"[{self.config.name}] {resp.status_code} server error, retrying in {wait}s"
                )
                await asyncio.sleep(wait)
                continue
            if resp.status_code != 200:
                # 4xx (auth, bad request, etc.) is NOT retryable — fail fast.
                raise ProviderFailedError(
                    self.config.name,
                    httpx.HTTPStatusError(
                        f"{resp.status_code}: {resp.text[:500]}",
                        request=resp.request,
                        response=resp,
                    ),
                )

            return resp.json()

        # Exhausted retries
        raise ProviderFailedError(
            self.config.name, last_exc or RuntimeError("retries exhausted with no error")
        )


class LLMClient(_BaseProviderClient):
    """Single-provider LLM client (chat completions).

    Use ResilientLLMClient for the production fallback chain. This class
    is the building block — one instance per provider.
    """

    def __init__(
        self,
        config: LLMProviderConfig | None = None,
        *,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        max_retries: int = 2,
    ):
        if config is None:
            config = _qwen_llm_provider()
        super().__init__(config=config, max_retries=max_retries)
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def ainvoke(
        self,
        messages: str | list[dict],
        config: dict | None = None,
        response_format: dict | None = None,
    ) -> "_LLMResponse":
        """Send completion request. Returns object with .content attribute."""
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]

        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        # Merge vendor-specific extras (chat_template_kwargs for Qwen,
        # thinking for DeepSeek, etc.). Payload keys take precedence over
        # extras to let callers override when needed.
        if self.config.extra_body:
            for k, v in self.config.extra_body.items():
                payload.setdefault(k, v)
        if response_format:
            payload["response_format"] = response_format

        data = await self._request(payload)
        msg = data["choices"][0]["message"]
        content = msg.get("content") or msg.get("reasoning") or ""
        if not content:
            logger.warning(
                f"[{self.config.name}] empty content, finish_reason="
                f"{data['choices'][0].get('finish_reason')}"
            )
        return _LLMResponse(content=content)


class _LLMResponse:
    """Simple response wrapper matching LangChain's .content attribute."""

    def __init__(self, content: str):
        self.content = content


# ---------------------------------------------------------------------------
# Resilient client — failover chain
# ---------------------------------------------------------------------------


class ResilientLLMClient:
    """LLM client with automatic failover across providers.

    Tries providers in order; on ProviderFailedError, moves to the next.
    On AllProvidersFailedError, the original error chain is preserved
    via __cause__.

    Usage:
        client = ResilientLLMClient.from_settings()
        resp = await client.ainvoke(messages)
    """

    def __init__(
        self,
        providers: Iterable[LLMProviderConfig],
        *,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        max_retries_per_provider: int = 2,
    ):
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._clients: list[LLMClient] = [
            LLMClient(
                cfg,
                temperature=temperature,
                max_tokens=max_tokens,
                max_retries=max_retries_per_provider,
            )
            for cfg in providers
        ]
        if not self._clients:
            raise ValueError(
                "ResilientLLMClient requires at least one provider. "
                "Check that QWEN_API_URL or DEEPSEEK_API_KEY is configured."
            )

    @classmethod
    def from_settings(
        cls,
        *,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        max_retries_per_provider: int = 2,
    ) -> "ResilientLLMClient":
        """Build the production chain from env-only settings.

        Order:
          1. DeepSeek (only if DEEPSEEK_API_KEY is set in env)
          2. Qwen self-hosted (always present)

        Does NOT consult the provider_keys table — used by tests and
        legacy callers that don't pass a DB session. Production code
        should use `from_settings_async()` to also pick up keys stored
        in the superadmin-managed provider_keys table.
        """
        providers: list[LLMProviderConfig] = []
        deepseek = _deepseek_llm_provider()
        if deepseek is not None:
            providers.append(deepseek)
        providers.append(_qwen_llm_provider())
        return cls(
            providers,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries_per_provider=max_retries_per_provider,
        )

    @classmethod
    async def from_settings_async(
        cls,
        *,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        max_retries_per_provider: int = 2,
    ) -> "ResilientLLMClient":
        """Build the production chain from env + provider_keys table.

        Same order as `from_settings()` but each provider's API key is
        resolved by `_resolve_db_key()` which prefers env and falls
        back to the active global key stored in `provider_keys`.

        This is what the AI pipeline (course generation, chat, fallback
        routing) calls — keys added or rotated via the superadmin
        provider-keys UI take effect immediately without a redeploy.
        """
        from dataclasses import replace

        s = get_settings()
        qwen = _qwen_llm_provider()  # always present
        providers: list[LLMProviderConfig] = []

        deepseek_key = await _resolve_db_key("deepseek", s.DEEPSEEK_API_KEY)
        if deepseek_key:
            cfg = _deepseek_llm_provider()
            if cfg is None:
                # Env was empty but DB had a key — build config from
                # defaults + DB key.
                cfg = LLMProviderConfig(
                    name="deepseek",
                    base_url=s.DEEPSEEK_BASE_URL,
                    api_key=deepseek_key,
                    model=s.DEEPSEEK_MODEL,
                    timeout=120.0,
                    extra_body={"thinking": {"type": "disabled"}},
                )
            else:
                cfg = replace(cfg, api_key=deepseek_key)
            providers.append(cfg)
        providers.append(qwen)

        return cls(
            providers,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries_per_provider=max_retries_per_provider,
        )

    @property
    def provider_names(self) -> list[str]:
        return [c.name for c in self._clients]

    async def ainvoke(
        self,
        messages: str | list[dict],
        config: dict | None = None,
        response_format: dict | None = None,
    ) -> _LLMResponse:
        last_exc: BaseException | None = None
        for client in self._clients:
            try:
                return await client.ainvoke(
                    messages, config=config, response_format=response_format
                )
            except ProviderFailedError as e:
                logger.warning(
                    f"[LLM_FAILOVER] {e.provider_name} failed "
                    f"({type(e.last_exc).__name__}); "
                    f"remaining={len(self._clients) - self._clients.index(client) - 1}"
                )
                last_exc = e
                continue

        raise AllProvidersFailedError(
            f"All LLM providers failed: {[c.name for c in self._clients]}"
        ) from last_exc


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


class EmbeddingsClient(_BaseProviderClient):
    """Single-provider embeddings client.

    Voyage requires `input_type` (document vs query). We send it on
    embed_documents vs embed_query; the Qwen endpoint ignores it.
    """

    def __init__(self, config: LLMProviderConfig | None = None, max_retries: int = 2):
        if config is None:
            config = _qwen_embed_provider()
        # OpenAI-compatible providers use /embeddings. Cohere has a native
        # v2 /embed endpoint and a different request/response schema.
        from dataclasses import replace
        endpoint = "/embed" if config.name == "cohere" else "/embeddings"
        config = replace(config, endpoint=endpoint)
        super().__init__(config=config, max_retries=max_retries)
        self.expected_dimensions = get_settings().EMBEDDING_DIMENSIONS

    def _validate_embeddings(self, embeddings: list[list[float]]) -> list[list[float]]:
        """Adapt smaller embeddings to the fixed pgvector schema.

        Voyage 4 returns 1024 dimensions by default while the primary Qwen
        model and the database column use 4096. Zero-padding preserves cosine
        similarity and Euclidean distances, so the fallback remains semantic
        without requiring a destructive pgvector migration.
        """
        oversized_dims = sorted(
            {len(embedding) for embedding in embeddings if len(embedding) > self.expected_dimensions}
        )
        if oversized_dims:
            raise ProviderFailedError(
                self.config.name,
                ValueError(
                    f"embedding dimensions mismatch: expected "
                    f"at most {self.expected_dimensions}, got {oversized_dims}"
                ),
            )
        return [
            embedding + [0.0] * (self.expected_dimensions - len(embedding))
            for embedding in embeddings
        ]

    async def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        if self.config.name == "cohere":
            payload: dict[str, Any] = {
                "model": self.config.model,
                "texts": texts,
                "input_type": (
                    "search_document" if input_type == "document" else "search_query"
                ),
                "embedding_types": ["float"],
                "output_dimension": 1024,
            }
        else:
            payload = {
                "model": self.config.model,
                "input": texts,
            }
        if self.config.name == "voyage":
            payload["input_type"] = input_type

        data = await self._request(payload)
        if self.config.name == "cohere":
            embeddings = data["embeddings"]["float"]
        else:
            embeddings = [item["embedding"] for item in data["data"]]
        return self._validate_embeddings(embeddings)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts, input_type="document")

    async def embed_query(self, text: str) -> list[float]:
        results = await self._embed([text], input_type="query")
        return results[0]


class ResilientEmbeddingsClient:
    """Embeddings client with automatic failover across providers.

    Chain:
      1. Voyage (only if VOYAGE_API_KEY is set)
      2. Cohere (only if COHERE_API_KEY is set)
      3. Qwen self-hosted (always present)
    """

    def __init__(
        self,
        providers: Iterable[LLMProviderConfig],
        *,
        max_retries_per_provider: int = 2,
    ):
        self._clients: list[EmbeddingsClient] = [
            EmbeddingsClient(cfg, max_retries=max_retries_per_provider)
            for cfg in providers
        ]
        if not self._clients:
            raise ValueError(
                "ResilientEmbeddingsClient requires at least one provider. "
                "Check that QWEN_EMBEDDING_URL is configured."
            )

    @classmethod
    def from_settings(cls, max_retries_per_provider: int = 6) -> "ResilientEmbeddingsClient":
        """Build the embeddings chain from env-only settings (tests/legacy)."""
        providers: list[LLMProviderConfig] = []
        voyage = _voyage_embed_provider()
        if voyage is not None:
            providers.append(voyage)
        cohere = _cohere_embed_provider()
        if cohere is not None:
            providers.append(cohere)
        providers.append(_qwen_embed_provider())
        return cls(providers, max_retries_per_provider=max_retries_per_provider)

    @classmethod
    async def from_settings_async(
        cls, max_retries_per_provider: int = 6
    ) -> "ResilientEmbeddingsClient":
        """Build the embeddings chain from env + provider_keys table.

        Same order as `from_settings()` but each provider's API key is
        resolved by `_resolve_db_key()` which prefers env and falls
        back to the active global key stored in `provider_keys`.
        """
        from dataclasses import replace

        s = get_settings()
        providers: list[LLMProviderConfig] = []

        voyage_key = await _resolve_db_key("voyage", s.VOYAGE_API_KEY)
        if voyage_key:
            cfg = _voyage_embed_provider()
            if cfg is None:
                cfg = LLMProviderConfig(
                    name="voyage",
                    base_url=s.VOYAGE_BASE_URL,
                    api_key=voyage_key,
                    model=s.VOYAGE_MODEL,
                    timeout=60.0,
                )
            else:
                cfg = replace(cfg, api_key=voyage_key)
            providers.append(cfg)
        cohere_key = await _resolve_db_key("cohere", s.COHERE_API_KEY)
        if cohere_key:
            cfg = _cohere_embed_provider()
            if cfg is None:
                cfg = LLMProviderConfig(
                    name="cohere",
                    base_url=s.COHERE_BASE_URL,
                    api_key=cohere_key,
                    model=s.COHERE_EMBED_MODEL,
                    timeout=30.0,
                    endpoint="/embed",
                )
            else:
                cfg = replace(cfg, api_key=cohere_key)
            providers.append(cfg)
        providers.append(_qwen_embed_provider())

        return cls(providers, max_retries_per_provider=max_retries_per_provider)

    @property
    def provider_names(self) -> list[str]:
        return [c.name for c in self._clients]

    async def _call_with_failover(self, fn_name: str, *args, **kwargs):
        last_exc: BaseException | None = None
        for client in self._clients:
            try:
                return await getattr(client, fn_name)(*args, **kwargs)
            except ProviderFailedError as e:
                logger.warning(
                    f"[EMBED_FAILOVER] {e.provider_name} failed "
                    f"({type(e.last_exc).__name__}); "
                    f"remaining={len(self._clients) - self._clients.index(client) - 1}"
                )
                last_exc = e
                continue

        raise AllProvidersFailedError(
            f"All embedding providers failed: {[c.name for c in self._clients]}"
        ) from last_exc

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._call_with_failover("embed_documents", texts)

    async def embed_query(self, text: str) -> list[float]:
        return await self._call_with_failover("embed_query", text)


# ---------------------------------------------------------------------------
# Backwards-compatible factories
# ---------------------------------------------------------------------------


def create_llm(
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 8192,
    response_format: dict | None = None,
    callbacks: list | None = None,
) -> ResilientLLMClient:
    """Factory for the LLM client.

    ResilientLLMClient is API-compatible with the previous LLMClient:
    callers use `await llm.ainvoke(messages)` and get back an object
    with `.content`. Internally it now falls over to DeepSeek on failure.

    The base_url/api_key/model args are kept for legacy callers but the
    production chain is built from settings — pass them only in tests
    to inject a mock provider.
    """
    if base_url is not None or api_key is not None or model is not None:
        # Legacy single-provider path (tests / one-off scripts).
        settings = get_settings()
        config = LLMProviderConfig(
            name="custom",
            base_url=base_url or settings.QWEN_API_URL,
            api_key=api_key or settings.LLM_API_KEY or "not-needed",
            model=model or settings.LLM_MODEL,
        )
        client = LLMClient(
            config, temperature=temperature, max_tokens=max_tokens
        )
        # Wrap so ainvoke signature stays identical.
        class _SingleProviderAdapter:
            def __init__(self, inner: LLMClient):
                self._inner = inner

            async def ainvoke(self, messages, config=None, response_format=None):
                return await self._inner.ainvoke(
                    messages, config=config, response_format=response_format
                )

            @property
            def provider_names(self) -> list[str]:
                return [self._inner.name]

        return _SingleProviderAdapter(client)  # type: ignore[return-value]

    return ResilientLLMClient.from_settings(
        temperature=temperature, max_tokens=max_tokens
    )


def create_embeddings(
    base_url: str | None = None,
    api_key: str = "not-needed",
    model: str = "Qwen3-Embedding-8B",
    callbacks: list | None = None,
) -> ResilientEmbeddingsClient:
    """Factory for the embeddings client.

    Production: returns ResilientEmbeddingsClient (Voyage → Qwen).
    Legacy args (base_url/api_key/model) are honored for tests.
    """
    if base_url is not None:
        config = LLMProviderConfig(
            name="custom",
            base_url=base_url,
            api_key=api_key or "not-needed",
            model=model,
        )
        client = EmbeddingsClient(config)
        # Wrap to keep .embed_documents / .embed_query API identical.
        class _SingleProviderAdapter:
            def __init__(self, inner: EmbeddingsClient):
                self._inner = inner

            async def embed_documents(self, texts):
                return await self._inner.embed_documents(texts)

            async def embed_query(self, text):
                return await self._inner.embed_query(text)

            @property
            def provider_names(self) -> list[str]:
                return [self._inner.name]

        return _SingleProviderAdapter(client)  # type: ignore[return-value]

    return ResilientEmbeddingsClient.from_settings()


async def embed_queries(
    client: EmbeddingsClient | ResilientEmbeddingsClient, queries: list[str]
) -> list[list[float]]:
    """Embed multiple queries (kept for legacy imports)."""
    return await client.embed_documents(queries)
