"""Provider-neutral transcript contract.

`TranscriptProvider` is the single external seam from the YouTube plan: callers
receive a normalized, provenance-carrying `TranscriptResult` and never see
adapter differences. Errors are classified as retryable or terminal so the
document pipeline can decide between re-enqueue and fail-fast.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.modules.youtube_transcript.url_resolver import YouTubeVideoRef

MAX_TOTAL_CHARS = 500_000
MAX_VIDEO_DURATION_SECONDS = 7200  # 120 minutes per plan §10
MAX_SEGMENTS = 50_000
MIN_TOTAL_CHARS = 200

SUPPORTED_LANGUAGES = frozenset({"ru", "kk", "en"})

_TIMESTAMP_SPLIT = re.compile(r"\s+")

# Stable error codes surfaced to the API and UI.
ERROR_CATALOG: dict[str, dict[str, str]] = {
    "transcript_unavailable": {
        "retryable": "false",
        "message_ru": "У видео нет доступных субтитров. Загрузите файл SRT, VTT или TXT.",
    },
    "language_unavailable": {
        "retryable": "false",
        "message_ru": "Субтитры на выбранном языке не найдены. Выберите другой язык или загрузите файл.",
    },
    "video_unavailable": {
        "retryable": "false",
        "message_ru": "Видео недоступно или удалено.",
    },
    "video_too_long": {
        "retryable": "false",
        "message_ru": "Видео длиннее допустимого лимита (120 минут).",
    },
    "transcript_too_short": {
        "retryable": "false",
        "message_ru": "Текст субтитров слишком короткий для создания курса.",
    },
    "transcript_too_large": {
        "retryable": "false",
        "message_ru": "Текст субтитров превышает допустимый размер.",
    },
    "provider_blocked": {
        "retryable": "true",
        "message_ru": "YouTube временно ограничил доступ. Повторите попытку позже.",
    },
    "provider_timeout": {
        "retryable": "true",
        "message_ru": "Источник не ответил вовремя. Повторите попытку позже.",
    },
    "provider_unavailable": {
        "retryable": "true",
        "message_ru": "Сервис получения субтитров недоступен. Повторите попытку позже.",
    },
}


class TranscriptAcquisitionError(RuntimeError):
    """Base class with stable code and retryable/terminal classification."""

    def __init__(self, code: str, message_ru: str | None = None):
        entry = ERROR_CATALOG.get(code)
        resolved = message_ru or (entry["message_ru"] if entry else "Неизвестная ошибка.")
        super().__init__(resolved)
        self.code = code
        self.message_ru = resolved
        self.retryable = bool(entry and entry["retryable"] == "true")


class TranscriptUnavailableError(TranscriptAcquisitionError):
    def __init__(self, code: str = "transcript_unavailable"):
        super().__init__(code)


class TranscriptProviderError(TranscriptAcquisitionError):
    """Retryable provider-side failure (network, block, timeout)."""


@dataclass
class TranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str

    def normalized_text(self) -> str:
        return _TIMESTAMP_SPLIT.sub(" ", self.text).strip()


@dataclass
class TranscriptResult:
    source_type: str
    video_id: str
    source_url: str
    canonical_url: str
    title: str
    channel: str | None
    language: str
    is_auto_generated: bool
    segments: list[TranscriptSegment]
    retrieved_at: datetime
    provider: str
    duration_seconds: float | None = None
    content_sha256: str = field(default="")

    def compute_content_hash(self) -> str:
        digest = hashlib.sha256()
        digest.update(self.video_id.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(self.language.encode("utf-8"))
        digest.update(b"\x00")
        for segment in self.segments:
            digest.update(
                f"{segment.start_seconds:.3f}|{segment.end_seconds:.3f}|{segment.normalized_text()}\n".encode()
            )
        return digest.hexdigest()

    def total_chars(self) -> int:
        return sum(len(s.normalized_text()) for s in self.segments)

    def to_plain_text(self) -> str:
        """Deterministic plain-text projection used as the ingestion source."""
        return "\n".join(f"[{_format_ts(s.start_seconds)}] {s.normalized_text()}" for s in self.segments)


def _format_ts(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


def validate_transcript(
    result: TranscriptResult,
    *,
    max_video_duration_seconds: int = MAX_VIDEO_DURATION_SECONDS,
    max_total_chars: int = MAX_TOTAL_CHARS,
) -> None:
    """Enforce plan §10 MVP limits; raise terminal errors on violation."""
    if result.duration_seconds is not None and result.duration_seconds > max_video_duration_seconds:
        raise TranscriptAcquisitionError("video_too_long")
    total = result.total_chars()
    if total > max_total_chars:
        raise TranscriptAcquisitionError("transcript_too_large")
    if len(result.segments) > MAX_SEGMENTS:
        raise TranscriptAcquisitionError("transcript_too_large")
    if total < MIN_TOTAL_CHARS:
        raise TranscriptAcquisitionError("transcript_too_short")


class TranscriptProvider(Protocol):
    """The one seam the rest of the system is allowed to know about."""

    async def get_transcript(
        self,
        video_ref: YouTubeVideoRef,
        preferred_languages: list[str],
    ) -> TranscriptResult:
        """Return a normalized transcript or raise TranscriptAcquisitionError."""
        ...
