"""Fail-safe redaction boundaries for application logs and error telemetry."""

from __future__ import annotations

import logging
import re
import traceback
from collections.abc import Mapping, Sequence
from typing import Any

REDACTED = "<redacted>"

_EMAIL_RE = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[a-z0-9.-]+\.[a-z]{2,}(?![\w.-])")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?7|8)(?:[\s().-]*\d){10}(?!\d)")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_JWT_RE = re.compile(r"(?<![\w-])eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(?![\w-])")
_SENSITIVE_PAIR_RE = re.compile(
    r"(?i)(\b(?:personnel_number|pin|passcode|password|otp|code|token|access_token|"
    r"refresh_token|api_key|secret|authorization)\b\s*[=:]\s*)"
    r"(?:[\"']?)[^\s&,;\"']+(?:[\"']?)"
)
_CAPABILITY_PATH_RE = re.compile(
    r"(?i)(/(?:access|candidate-assessment|kiosk)/)[A-Za-z0-9_-]{8,}"
)

_SENSITIVE_KEY_FRAGMENTS = (
    "authorization",
    "cookie",
    "email",
    "phone",
    "personnel_number",
    "password",
    "passcode",
    "pin",
    "otp",
    "token",
    "secret",
    "api_key",
    "prompt",
    "llm_output",
    "model_output",
    "response_body",
    "request_body",
    "document_text",
    "source_text",
)

_STANDARD_LOG_RECORD_KEYS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
)


def redact_sensitive_text(value: str) -> str:
    """Remove common credentials and direct identifiers from free-form text."""

    redacted = _BEARER_RE.sub("Bearer <redacted-token>", value)
    redacted = _JWT_RE.sub("<redacted-token>", redacted)
    redacted = _EMAIL_RE.sub("<redacted-email>", redacted)
    redacted = _PHONE_RE.sub("<redacted-phone>", redacted)
    redacted = _SENSITIVE_PAIR_RE.sub(lambda match: f"{match.group(1)}{REDACTED}", redacted)
    return _CAPABILITY_PATH_RE.sub(r"\1<redacted-token>", redacted)


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower()
    return any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS)


def scrub_sensitive_data(value: Any, *, _depth: int = 0) -> Any:
    """Return a bounded, recursively redacted copy for telemetry payloads."""

    if _depth >= 12:
        return REDACTED
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, Mapping):
        return {
            key: REDACTED if _is_sensitive_key(key) else scrub_sensitive_data(item, _depth=_depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(scrub_sensitive_data(item, _depth=_depth + 1) for item in value)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [scrub_sensitive_data(item, _depth=_depth + 1) for item in value]
    return value


class SensitiveDataFilter(logging.Filter):
    """Redact every formatted LogRecord before a handler emits it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact_sensitive_text(record.getMessage())
            record.args = ()
            if record.exc_info:
                record.exc_text = redact_sensitive_text("".join(traceback.format_exception(*record.exc_info)))
                record.exc_info = None
            if record.stack_info:
                record.stack_info = redact_sensitive_text(record.stack_info)
            for key, value in tuple(record.__dict__.items()):
                if key in _STANDARD_LOG_RECORD_KEYS:
                    continue
                if _is_sensitive_key(key):
                    setattr(record, key, REDACTED)
                elif isinstance(value, str):
                    setattr(record, key, redact_sensitive_text(value))
        except Exception:
            # Logging must remain available even if an exotic record value is
            # not redaction-compatible. Call sites still avoid raw content.
            record.msg = "log message redaction failed"
            record.args = ()
        return True


def install_sensitive_logging_filters() -> None:
    """Attach redaction to every currently configured root handler."""

    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(item, SensitiveDataFilter) for item in handler.filters):
            handler.addFilter(SensitiveDataFilter())


def scrub_sentry_event(event: dict[str, Any], _hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Sentry ``before_send`` callback with the same redaction contract."""

    return scrub_sensitive_data(event)
