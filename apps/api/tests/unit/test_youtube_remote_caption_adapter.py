"""Deterministic contracts for the authenticated caption relay adapter."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.modules.youtube_transcript.provider import TranscriptProviderError, TranscriptResult
from app.modules.youtube_transcript.remote_caption_adapter import (
    FallbackTranscriptProvider,
    RemoteCaptionConfigurationError,
    RemoteCaptionProvider,
    build_runtime_caption_provider,
)
from app.modules.youtube_transcript.url_resolver import extract_video_id


def _ref():
    return extract_video_id("https://youtu.be/dQw4w9WgXcQ")


def _response(status: int, payload: dict) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("POST", "https://caption.example/v1/transcripts"))


@pytest.mark.asyncio
async def test_remote_provider_normalizes_relay_payload(monkeypatch):
    payload = {
        "language": "ru",
        "is_auto_generated": True,
        "duration_seconds": 9.5,
        "segments": [
            {"start": 0.0, "end": 4.0, "text": "Первый фрагмент."},
            {"start": 4.0, "end": 9.5, "text": "Второй фрагмент."},
        ],
    }

    async def fake_post(*args, **kwargs):
        assert kwargs["headers"]["Authorization"] == "Bearer secret"
        assert kwargs["json"] == {"video_id": "dQw4w9WgXcQ", "languages": ["ru"]}
        return _response(200, payload)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    result = await RemoteCaptionProvider(base_url="https://caption.example", token="secret").get_transcript(_ref(), ["ru"])
    assert result.video_id == "dQw4w9WgXcQ"
    assert result.language == "ru"
    assert result.is_auto_generated is True
    assert len(result.segments) == 2


@pytest.mark.asyncio
async def test_auth_failure_never_falls_back(monkeypatch):
    async def fake_post(*args, **kwargs):
        return _response(401, {"detail": {"code": "unauthorized"}})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    fallback = SimpleNamespace(get_transcript=AsyncMock())
    provider = FallbackTranscriptProvider(
        RemoteCaptionProvider(base_url="https://caption.example", token="secret"),
        fallback,
    )
    with pytest.raises(RemoteCaptionConfigurationError):
        await provider.get_transcript(_ref(), ["ru"])
    fallback.get_transcript.assert_not_awaited()


@pytest.mark.asyncio
async def test_transient_relay_failure_uses_public_fallback():
    expected = SimpleNamespace(spec=TranscriptResult)
    primary = SimpleNamespace(get_transcript=AsyncMock(side_effect=TranscriptProviderError("provider_timeout")))
    fallback = SimpleNamespace(get_transcript=AsyncMock(return_value=expected))
    provider = FallbackTranscriptProvider(primary, fallback)
    assert await provider.get_transcript(_ref(), ["ru"]) is expected
    fallback.get_transcript.assert_awaited_once()


def test_runtime_factory_requires_url_and_token_together():
    settings = SimpleNamespace(
        YOUTUBE_PROVIDER_TIMEOUT_SECONDS=20.0,
        YOUTUBE_CAPTION_SERVICE_URL="https://caption.example",
        YOUTUBE_CAPTION_SERVICE_TOKEN="",
    )
    with pytest.raises(RuntimeError, match="configured together"):
        build_runtime_caption_provider(settings)
