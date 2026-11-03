"""Owner-bound, non-authorizing quarantine of a complete rejected response."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.modules.ai.direct_luna_responses_client import ResponsesResult
from app.modules.ai.managed_luna_client import MAX_RESPONSE_BYTES, MODEL, ManagedLunaError

_CODE = "managed_luna_response_rejected"
_PHASES = frozenset({"envelope", "model", "choices", "message", "content_limit", "content_json", "usage", "structured_mode", "structured_shape", "stage_validation", "stage_metadata", "stage_finalize"})
_SUBTYPES = {"source_first_qa_duplicate_key": "duplicate", "source_first_qa_nonfinite_number": "nonfinite",
             "source_first_qa_response_invalid": "nonobject"}


def _hex(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _canonical_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


class ManagedResponseRejectedError(ManagedLunaError):
    """Raw bytes are accessible only through exact scope and route verification."""

    __slots__ = ("_scope", "_stage", "_route", "_wire_hash", "_phase", "_raw", "_subtype", "_position", "_model", "_sealed")

    def for_completed_stage(self, phase: str, cause: Exception) -> ManagedResponseRejectedError:
        if phase not in {"stage_validation", "stage_metadata", "stage_finalize"}:
            raise ValueError("managed_completed_phase_invalid")
        return ManagedResponseRejectedError(raw=self._raw, tenant_id=self._scope[0], user_id=self._scope[1],
            job_id=self._scope[2], stage=self._stage, route_fingerprint=self._route,
            wire_request_sha256=self._wire_hash, phase=phase, cause=cause, configured_model=self._model)

    def __init__(self, *, raw: bytes, tenant_id: UUID, user_id: UUID, job_id: str, stage: str,
                 route_fingerprint: str, wire_request_sha256: str, phase: str, cause: Exception,
                 configured_model: str = MODEL):
        if (type(raw) is not bytes or len(raw) > MAX_RESPONSE_BYTES or type(tenant_id) is not UUID
                or type(user_id) is not UUID or not _canonical_uuid(job_id) or not _hex(stage)
                or not _hex(route_fingerprint) or not _hex(wire_request_sha256)
                or not isinstance(phase, str) or phase not in _PHASES or not isinstance(cause, Exception)
                or type(configured_model) is not str or configured_model not in {MODEL, "gpt-6-luna"}):
            raise ValueError("managed_rejection_invalid")
        super().__init__(_CODE)
        self._scope = (tenant_id, user_id, job_id)
        self._model = configured_model
        self._stage, self._route, self._wire_hash, self._phase, self._raw = (
            stage, route_fingerprint, wire_request_sha256, phase, raw,
        )
        self._subtype = "unverified"
        self._position: tuple[int, int, int] | None = None
        if (type(cause) is json.JSONDecodeError and type(cause.pos) is int and 0 <= cause.pos <= len(cause.doc)
                and type(cause.lineno) is int and cause.lineno >= 1
                and type(cause.colno) is int and cause.colno >= 1):
            self._subtype = "syntax"
            self._position = (cause.pos, cause.lineno, cause.colno)
        elif type(cause) is ValueError:
            self._subtype = _SUBTYPES.get(str(cause), "unverified")
        self._sealed = True

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False) and name not in {"__traceback__", "__cause__", "__context__", "__suppress_context__"}:
            raise AttributeError("managed_rejection_immutable")
        super().__setattr__(name, value)

    def __repr__(self) -> str:
        return f"ManagedResponseRejectedError({_CODE!r})"

    def checked_receipt(self, *, tenant_id: str, user_id: UUID, job_id: str, stage: str,
                        route_fingerprint: str) -> dict[str, Any]:
        if (not _canonical_uuid(tenant_id) or type(user_id) is not UUID or not _canonical_uuid(job_id)
                or not _hex(stage) or not _hex(route_fingerprint)
                or (UUID(tenant_id), user_id, job_id) != self._scope or stage != self._stage
                or route_fingerprint != self._route):
            raise ValueError("managed_rejection_scope_invalid")
        pos, line, col = self._position if self._position is not None else (None, None, None)
        return {"policy": "managed-response-quarantine-v1", "accepted": False,
                "complete_http_response": True, "status": 200, "configured_model": self._model,
                "raw_base64": base64.b64encode(self._raw).decode("ascii"),
                "body_sha256": hashlib.sha256(self._raw).hexdigest(), "byte_count": len(self._raw),
                "wire_request_sha256": self._wire_hash, "phase": self._phase, "subtype": self._subtype,
                "position": pos, "line": line, "column": col}


@dataclass(frozen=True, repr=False)
class ManagedResponsesResult(ResponsesResult):
    """A successful transport retains one private capture until stage completion."""

    _capture: ManagedResponseRejectedError | None = field(default=None, repr=False, compare=False)

    def rejection_for(self, phase: str, cause: Exception) -> ManagedResponseRejectedError | None:
        return self._capture.for_completed_stage(phase, cause) if self._capture is not None else None
