"""Normalization of a TranscriptResult into the existing document pipeline.

The transcript becomes an ordinary Kamilya text source: a deterministic
markdown-like plain text with timestamp markers, a stable
`document:<sha256>` source revision, and provenance metadata. No parallel RAG
or second content table is created (plan §7).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.modules.youtube_transcript.provider import TranscriptResult, validate_transcript


class TranscriptLimitError(ValueError):
    """Terminal limit violation raised after validation."""

    def __init__(self, code: str, message_ru: str):
        super().__init__(message_ru)
        self.code = code
        self.message_ru = message_ru


@dataclass(frozen=True)
class NormalizedTranscriptSource:
    """Everything the document/ingestion seam needs from one transcript."""

    title: str
    filename: str
    content_type: str
    plain_text: str
    source_revision: str
    content_sha256: str
    provenance: dict


def normalize_transcript(
    result: TranscriptResult,
    *,
    max_video_duration_seconds: int | None = None,
    max_total_chars: int | None = None,
) -> NormalizedTranscriptSource:
    """Validate, project to plain text, and compute the canonical revision.

    The source revision uses the strict `document:<64 lowercase hex>` form so
    the existing ingestion and retrieval contracts accept it unchanged.
    """
    try:
        limits = {}
        if max_video_duration_seconds is not None:
            limits["max_video_duration_seconds"] = max_video_duration_seconds
        if max_total_chars is not None:
            limits["max_total_chars"] = max_total_chars
        validate_transcript(result, **limits)
    except TranscriptLimitError:
        raise
    except Exception as exc:  # TranscriptAcquisitionError carries UI-ready RU text
        raise TranscriptLimitError(getattr(exc, "code", "transcript_too_short"), str(exc)) from exc

    safe_title = " ".join((result.title or f"Видео {result.video_id}").split())
    transcript_text = result.to_plain_text()
    plain_text = "\n".join(
        [
            f"# {safe_title}",
            "",
            f"Источник: {result.canonical_url}",
            f"Язык субтитров: {result.language}",
            f"Автоматические субтитры: {'да' if result.is_auto_generated else 'нет'}",
            "",
            "## Субтитры",
            "",
            transcript_text,
            "",
        ]
    )
    content_sha256 = hashlib.sha256(plain_text.encode("utf-8")).hexdigest()
    source_revision = f"document:{content_sha256}"
    provenance = {
        "source_type": result.source_type,
        "provider": result.provider,
        "video_id": result.video_id,
        "source_url": result.source_url,
        "canonical_url": result.canonical_url,
        "title": result.title,
        "channel": result.channel,
        "language": result.language,
        "is_auto_generated": result.is_auto_generated,
        "duration_seconds": result.duration_seconds,
        "segment_count": len(result.segments),
        "retrieved_at": result.retrieved_at.isoformat(),
        "content_sha256": content_sha256,
        "source_revision": source_revision,
    }
    filename = f"youtube-{result.video_id}-{result.language}.md"
    return NormalizedTranscriptSource(
        title=safe_title,
        filename=filename,
        content_type="text/markdown",
        plain_text=plain_text,
        source_revision=source_revision,
        content_sha256=content_sha256,
        provenance=provenance,
    )
