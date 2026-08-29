"""Public-caption adapter backed by youtube-transcript-api (YTG-06).

The adapter is deliberately thin: it maps the library's exception taxonomy to
the module's retryable/terminal catalog and normalizes `FetchedTranscript`
into `TranscriptResult`. It never downloads media, never bypasses access
controls, and stores no credentials. Runtime dependency is optional — the
module imports lazily so the rest of the system works without the package.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.modules.youtube_transcript.provider import (
    TranscriptAcquisitionError,
    TranscriptProviderError,
    TranscriptResult,
    TranscriptSegment,
    TranscriptUnavailableError,
)
from app.modules.youtube_transcript.url_resolver import YouTubeVideoRef

logger = logging.getLogger(__name__)

ADAPTER_NAME = "youtube_public_transcript"


def _map_exception(exc: Exception) -> TranscriptAcquisitionError:
    """Map library exception classes to the stable error catalog."""
    try:
        from youtube_transcript_api import (
            IpBlocked,
            NoTranscriptFound,
            RequestBlocked,
            TranscriptsDisabled,
            VideoUnavailable,
            YouTubeRequestFailed,
        )
    except ImportError:  # pragma: no cover - guarded by lazy import at call site
        return TranscriptProviderError("provider_unavailable")

    if isinstance(exc, RequestBlocked | IpBlocked):
        return TranscriptProviderError("provider_blocked")
    if isinstance(exc, TranscriptsDisabled | NoTranscriptFound):
        return TranscriptUnavailableError("transcript_unavailable")
    if isinstance(exc, VideoUnavailable):
        return TranscriptUnavailableError("video_unavailable")
    if isinstance(exc, YouTubeRequestFailed):
        return TranscriptProviderError("provider_unavailable")
    return TranscriptProviderError("provider_unavailable")


class PublicCaptionProvider:
    """Concrete TranscriptProvider using the public caption web endpoint.

    Request timeout is enforced through the underlying `requests.Session`
    (injected), keeping the adapter itself free of network configuration.
    """

    def __init__(self, http_client=None, timeout_seconds: float = 20.0):
        self._http_client = http_client
        self._timeout_seconds = timeout_seconds

    def _build_api(self):
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError as exc:
            raise TranscriptProviderError("provider_unavailable") from exc
        kwargs = {}
        if self._http_client is not None:
            kwargs["http_client"] = self._http_client
        return YouTubeTranscriptApi(**kwargs)

    async def get_transcript(
        self,
        video_ref: YouTubeVideoRef,
        preferred_languages: list[str],
    ) -> TranscriptResult:
        api = self._build_api()
        languages = [code for code in (preferred_languages or ["ru"]) if code]
        try:
            fetched = await asyncio.wait_for(
                asyncio.to_thread(
                    api.fetch,
                    video_ref.video_id,
                    languages=languages or ["ru"],
                    preserve_formatting=False,
                ),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as exc:
            raise TranscriptProviderError("provider_timeout") from exc
        except TranscriptAcquisitionError:
            raise
        except Exception as exc:
            raise _map_exception(exc) from exc

        try:
            raw = fetched.to_raw_data()
            language_code: str = fetched.language_code
            is_generated: bool = fetched.is_generated
        except AttributeError as exc:
            raise TranscriptProviderError("provider_unavailable") from exc

        segments = []
        for item in raw:
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            start = float(item.get("start", 0.0))
            duration = float(item.get("duration", 0.0))
            segments.append(
                TranscriptSegment(
                    start_seconds=start,
                    end_seconds=start + duration,
                    text=text,
                )
            )
        if not segments:
            raise TranscriptUnavailableError("transcript_unavailable")

        duration_total = segments[-1].end_seconds
        return TranscriptResult(
            source_type="youtube",
            video_id=video_ref.video_id,
            source_url=video_ref.source_url,
            canonical_url=video_ref.canonical_url,
            title=f"Видео {video_ref.video_id}",
            channel=None,
            language=language_code,
            is_auto_generated=is_generated,
            segments=segments,
            retrieved_at=datetime.now(UTC),
            provider=ADAPTER_NAME,
            duration_seconds=duration_total,
        )
