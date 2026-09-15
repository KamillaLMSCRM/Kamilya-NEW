"""Narrow OpenAI-compatible transports for the isolated V2 experiment."""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any, Protocol

import httpx

from .provider_models import ChatCompletion, EmbeddingBatch

QWEN_QUERY_PREFIX = (
    "Instruct: Given a user question, retrieve relevant passages that answer the question\n"
    "Query: "
)

EVIDENCE_REALIZER_SYSTEM_PROMPT = """You are a senior instructional designer.
Return one strict JSON object and no markdown fences.
The caller provides an immutable lesson evidence plan. Do not add facts, numbers,
entities, promises, legal interpretations, or examples that are absent from the
provided facts. Every teaching block must cite the exact fact_ids that support it.
Use clear natural Russian. Explain how an employee should understand or apply the
facts, but do not invent a business process. Rewrite question prompts into useful
workplace checks while preserving the exact fact_id from each question seed.
Answer options and the correct answer are server-owned: do not return or rewrite
them. Prefer direct attribute questions or a short workplace situation when the
evidence supports it. Never ask what is stated in a lesson, course, heading, table,
source, or material, and never ask what the lesson is about. Do not create extra
questions to reach a quota. Correct obvious OCR spelling noise, but if a glyph
sequence or value is unreadable, omit only that unreadable fragment and never infer
its replacement. Use a concise complete nominal lesson title of 3-8 words, not a
sentence or a clause copied from the source. Keep the lesson under 600 words.
Output schema:
{"title":str,"objective":str,"blocks":[{"heading":str,"text":str,
"fact_ids":[str]}],"questions":[{"prompt":str,"explanation":str,
"fact_ids":[str]}]}"""


class ProviderCallError(RuntimeError):
    """A bounded provider request failed or returned an invalid contract."""


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> EmbeddingBatch: ...


class ChatJsonProvider(Protocol):
    def complete_json(self, request: dict[str, Any]) -> ChatCompletion: ...


def discover_models(
    *,
    base_url: str,
    api_key: str = "",
    timeout_seconds: float = 15.0,
) -> tuple[str, ...]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        timeout = httpx.Timeout(
            connect=min(5.0, timeout_seconds),
            read=timeout_seconds,
            write=min(10.0, timeout_seconds),
            pool=min(5.0, timeout_seconds),
        )
        response = httpx.get(
            f"{base_url.rstrip('/')}/models",
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json().get("data", [])
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise ProviderCallError(f"model discovery failed: {type(exc).__name__}") from exc
    return tuple(str(item["id"]) for item in data if isinstance(item, dict) and item.get("id"))


class OpenAICompatibleEmbeddingProvider:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_seconds: float = 45.0,
        batch_size: int = 64,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        if not self._base_url.endswith("/v1"):
            self._base_url += "/v1"
        self._model = model
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._batch_size = batch_size

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        if not texts:
            return EmbeddingBatch(vectors=(), model=self._model, duration_seconds=0.0)
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        vectors: list[tuple[float, ...]] = []
        started = perf_counter()
        try:
            timeout = httpx.Timeout(
                connect=min(5.0, self._timeout_seconds),
                read=self._timeout_seconds,
                write=min(20.0, self._timeout_seconds),
                pool=min(5.0, self._timeout_seconds),
            )
            with httpx.Client(timeout=timeout) as client:
                for offset in range(0, len(texts), self._batch_size):
                    batch = texts[offset : offset + self._batch_size]
                    response = client.post(
                        f"{self._base_url}/embeddings",
                        headers=headers,
                        json={"model": self._model, "input": batch},
                    )
                    response.raise_for_status()
                    indexed = sorted(response.json().get("data", []), key=lambda item: item["index"])
                    if len(indexed) != len(batch):
                        raise ProviderCallError("embedding response count mismatch")
                    vectors.extend(tuple(float(value) for value in item["embedding"]) for item in indexed)
        except ProviderCallError:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise ProviderCallError(f"embedding request failed: {type(exc).__name__}") from exc
        if not vectors or any(len(vector) != len(vectors[0]) for vector in vectors):
            raise ProviderCallError("embedding vectors are empty or dimensionally inconsistent")
        return EmbeddingBatch(
            vectors=tuple(vectors),
            model=self._model,
            duration_seconds=perf_counter() - started,
        )


class DeepSeekJsonProvider:
    _SYSTEM_PROMPT = EVIDENCE_REALIZER_SYSTEM_PROMPT

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
        max_tokens: int = 4096,
    ) -> None:
        if not api_key:
            raise ValueError("DeepSeek API key is required")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_tokens = max_tokens

    def complete_json(self, request: dict[str, Any]) -> ChatCompletion:
        started = perf_counter()
        try:
            timeout = httpx.Timeout(
                connect=min(10.0, self._timeout_seconds),
                read=self._timeout_seconds,
                write=min(30.0, self._timeout_seconds),
                pool=min(10.0, self._timeout_seconds),
            )
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": self._SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": json.dumps(request, ensure_ascii=False, separators=(",", ":")),
                        },
                    ],
                    "temperature": 0,
                    "max_tokens": self._max_tokens,
                    "response_format": {"type": "json_object"},
                    "thinking": {"type": "disabled"},
                },
                timeout=timeout,
            )
            response.raise_for_status()
            body = response.json()
            choice = body["choices"][0]
            finish_reason = str(choice.get("finish_reason") or "")
            if finish_reason and finish_reason != "stop":
                raise ProviderCallError(f"chat response incomplete: {finish_reason}")
            content = str(choice["message"]["content"]).strip()
            if content.startswith("```"):
                content = content.removeprefix("```json").removeprefix("```")
                content = content.removesuffix("```").strip()
            payload = json.loads(content)
            if not isinstance(payload, dict):
                raise ProviderCallError("chat response JSON is not an object")
            usage = body.get("usage") or {}
        except ProviderCallError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderCallError(f"chat request failed: {type(exc).__name__}") from exc
        return ChatCompletion(
            payload=payload,
            model=str(body.get("model") or self._model),
            duration_seconds=perf_counter() - started,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
        )
