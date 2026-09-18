from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from .domain import AdapterResult, EvaluationRequest, Evaluator, JsonObject

Transport = Callable[[str, dict[str, str], JsonObject, float], tuple[int, JsonObject, dict[str, str]]]


class CacheMissError(RuntimeError):
    pass


class TypeSafeAPIError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"TypeSafe request failed with HTTP {status}: {message}")
        self.status = status


def _default_transport(
    url: str,
    headers: dict[str, str],
    payload: JsonObject,
    timeout: float,
) -> tuple[int, JsonObject, dict[str, str]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS URL
            body = json.loads(response.read().decode("utf-8"))
            return response.status, body, dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        body_bytes = exc.read()
        try:
            body = json.loads(body_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {"detail": "non-JSON error response"}
        return exc.code, body, dict(exc.headers.items())


class TypeSafeHTTPAdapter:
    ENDPOINT = "https://api.typesafe.ai/v1/systemone"

    def __init__(
        self,
        *,
        api_key: str,
        transport: Transport = _default_transport,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 30.0,
        max_attempts: int = 3,
    ) -> None:
        if not api_key.strip():
            raise ValueError("TYPESAFE_API_KEY is required for live evaluation")
        self._api_key = api_key
        self._transport = transport
        self._sleep = sleep
        self._timeout = timeout
        self._max_attempts = max_attempts

    def evaluate(self, request: EvaluationRequest) -> AdapterResult:
        payload: JsonObject = {
            "state": request.state,
            "model": request.model,
            "questions": request.questions,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "User-Agent": "kamilya-course-quality-eval/1",
        }
        started = time.perf_counter()
        for attempt in range(1, self._max_attempts + 1):
            status, body, response_headers = self._transport(
                self.ENDPOINT, headers, payload, self._timeout
            )
            if status == 200:
                answers = body.get("answers")
                usage = body.get("usage", {})
                if not isinstance(answers, dict) or not isinstance(usage, dict):
                    raise TypeSafeAPIError(status, "malformed success response")
                return AdapterResult(
                    model=str(body.get("model", request.model)),
                    answers=answers,
                    input_tokens=int(usage.get("input_tokens", 0)),
                    output_tokens=int(usage.get("output_tokens", 0)),
                    latency_ms=round((time.perf_counter() - started) * 1000),
                )
            if status not in {429, 529} or attempt == self._max_attempts:
                detail = body.get("detail", "request rejected")
                raise TypeSafeAPIError(status, str(detail))
            retry_after = response_headers.get("Retry-After")
            delay = float(retry_after) if retry_after else min(2 ** (attempt - 1), 8)
            self._sleep(delay)
        raise AssertionError("unreachable")


def _cache_key(request: EvaluationRequest) -> str:
    canonical = json.dumps(asdict(request), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CachedEvaluator:
    """Store only answers/usage; request state never enters the cache file."""

    def __init__(self, delegate: Evaluator | None, cache_dir: str | Path, *, refresh: bool = False) -> None:
        self._delegate = delegate
        self._cache_dir = Path(cache_dir)
        self._refresh = refresh

    def evaluate(self, request: EvaluationRequest) -> AdapterResult:
        key = _cache_key(request)
        cache_path = self._cache_dir / f"{key}.json"
        if cache_path.exists() and not self._refresh:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            payload["cached"] = True
            return AdapterResult(**payload)
        if self._delegate is None:
            raise CacheMissError(f"No cached evaluation for request {key}")
        result = self._delegate.evaluate(request)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(asdict(result), ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        return result
