"""One-attempt managed CLI connector client; local preparation is not token counting."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import httpx

from app.modules.admin.model_routing.chatgpt_reserve import configuration_blocker
from app.modules.ai.credential_content_guard import contains_credential
from app.modules.ai.direct_luna_api import LunaUsage
from app.modules.ai.direct_luna_responses_client import ResponsesResult
from app.modules.ai.source_first_response import parse_source_first_response
from app.modules.ai.v3.practical_author_transport import PracticalAuthorArtifact

MODEL = "gpt-5.6-luna"
LUNA6_MODEL = "gpt-6-luna"
MAX_INPUT_BYTES = 524288
MAX_RESPONSE_BYTES = 2097152
MAX_CONTENT_BYTES = 262144
logger = logging.getLogger(__name__)
ERROR_CODES = frozenset({"not_configured", "authorization_required", "unavailable", "protocol_mismatch",
                         "busy", "invalid_input", "timeout", "output_limit", "tool_use_rejected"})


def _unsafe_credential_envelope(raw: bytes, token: str) -> bool:
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        return True
    return contains_credential(text, token, embedded_json=True)


def _diagnostic(phase: str, job_id: str, stage_id: str | None, started: float,
                status: int | None, category: str, incoming: int | None = None,
                outgoing: int | None = None) -> None:
    try:
        canonical_job = str(UUID(job_id)) if str(UUID(job_id)) == job_id else None
    except (ValueError, TypeError, AttributeError):
        canonical_job = None
    def bounded(value: object, minimum: int = 0, maximum: int = 2**63 - 1) -> int | None:
        return value if type(value) is int and minimum <= value <= maximum else None

    try:
        elapsed = bounded(int((time.monotonic() - started) * 1000))
        logger.info("managed_luna phase=%s job_id=%s stage_sha256=%s status=%s elapsed_ms=%s category=%s input_tokens=%s output_tokens=%s",
                    phase, canonical_job, stage_id, bounded(status, 100, 599), elapsed,
                    category, bounded(incoming), bounded(outgoing))
    except Exception:
        pass



class ManagedLunaError(RuntimeError):
    """Sanitized connector failure."""


class ManagedLunaCompletedJsonError(ManagedLunaError):
    """A complete HTTP 200 response had content that was not a valid JSON object."""


class _ResponseDecodeError(Exception):
    def __init__(self, phase: str, original: Exception):
        self.phase, self.original = phase, original
        super().__init__(phase)


class ManagedLunaClient:
    def __init__(self, *, base_url: str, api_key: str, tenant_id: UUID, user_id: UUID, job_id: str,
                 credential_revision: str, deadline_seconds: float = 60.0, reasoning_effort: str = "low",
                 model: str = MODEL):
        config = SimpleNamespace(CHATGPT_RESERVE_URL=base_url, CHATGPT_RESERVE_TOKEN=api_key,
                                 CHATGPT_RESERVE_MODEL=model, CHATGPT_RESERVE_AUTH_MODE="codex_cli")
        if (not isinstance(base_url, str) or not isinstance(api_key, str) or not api_key.strip()
                or not isinstance(tenant_id, UUID) or not isinstance(user_id, UUID)
                or not isinstance(job_id, str) or not job_id.strip()
                or not isinstance(credential_revision, str) or not credential_revision.strip()
                or isinstance(deadline_seconds, bool) or not isinstance(deadline_seconds, int | float)
                or type(model) is not str or model not in (MODEL, LUNA6_MODEL)
                or not 0 < deadline_seconds <= (300 if model == LUNA6_MODEL else 120)
                or type(reasoning_effort) is not str
                or reasoning_effort not in (("low", "medium", "high") if model == LUNA6_MODEL else ("low", "medium"))
                or configuration_blocker(cast(Any, config)) is not None):
            raise ValueError("managed_luna_config_invalid")
        base = base_url.rstrip("/")
        self._url = (base if base.endswith("/v1") else base + "/v1") + "/chat/completions"
        self._token = api_key
        self._model = model
        self._revision = credential_revision
        self._scope = (tenant_id, user_id, job_id)
        self._deadline = float(deadline_seconds)
        self._reasoning_effort = reasoning_effort
        self._prepared: dict[object, bytes] = {}
        self._closed = False

    def __repr__(self) -> str:
        return "ManagedLunaClient(<redacted>)"

    @property
    def model(self) -> str:
        """Return the constructor-validated model bound to this client's route."""
        return self._model

    @property
    def generation_deadline_seconds(self) -> float:
        return self._deadline

    def cache_fingerprint(self) -> str:
        policy = json.dumps(["managed-cli-v1", self._url, self._model, self._reasoning_effort, "json-object",
                             self._deadline, self._revision], separators=(",", ":")).encode()
        return hmac.new(self._token.encode(), policy, hashlib.sha256).hexdigest()

    async def _check(self, checkpoint: Callable[[], Awaitable[bool]]) -> None:
        allowed = False
        try:
            allowed = callable(checkpoint) and await checkpoint() is True
        except Exception:
            pass
        if not allowed:
            raise ManagedLunaError("managed_luna_ownership_unverified")

    async def prepare(self, messages: list[dict[str, str]], *, max_output_tokens: int,
                      ownership_checkpoint: Callable[[], Awaitable[bool]],
                      response_format: dict[str, Any] | None = None) -> object:
        if self._closed:
            raise ManagedLunaError("managed_luna_closed")
        if (not isinstance(messages, list) or not 1 <= len(messages) <= 100
                or any(not isinstance(m, dict) or set(m) != {"role", "content"}
                       or m.get("role") not in {"system", "developer", "user", "assistant"}
                       or not isinstance(m.get("content"), str) for m in messages)
                or type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 32768):
            raise ValueError("managed_luna_request_invalid")
        request = {"model": self._model, "messages": messages, "temperature": 0.2,
                   "max_tokens": max_output_tokens, "response_format": {"type": "json_object"}}
        if self._reasoning_effort != "low":
            request["reasoning_effort"] = self._reasoning_effort
        if response_format is not None:
            from app.modules.ai.v3.response_contracts import response_contract
            if response_contract(response_format) is None:
                raise ValueError("managed_luna_structured_format_invalid")
            request["response_format"] = response_format
            request["structured_output_policy"] = "typed-json-object-v1"
        encoded = json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        # The CLI runner reserializes with json.dumps default separators.
        if len(json.dumps(request, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_INPUT_BYTES:
            raise ValueError("managed_luna_request_too_large")
        await self._check(ownership_checkpoint)
        if self._closed:
            raise ManagedLunaError("managed_luna_closed")
        capability = object()
        self._prepared[capability] = encoded
        return capability

    def discard(self, capability: object) -> None:
        try:
            self._prepared.pop(capability, None)
        except TypeError:
            pass

    def close(self) -> None:
        self._prepared.clear()
        self._token = ""
        self._closed = True

    def _decode_response(self, raw: bytes, payload: bytes) -> tuple[ResponsesResult, str]:
        category = "envelope"
        try:
            body = parse_source_first_response(raw.decode("utf-8"))
            category = "model"
            if body.get("model") != self._model:
                raise ValueError
            category = "structured_mode"
            requested = json.loads(payload)
            if "structured_output_policy" in requested:
                from app.modules.ai.v3.response_contracts import response_contract_hash
                if (body.get("structured_output_policy") != "typed-json-object-v1"
                        or body.get("response_format_sha256") != response_contract_hash(requested["response_format"])):
                    raise ValueError("managed_luna_structured_mode_unverified")
            elif "structured_output_policy" in body or "response_format_sha256" in body:
                raise ValueError("managed_luna_unrequested_structured_mode")
            category = "choices"
            choices = body.get("choices")
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError
            category = "message"
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if (not isinstance(message, dict) or set(message) not in ({"content"}, {"role", "content"})
                    or message.get("role", "assistant") != "assistant" or not isinstance(message.get("content"), str)):
                raise ValueError
            category = "content_limit"
            if len(message["content"].encode("utf-8")) > MAX_CONTENT_BYTES:
                raise ValueError
            category = "content_json"
            parsed_content = parse_source_first_response(message["content"])
            content: dict[str, Any] | PracticalAuthorArtifact = parsed_content
            if "structured_output_policy" in requested:
                from app.modules.ai.v3.response_contracts import matches_transport_contract
                category = "structured_shape"
                from app.modules.ai.v3.practical_contract import is_practical_course_format
                from app.modules.ai.v3.simple_course_editor import is_simple_editor_format
                from app.modules.ai.v3.simple_course_revision_v2 import is_simple_revision_v2_format
                if (is_practical_course_format(requested["response_format"]) or is_simple_editor_format(requested["response_format"])
                        or is_simple_revision_v2_format(requested["response_format"])):
                    if contains_credential(message["content"], self._token):
                        raise ValueError("managed_luna_structured_shape_invalid")
                    from app.modules.ai.v3.practical_author_transport import normalize_practical_author
                    artifact = normalize_practical_author(message["content"], requested["response_format"])
                    content = artifact
                    checked_content = artifact.normalized_value
                else:
                    checked_content = parsed_content
                if not matches_transport_contract(checked_content, requested["response_format"]):
                    raise ValueError("managed_luna_structured_shape_invalid")
            category = "usage"
            usage = body.get("usage")
            if not isinstance(usage, dict):
                raise ValueError
            incoming, outgoing = usage.get("prompt_tokens"), usage.get("completion_tokens")
            if type(incoming) is not int or incoming < 0 or type(outgoing) is not int or not 0 <= outgoing <= requested["max_tokens"]:
                raise ValueError
            return ResponsesResult(content=content, model=self._model, usage=LunaUsage(incoming, outgoing, None, None)), category
        except Exception as exc:
            raise _ResponseDecodeError(category, exc) from None

    async def replay_completed(self, capability: object, *, receipt: dict[str, Any], tenant_id: UUID,
                               user_id: UUID, job_id: str, stage_id: str,
                               ownership_checkpoint: Callable[[], Awaitable[bool]],
                               stage_plan: dict[str, Any] | None = None) -> ResponsesResult:
        """Consume an exact retained structured-shape response without a network request."""
        try:
            payload = self._prepared.pop(capability, None)
        except TypeError:
            payload = None
        if (payload is None or self._closed or (tenant_id, user_id, job_id) != self._scope
                or not isinstance(stage_id, str) or not re.fullmatch(r"[0-9a-f]{64}", stage_id)):
            raise ManagedLunaError("managed_luna_capability_invalid")
        await self._check(ownership_checkpoint)
        try:
            if (self._closed or not isinstance(receipt, dict)
                    or receipt.get("policy") != "managed-response-quarantine-v1"
                    or receipt.get("accepted") is not False or receipt.get("complete_http_response") is not True
                    or type(receipt.get("status")) is not int or receipt["status"] != 200
                    or receipt.get("phase") not in {"structured_shape", "stage_finalize"} or receipt.get("stage_sha256") != stage_id
                    or receipt.get("route_fingerprint") != self.cache_fingerprint()
                    or receipt.get("wire_request_sha256") != hashlib.sha256(payload).hexdigest()):
                raise ValueError
            raw = base64.b64decode(receipt["raw_base64"], validate=True)
            if (len(raw) > MAX_RESPONSE_BYTES or type(receipt.get("byte_count")) is not int
                    or receipt["byte_count"] != len(raw) or receipt.get("body_sha256") != hashlib.sha256(raw).hexdigest()):
                raise ValueError
            request = json.loads(payload)
            from app.modules.ai.v3.response_contracts import response_contract
            kind = response_contract(request.get("response_format"))
            if kind not in {"practical_course", "practical_editorial_verification"}:
                raise ValueError
            if receipt['phase'] == 'stage_finalize':
                from app.modules.ai.v3.retained_author_replay import is_focused_author_plan
                from app.modules.ai.v3.stage_checkpoint import _digest
                if (not is_focused_author_plan(stage_plan) or kind != 'practical_course'
                        or not isinstance(stage_plan, dict) or stage_plan.get('schema') != 'v3-stage-checkpoint-v1'
                        or stage_plan.get('tenant_id') != str(tenant_id) or stage_plan.get('job_id') != job_id
                        or not isinstance(stage_plan.get('source_sha256'), str)
                        or re.fullmatch(r'[0-9a-f]{64}', stage_plan['source_sha256']) is None
                        or stage_plan.get('route_fingerprint') != self.cache_fingerprint()
                        or stage_plan.get('request_sha256') != _digest([request['messages'], request['response_format']])
                        or _digest(stage_plan) != stage_id):
                    raise ValueError
            result, _ = self._decode_response(raw, payload)
            return result
        except Exception:
            raise ManagedLunaError("managed_luna_replay_unverified") from None

    async def invoke(self, capability: object, *, tenant_id: UUID, user_id: UUID, job_id: str,
                     ownership_checkpoint: Callable[[], Awaitable[bool]], stage_id: str | None = None,
                     classify_invalid_json: bool = False) -> ResponsesResult:
        try:
            payload = self._prepared.pop(capability, None)
        except TypeError:
            payload = None
        if (payload is None or self._closed or (tenant_id, user_id, job_id) != self._scope
                or stage_id is not None and (not isinstance(stage_id, str) or not re.fullmatch(r"[0-9a-f]{64}", stage_id))):
            raise ManagedLunaError("managed_luna_capability_invalid")
        await self._check(ownership_checkpoint)
        if self._closed:
            raise ManagedLunaError("managed_luna_closed")
        started = time.monotonic()
        status = None
        category = "transport"
        _diagnostic("attempt", job_id, stage_id, started, None, "started")
        failed = False
        raw = bytearray()
        try:
            async with asyncio.timeout(self._deadline):
                async with httpx.AsyncClient(timeout=self._deadline, follow_redirects=False, trust_env=False) as client:
                    if self._closed:
                        raise ManagedLunaError("managed_luna_closed")
                    async with client.stream("POST", self._url, content=payload,
                        headers={"Authorization": "Bearer " + self._token, "Content-Type": "application/json",
                                 "Accept-Encoding": "identity"}) as response:
                        status = response.status_code
                        if status != 200:
                            failed = True
                            category = "http_error"
                            error_raw = bytearray()
                            async for chunk in response.aiter_raw():
                                if len(error_raw) + len(chunk) > 4096:
                                    break
                                error_raw.extend(chunk)
                            try:
                                parsed_error = json.loads(error_raw)
                                code = parsed_error.get("error") if isinstance(parsed_error, dict) else None
                                if isinstance(code, str) and code in ERROR_CODES:
                                    category = code
                            except Exception:
                                pass
                        elif response.headers.get("content-encoding", "identity").lower() != "identity":
                            category = "encoding"
                            failed = True
                        else:
                            async for chunk in response.aiter_raw():
                                raw.extend(chunk)
                                if len(raw) > MAX_RESPONSE_BYTES:
                                    category = "response_limit"
                                    failed = True
                                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            failed = True
        if failed:
            _diagnostic("failure", job_id, stage_id, started, status, category)
            raise ManagedLunaError("managed_luna_outcome_unknown")
        _diagnostic("response", job_id, stage_id, started, status, "body_received")
        try:
            decoded, _ = self._decode_response(bytes(raw), payload)
            incoming, outgoing = decoded.usage.input_tokens, decoded.usage.output_tokens
            from app.modules.ai.managed_response_rejection import ManagedResponseRejectedError, ManagedResponsesResult
            capture = None
            if stage_id is not None and not _unsafe_credential_envelope(bytes(raw), self._token):
                try:
                    capture = ManagedResponseRejectedError(raw=bytes(raw), tenant_id=tenant_id, user_id=user_id,
                        job_id=job_id, stage=stage_id, route_fingerprint=self.cache_fingerprint(),
                        wire_request_sha256=hashlib.sha256(payload).hexdigest(), phase="stage_validation",
                        cause=ValueError("managed_stage_validation_unverified"), configured_model=self._model)
                except (ValueError, TypeError):
                    pass
            result = ManagedResponsesResult(content=decoded.content, model=decoded.model, usage=decoded.usage, _capture=capture)
        except _ResponseDecodeError as rejection:
            category = rejection.phase
            _diagnostic("failure", job_id, stage_id, started, status, category)
            if classify_invalid_json and status == 200 and category == "content_json":
                raise ManagedLunaCompletedJsonError("managed_luna_response_invalid") from None
            if stage_id is not None and not _unsafe_credential_envelope(bytes(raw), self._token):
                from app.modules.ai.managed_response_rejection import ManagedResponseRejectedError
                try:
                    retained = ManagedResponseRejectedError(raw=bytes(raw), tenant_id=tenant_id, user_id=user_id,
                        job_id=job_id, stage=stage_id, route_fingerprint=self.cache_fingerprint(),
                        wire_request_sha256=hashlib.sha256(payload).hexdigest(), phase=category, cause=rejection.original,
                        configured_model=self._model)
                except (ValueError, TypeError):
                    pass
                else:
                    raise retained from None
            raise ManagedLunaError("managed_luna_response_invalid") from None
        _diagnostic("response", job_id, stage_id, started, status, "validated", incoming, outgoing)
        return result
