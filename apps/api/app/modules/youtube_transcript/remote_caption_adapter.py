"""Authenticated remote caption relay with a bounded local fallback."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast

import httpx

from app.modules.youtube_transcript.provider import (
    ERROR_CATALOG,
    TranscriptAcquisitionError,
    TranscriptProvider,
    TranscriptProviderError,
    TranscriptResult,
    TranscriptSegment,
    TranscriptUnavailableError,
)
from app.modules.youtube_transcript.public_caption_adapter import PublicCaptionProvider
from app.modules.youtube_transcript.url_resolver import YouTubeVideoRef

logger = logging.getLogger(__name__)

ADAPTER_NAME = "kamilya_caption_relay"
_TERMINAL_CODES = {
    "transcript_unavailable",
    "language_unavailable",
    "video_unavailable",
    "video_too_long",
    "transcript_too_short",
    "transcript_too_large",
}


class RemoteCaptionConfigurationError(TranscriptAcquisitionError):
    """Authentication/configuration failure that must not be hidden by fallback."""


class RemoteCaptionProvider:
    def __init__(self, *, base_url: str, token: str, timeout_seconds: float = 20.0) -> None:
        if not base_url.startswith("https://") or not token:
            raise ValueError("remote caption provider requires an HTTPS URL and token")
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout_seconds = timeout_seconds

    async def get_transcript(
        self,
        video_ref: YouTubeVideoRef,
        preferred_languages: list[str],
    ) -> TranscriptResult:
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    f"{self._base_url}/v1/transcripts",
                    headers={"Authorization": f"Bearer {self._token}"},
                    json={
                        "video_id": video_ref.video_id,
                        "languages": preferred_languages or ["ru"],
                    },
                )
        except httpx.TimeoutException as exc:
            raise TranscriptProviderError("provider_timeout") from exc
        except httpx.HTTPError as exc:
            raise TranscriptProviderError("provider_unavailable") from exc

        if response.status_code in {401, 403}:
            raise RemoteCaptionConfigurationError("provider_unavailable")
        if response.is_error:
            code = _response_error_code(response)
            if code in _TERMINAL_CODES:
                raise TranscriptUnavailableError(code)
            raise TranscriptProviderError(code if code in ERROR_CATALOG else "provider_unavailable")

        try:
            payload = cast(dict[str, Any], response.json())
            segments = [
                TranscriptSegment(
                    start_seconds=float(item["start"]),
                    end_seconds=float(item["end"]),
                    text=str(item["text"]),
                )
                for item in payload["segments"]
                if str(item.get("text", "")).strip()
            ]
            if not segments:
                raise KeyError("segments")
            return TranscriptResult(
                source_type="youtube",
                video_id=video_ref.video_id,
                source_url=video_ref.source_url,
                canonical_url=video_ref.canonical_url,
                title=str(payload.get("title") or f"Видео {video_ref.video_id}"),
                channel=str(payload["channel"]) if payload.get("channel") else None,
                language=str(payload["language"]),
                is_auto_generated=bool(payload["is_auto_generated"]),
                segments=segments,
                retrieved_at=datetime.now(UTC),
                provider=ADAPTER_NAME,
                duration_seconds=float(payload["duration_seconds"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TranscriptProviderError("provider_unavailable") from exc


def _response_error_code(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail", {})
        return str(detail.get("code", "provider_unavailable"))
    except (AttributeError, TypeError, ValueError):
        return "provider_unavailable"


class FallbackTranscriptProvider:
    """Use the relay first and the existing public adapter on transient failure."""

    def __init__(self, primary: TranscriptProvider, fallback: TranscriptProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    async def get_transcript(
        self,
        video_ref: YouTubeVideoRef,
        preferred_languages: list[str],
    ) -> TranscriptResult:
        try:
            return await self._primary.get_transcript(video_ref, preferred_languages)
        except RemoteCaptionConfigurationError:
            raise
        except TranscriptProviderError as exc:
            logger.warning("Remote caption relay failed with code=%s; using public fallback", exc.code)
            return await self._fallback.get_transcript(video_ref, preferred_languages)


def build_runtime_caption_provider(settings: Any) -> TranscriptProvider:
    local = PublicCaptionProvider(timeout_seconds=settings.YOUTUBE_PROVIDER_TIMEOUT_SECONDS)
    service_url = str(getattr(settings, "YOUTUBE_CAPTION_SERVICE_URL", "")).strip()
    service_token = str(getattr(settings, "YOUTUBE_CAPTION_SERVICE_TOKEN", "")).strip()
    if not service_url and not service_token:
        return local
    if not service_url or not service_token:
        raise RuntimeError("YOUTUBE_CAPTION_SERVICE_URL and YOUTUBE_CAPTION_SERVICE_TOKEN must be configured together")
    remote = RemoteCaptionProvider(
        base_url=service_url,
        token=service_token,
        timeout_seconds=settings.YOUTUBE_PROVIDER_TIMEOUT_SECONDS,
    )
    return FallbackTranscriptProvider(remote, local)
