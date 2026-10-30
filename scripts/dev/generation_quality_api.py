"""Bounded development-only OpenAI transport; no application routing mutation.

Prices checked against https://developers.openai.com/api/docs/pricing on
2026-10-30. Ledger money is integer micro-USD. Cached input is deliberately not
discounted, and a conservative ceiling covers long-context/cache-write pricing.
Unknown physical outcomes are never refunded or retried automatically.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

import httpx

MICRO_USD = 1_000_000
MAX_BUDGET = 5 * MICRO_USD
ENDPOINT = "https://api.openai.com/v1/chat/completions"
PRICES = {
    "gpt-6-luna": (100_000, 500_000, 500_000, 750_000),
    "gpt-5.6-luna": (200_000, 1_200_000, 1_000_000, 1_800_000),
    "gpt-6-sol": (2_000_000, 10_000_000, 10_000_000, 15_000_000),
}


class QualityBudgetStopped(RuntimeError):
    pass


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _cost(tokens: int, rate: int) -> int:
    return (tokens * rate + MICRO_USD - 1) // MICRO_USD


def budget_summary(path: Path) -> dict[str, Any]:
    state = json.loads(path.read_bytes())
    rows = state["calls"]
    return {"physical_calls": len(rows), "completed": sum(row.get("status") == "completed" for row in rows),
        "reserved_or_unknown": sum(row.get("status") != "completed" for row in rows),
        "budget_charge_usd": sum(row["charged_micro_usd"] for row in rows) / MICRO_USD,
        "known_price_estimate_usd": sum(row.get("estimated_cost_micro_usd", 0) for row in rows) / MICRO_USD,
        "last": [{key: row.get(key) for key in ("ordinal", "status", "http_status", "model", "input_tokens", "output_tokens")}
                 for row in rows[-3:]]}


def load_api_key(path: Path) -> str:
    """Read an owner-authorized file, decrypting DPAPI only in process memory."""
    if path.suffix != ".dpapi":
        key = path.read_text(encoding="utf-8-sig").strip()
    else:
        if os.name != "nt":
            raise ValueError("quality_api_dpapi_requires_windows_user")
        import ctypes
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

        encrypted = path.read_bytes()
        if not encrypted or len(encrypted) > 16_384:
            raise ValueError("quality_api_protected_key_invalid")
        source = (ctypes.c_ubyte * len(encrypted)).from_buffer_copy(encrypted)
        entropy_bytes = b"Kamilya-generation-quality-v1"
        entropy = (ctypes.c_ubyte * len(entropy_bytes)).from_buffer_copy(entropy_bytes)
        incoming, optional, outgoing = Blob(len(encrypted), source), Blob(len(entropy_bytes), entropy), Blob()
        crypt = ctypes.WinDLL("crypt32", use_last_error=True)
        crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        crypt.CryptUnprotectData.restype = wintypes.BOOL
        if not crypt.CryptUnprotectData(ctypes.byref(incoming), None, ctypes.byref(optional),
                                       None, None, 1, ctypes.byref(outgoing)):
            raise ValueError("quality_api_protected_key_unavailable_for_user")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        try:
            key = ctypes.string_at(outgoing.data, outgoing.size).decode("utf-8").strip()
        finally:
            kernel.LocalFree(ctypes.cast(outgoing.data, ctypes.c_void_p))
    if not key.startswith("sk-proj-") or len(key) > 4096 or any(char.isspace() for char in key):
        raise ValueError("quality_api_key_file_invalid")
    return key


class QualityAPISession:
    """One process owns one ledger, including reservations surviving interruptions."""

    def __init__(self, *, key_file: Path, ledger: Path, model: str = "gpt-6-luna",
                 output_tokens: int = 16_384, budget_micro_usd: int = MAX_BUDGET,
                 replay_requests: frozenset[str] = frozenset()):
        if model not in PRICES or type(output_tokens) is not int or not 512 <= output_tokens <= 32_768:
            raise ValueError("quality_api_profile_invalid")
        if type(budget_micro_usd) is not int or not 0 < budget_micro_usd <= MAX_BUDGET:
            raise ValueError("quality_api_budget_invalid")
        if not ledger.parent.is_dir() or ledger.is_symlink():
            raise ValueError("quality_api_evidence_directory_invalid")
        self._key = load_api_key(key_file)
        self.path, self.model = ledger, model
        self.output_tokens = output_tokens
        self.replay_requests, self.replayed = replay_requests, 0
        self._lock_path = ledger.with_suffix(".lock")
        self._descriptor = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        self._operation = asyncio.Lock()
        try:
            if ledger.exists():
                self.state = json.loads(ledger.read_text(encoding="utf-8"))
                if (self.state.get("schema") != "generation-quality-budget-v1"
                        or self.state.get("budget_micro_usd") != budget_micro_usd
                        or not isinstance(self.state.get("calls"), list)):
                    raise ValueError("quality_api_ledger_invalid")
                for row in self.state["calls"]:
                    if (not isinstance(row, dict) or type(row.get("charged_micro_usd")) is not int
                            or not 0 <= row["charged_micro_usd"] <= MAX_BUDGET):
                        raise ValueError("quality_api_ledger_invalid")
            else:
                self.state = {"schema": "generation-quality-budget-v1", "budget_micro_usd": budget_micro_usd, "calls": []}
                self._persist()
        except BaseException:
            os.close(self._descriptor)
            self._lock_path.unlink()
            self._key = ""
            raise
        self._http = httpx.AsyncClient(timeout=240, follow_redirects=False, trust_env=False)

    def _persist(self) -> None:
        temporary = self.path.with_suffix(".pending")
        with temporary.open("wb") as stream:
            stream.write(_json(self.state))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    @property
    def charged_micro_usd(self) -> int:
        return sum(row["charged_micro_usd"] for row in self.state["calls"])

    async def close(self) -> None:
        await self._http.aclose()
        self._key = ""
        if self._descriptor is not None:
            os.close(self._descriptor)
            self._descriptor = None
            self._lock_path.unlink()

    async def ainvoke_validated(self, messages: Any, parser: Callable[[str], Any],
                               response_format: dict | None = None, **kwargs: Any) -> Any:
        from app.modules.ai.llm_client import (
            AllProvidersFailedError,
            ValidatedCallFailureReason,
            ValidatedLLMResult,
            _structured_output_messages,
        )

        async with self._operation:
            if (not isinstance(messages, list) or any(not isinstance(row, dict)
                    or set(row) != {"role", "content"} or row["role"] not in {"system", "user", "assistant"}
                    or not isinstance(row["content"], str) for row in messages)):
                raise ValueError("quality_api_text_messages_only")
            wire_format = response_format or {"type": "json_object"}
            body = {"model": self.model, "messages": _structured_output_messages(messages, wire_format),
                    "max_completion_tokens": self.output_tokens, "reasoning_effort": "medium",
                    "service_tier": "default", "store": False,
                    "response_format": wire_format}
            encoded = _json(body)
            if len(encoded) > 524_288:
                raise QualityBudgetStopped("quality_api_request_bound")
            # Tokenization cannot use more ordinary text tokens than UTF-8 bytes;
            # reserve additional framing overhead. Tools/images are not accepted.
            request_sha256 = hashlib.sha256(encoded).hexdigest()
            if request_sha256 in self.replay_requests:
                saved = [row for row in self.state["calls"] if row.get("request_sha256") == request_sha256
                         and row.get("status") == "completed" and row.get("response_sha256")]
                if len(saved) != 1:
                    raise ValueError("quality_api_replay_not_unique")
                artifact = self.path.parent / f"response-{saved[0]['ordinal']:04d}.json"
                data = json.loads(artifact.read_bytes())
                if (hashlib.sha256(_json(data)).hexdigest() != saved[0]["response_sha256"]
                        or data.get("model") != self.model):
                    raise ValueError("quality_api_replay_identity_changed")
                value = parser(data["choices"][0]["message"]["content"])
                self.replayed += 1
                usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
                replay_prompt = usage.get("prompt_tokens", 0)
                replay_completion = usage.get("completion_tokens", 0)
                return ValidatedLLMResult(provider="openai-saved-response-replay", model_id=data["model"],
                    value=value, attempt_count=0, failure_reasons=(),
                    prompt_tokens=replay_prompt if type(replay_prompt) is int and replay_prompt >= 0 else 0,
                    completion_tokens=replay_completion if type(replay_completion) is int and replay_completion >= 0 else 0)
            _input, _output, ceiling_input, ceiling_output = PRICES[self.model]
            reserved = _cost(len(encoded) + 4096, ceiling_input) + _cost(self.output_tokens, ceiling_output)
            if self.charged_micro_usd + reserved > self.state["budget_micro_usd"]:
                raise QualityBudgetStopped("quality_api_budget_exhausted")
            record = {"ordinal": len(self.state["calls"]), "request_sha256": request_sha256,
                      "model": self.model, "reasoning": "medium", "status": "outcome_unknown",
                      "started_at_utc": datetime.now(UTC).isoformat(),
                      "reserved_micro_usd": reserved, "charged_micro_usd": reserved}
            self.state["calls"].append(record)
            self._persist()  # Durable admission precedes the only physical POST.
            started = perf_counter()
            try:
                response = await self._http.post(ENDPOINT, content=encoded,
                    headers={"Authorization": "Bearer " + self._key, "Content-Type": "application/json"})
                record["http_status"] = response.status_code
                if response.status_code != 200:
                    record["status"] = "http_rejected_usage_unknown"
                    try:
                        error = response.json().get("error", {})
                        allowed = {"messages", "response_format", "model", "max_completion_tokens", "reasoning_effort"}
                        record["error_param"] = error.get("param") if error.get("param") in allowed else None
                    except (ValueError, AttributeError):
                        pass
                    self._persist()
                    raise QualityBudgetStopped("quality_api_http_" + str(response.status_code))
                data = response.json()
                usage = data.get("usage", {})
                input_tokens, output_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
                if (type(input_tokens) is not int or type(output_tokens) is not int
                        or not 0 <= input_tokens <= len(encoded) + 4096
                        or not 0 <= output_tokens <= self.output_tokens):
                    raise QualityBudgetStopped("quality_api_usage_unavailable_or_outside_reservation")
                if data.get("model") != self.model:
                    raise QualityBudgetStopped("quality_api_model_identity_changed")
                record.update(input_tokens=input_tokens, output_tokens=output_tokens,
                    reasoning_tokens=usage.get("completion_tokens_details", {}).get("reasoning_tokens"),
                    status="completed", actual_model=data["model"],
                    charged_micro_usd=_cost(input_tokens, ceiling_input) + _cost(output_tokens, ceiling_output))
                # A price-table estimate is separate from the conservative budget charge.
                long_context = input_tokens > 272_000
                record["estimated_cost_micro_usd"] = (
                    _cost(input_tokens, _input * (2 if long_context else 1))
                    + _cost(output_tokens, (_output * 3 // 2) if long_context else _output))
                content = data["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise ValueError("quality_api_content_invalid")
                artifact = self.path.parent / f"response-{record['ordinal']:04d}.json"
                with artifact.open("xb") as stream:
                    stream.write(_json(data))
                record["response_sha256"] = hashlib.sha256(_json(data)).hexdigest()
                self._persist()  # Paid output survives even when its parser rejects.
                try:
                    value = parser(content)
                except (ValueError, TypeError, KeyError) as exc:
                    record["parser_error_class"] = type(exc).__name__
                    self._persist()
                    raise AllProvidersFailedError("Recorded model output failed native validation",
                        [ValidatedCallFailureReason.PROVIDER_OUTPUT_UNPARSEABLE]) from None
                return ValidatedLLMResult(provider="openai-quality-control", model_id=data["model"],
                    value=value, attempt_count=1, failure_reasons=(),
                    prompt_tokens=input_tokens, completion_tokens=output_tokens)
            finally:
                record["elapsed_seconds"] = round(perf_counter() - started, 3)
                self._persist()
