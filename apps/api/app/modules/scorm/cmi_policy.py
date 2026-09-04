from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CmiPolicyLimits:
    max_entries: int = 256
    max_key_bytes: int = 128
    max_value_bytes: int = 8 * 1024
    max_suspend_data_bytes: int = 64 * 1024
    max_raw_bytes: int = 128 * 1024
    max_persisted_bytes: int = 256 * 1024


@dataclass(frozen=True)
class NormalizedCmiPatch:
    patch: dict[str, str]
    merged: dict[str, Any]


class CmiPolicyError(ValueError):
    def __init__(self, code: str, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.status_code = status_code
        self.detail = detail


_EXACT_KEYS = {
    "lesson_status",
    "cmi.lesson_status",
    "cmi.suspend_data",
    "cmi.launch_data",
    "cmi.comments",
}
_KEY_PATTERNS = (
    re.compile(r"^cmi\.core\.(?:lesson_location|lesson_status|score\.(?:raw|max|min)|exit|session_time|total_time)$"),
    re.compile(r"^cmi\.student_preference\.(?:audio|language|speed|text)$"),
    re.compile(r"^cmi\.objectives\.[0-9]+\.(?:id|status|score\.(?:raw|max|min))$"),
    re.compile(r"^cmi\.interactions\.[0-9]+\.(?:id|time|type|weighting|student_response|result|latency)$"),
    re.compile(r"^cmi\.interactions\.[0-9]+\.objectives\.[0-9]+\.id$"),
    re.compile(r"^cmi\.interactions\.[0-9]+\.correct_responses\.[0-9]+\.pattern$"),
)
_STATUS_KEYS = {"lesson_status", "cmi.lesson_status", "cmi.core.lesson_status"}
_LESSON_STATUSES = {"passed", "completed", "failed", "incomplete", "browsed", "not attempted"}
_OBJECTIVE_STATUS_KEY = re.compile(r"^cmi\.objectives\.[0-9]+\.status$")
_SCORE_KEY = re.compile(r"^(?:cmi\.core|cmi\.objectives\.[0-9]+)\.score\.(?:raw|max|min)$")
_DECIMAL_VALUE = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)$")


class CmiCommitPolicy:
    """Validate and normalize SCORM CMI before ORM state is changed."""

    def __init__(self, limits: CmiPolicyLimits | None = None) -> None:
        self._limits = limits or CmiPolicyLimits()

    def validate(
        self,
        raw_patch: Mapping[str, Any],
        existing_state: Mapping[str, Any] | None,
        *,
        raw_content_length: str | int | None = None,
    ) -> NormalizedCmiPatch:
        self._validate_declared_length(raw_content_length)
        if not isinstance(raw_patch, Mapping):
            raise CmiPolicyError("invalid_cmi_payload", 422, "CMI must be an object")
        if len(raw_patch) > self._limits.max_entries:
            raise CmiPolicyError("too_many_cmi_entries", 413, "CMI contains too many entries")
        if self._json_size({"cmi": raw_patch}) > self._limits.max_raw_bytes:
            raise CmiPolicyError("cmi_request_too_large", 413, "CMI request exceeds the allowed size")

        normalized: dict[str, str] = {}
        for key, raw_value in raw_patch.items():
            if not isinstance(key, str) or not key or key != key.strip():
                raise CmiPolicyError("unsupported_cmi_key", 422, "CMI contains an unsupported key")
            if len(key.encode("utf-8")) > self._limits.max_key_bytes:
                raise CmiPolicyError("cmi_key_too_large", 413, "CMI key exceeds the allowed size")
            if not self._is_supported_key(key):
                raise CmiPolicyError("unsupported_cmi_key", 422, "CMI contains an unsupported key")
            if not isinstance(raw_value, str):
                raise CmiPolicyError("invalid_cmi_value_type", 422, "CMI values must be strings")

            is_status = key in _STATUS_KEYS or _OBJECTIVE_STATUS_KEY.fullmatch(key) is not None
            value = raw_value.strip() if is_status else raw_value
            if is_status:
                value = value.lower()
                if value not in _LESSON_STATUSES:
                    raise CmiPolicyError("invalid_lesson_status", 422, "CMI lesson status is invalid")
            elif _SCORE_KEY.fullmatch(key):
                value = value.strip()
                if not _DECIMAL_VALUE.fullmatch(value):
                    raise CmiPolicyError("invalid_cmi_score", 422, "CMI score must be a finite decimal")
            value_limit = (
                self._limits.max_suspend_data_bytes if key == "cmi.suspend_data" else self._limits.max_value_bytes
            )
            if len(value.encode("utf-8")) > value_limit:
                raise CmiPolicyError("cmi_value_too_large", 413, "CMI value exceeds the allowed size")
            normalized[key] = value

        merged = {**dict(existing_state or {}), **normalized}
        if self._json_size(merged) > self._limits.max_persisted_bytes:
            raise CmiPolicyError("cmi_state_too_large", 413, "CMI state exceeds the allowed size")
        return NormalizedCmiPatch(patch=normalized, merged=merged)

    def _validate_declared_length(self, raw_content_length: str | int | None) -> None:
        if raw_content_length is None or raw_content_length == "":
            return
        try:
            declared = raw_content_length if isinstance(raw_content_length, int) else int(raw_content_length)
        except (TypeError, ValueError):
            raise CmiPolicyError("invalid_content_length", 422, "Invalid Content-Length") from None
        if declared < 0:
            raise CmiPolicyError("invalid_content_length", 422, "Invalid Content-Length")
        if declared > self._limits.max_raw_bytes:
            raise CmiPolicyError("cmi_request_too_large", 413, "CMI request exceeds the allowed size")

    @staticmethod
    def _is_supported_key(key: str) -> bool:
        return key in _EXACT_KEYS or any(pattern.fullmatch(key) for pattern in _KEY_PATTERNS)

    @staticmethod
    def _json_size(value: object) -> int:
        try:
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        except (TypeError, ValueError):
            raise CmiPolicyError("invalid_cmi_payload", 422, "CMI must be JSON-compatible") from None
        return len(encoded)
