"""Private model content, carried to the owned journal without claiming wire proof."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, cast
from uuid import UUID

_CODE = "v3_model_artifact_rejected"
_PHASES = {"provider_contract", "stage_validation", "stage_metadata", "stage_finalize"}


class ModelArtifactRejectedError(ValueError):
    """Never authorizes acceptance, retry, refund or unscoped persistence."""

    __slots__ = ("_raw", "_metadata", "_job", "_route", "_request", "_phase", "_sealed")

    def __init__(self, content: str, *, provider: str | None = None, model: str | None = None,
                 input_tokens: int | None = None, output_tokens: int | None = None,
                 job_id: str | None = None, route: str | None = None, request: str | None = None,
                 phase: str = "provider_contract"):
        super().__init__(_CODE)
        raw = content.encode("utf-8")
        if len(raw) > 2 * 1024 * 1024 or phase not in _PHASES:
            raise ValueError("v3_rejected_artifact_invalid")
        self._raw = raw
        self._metadata = MappingProxyType({"provider": provider if isinstance(provider, str) and re.fullmatch(r"[a-z0-9_-]{1,64}", provider) else None,
            "reported_model": model if isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9._/-]{1,128}", model) else None,
            "input_tokens": input_tokens if type(input_tokens) is int and input_tokens >= 0 else None,
            "output_tokens": output_tokens if type(output_tokens) is int and output_tokens >= 0 else None})
        self._job, self._route, self._request, self._phase = job_id, route, request, phase
        self._sealed = True

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False) and name not in {"__traceback__", "__cause__", "__context__", "__suppress_context__"}:
            raise AttributeError("v3_rejected_artifact_immutable")
        super().__setattr__(name, value)

    def __repr__(self) -> str:
        return f"ModelArtifactRejectedError({_CODE!r})"

    def bound(self, *, job_id: str, route: str, request: str, phase: str | None = None) -> ModelArtifactRejectedError:
        if self._job is not None or self._route is not None or self._request is not None:
            raise ValueError("v3_rejected_artifact_already_bound")
        if (str(UUID(job_id)) != job_id or not re.fullmatch(r"[0-9a-f]{64}", route)
                or not re.fullmatch(r"[0-9a-f]{64}", request)):
            raise ValueError("v3_rejected_artifact_scope_invalid")
        return ModelArtifactRejectedError(self._raw.decode("utf-8"), provider=cast(str | None, self._metadata["provider"]),
            model=cast(str | None, self._metadata["reported_model"]), input_tokens=cast(int | None, self._metadata["input_tokens"]),
            output_tokens=cast(int | None, self._metadata["output_tokens"]), job_id=job_id, route=route, request=request,
            phase=phase or self._phase)

    def checked_receipt(self, *, job_id: str, route: str, request: str) -> dict[str, Any]:
        if (self._job, self._route, self._request) != (job_id, route, request) or self._job is None:
            raise ValueError("v3_rejected_artifact_scope_invalid")
        return {"policy": "v3-provider-artifact-v1", "accepted": False, "capture_kind": "model_content_text",
            "complete_http_response": False, "status": None, **self._metadata,
            "raw_base64": base64.b64encode(self._raw).decode("ascii"), "byte_count": len(self._raw),
            "body_sha256": hashlib.sha256(self._raw).hexdigest(), "request_sha256": self._request,
            "phase": self._phase}

    @classmethod
    def from_value(cls, value: dict[str, Any], *, job_id: str, route: str, request: str, phase: str) -> ModelArtifactRejectedError:
        content = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return cls(content).bound(job_id=job_id, route=route, request=request, phase=phase)
