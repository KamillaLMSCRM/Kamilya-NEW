"""Deterministic tests for the PublicCaptionProvider adapter.

The youtube-transcript-api dependency is faked with stub classes so no live
YouTube call can happen. Tests prove exception mapping, normalization into
TranscriptResult, and behavior when the library is not imported.
"""

from datetime import UTC, datetime
import time
from types import SimpleNamespace

import pytest

from app.modules.youtube_transcript.provider import TranscriptProviderError, TranscriptUnavailableError
from app.modules.youtube_transcript.public_caption_adapter import (
    ADAPTER_NAME,
    PublicCaptionProvider,
    _map_exception,
)
from app.modules.youtube_transcript.url_resolver import extract_video_id


def _video_ref():
    return extract_video_id("https://youtu.be/dQw4w9WgXcQ")


def _fetched(video_id="dQw4w9WgXcQ", language_code="ru", is_generated=True):
    raw = [
        {"text": "Первый фрагмент текста с достаточным объёмом для валидации.", "start": 0.0, "duration": 4.0},
        {"text": "Второй фрагмент текста с достаточным объёмом для валидации.", "start": 4.0, "duration": 5.5},
    ]
    return SimpleNamespace(to_raw_data=lambda: raw, language_code=language_code, is_generated=is_generated)


def test_map_exception_taxonomy(monkeypatch):
    import sys
    import types as t

    stub = t.ModuleType("youtube_transcript_api")
    stub.RequestBlocked = type("RequestBlocked", (Exception,), {})
    stub.IpBlocked = type("IpBlocked", (stub.RequestBlocked,), {})
    stub.TranscriptsDisabled = type("TranscriptsDisabled", (Exception,), {})
    stub.NoTranscriptFound = type("NoTranscriptFound", (Exception,), {})
    stub.VideoUnavailable = type("VideoUnavailable", (Exception,), {})
    stub.YouTubeRequestFailed = type("YouTubeRequestFailed", (Exception,), {})
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", stub)

    assert _map_exception(stub.IpBlocked("x")).code == "provider_blocked"
    assert _map_exception(stub.IpBlocked("x")).retryable is True
    assert _map_exception(stub.TranscriptsDisabled("x")).code == "transcript_unavailable"
    assert _map_exception(stub.TranscriptsDisabled("x")).retryable is False
    assert _map_exception(stub.NoTranscriptFound("x")).code == "transcript_unavailable"
    assert _map_exception(stub.VideoUnavailable("x")).code == "video_unavailable"
    assert _map_exception(stub.YouTubeRequestFailed("x")).code == "provider_unavailable"
    assert _map_exception(stub.YouTubeRequestFailed("x")).retryable is True


@pytest.mark.asyncio
async def test_adapter_normalizes_fetched_transcript():
    provider = PublicCaptionProvider()

    class FakeAPI:
        def fetch(self, video_id, languages, preserve_formatting):
            assert video_id == "dQw4w9WgXcQ"
            assert languages == ["ru"]
            assert preserve_formatting is False
            return _fetched()

    provider._build_api = lambda: FakeAPI()
    result = await provider.get_transcript(_video_ref(), ["ru"])
    assert result.provider == ADAPTER_NAME
    assert result.video_id == "dQw4w9WgXcQ"
    assert result.language == "ru"
    assert result.is_auto_generated is True
    assert len(result.segments) == 2
    assert result.duration_seconds == 9.5
    assert result.segments[0].end_seconds == 4.0
    assert result.retrieved_at <= datetime.now(UTC)


@pytest.mark.asyncio
async def test_adapter_skips_empty_segments():
    provider = PublicCaptionProvider()
    fetched = _fetched()
    fetched.to_raw_data = lambda: [
        {"text": "", "start": 0.0, "duration": 1.0},
        {"text": "   ", "start": 1.0, "duration": 1.0},
        {"text": "Контент с достаточным объёмом текста для валидации.", "start": 2.0, "duration": 3.0},
    ]

    class FakeAPI:
        def fetch(self, video_id, languages, preserve_formatting):
            return fetched

    provider._build_api = lambda: FakeAPI()
    result = await provider.get_transcript(_video_ref(), ["ru"])
    assert len(result.segments) == 1


@pytest.mark.asyncio
async def test_adapter_empty_transcript_is_terminal():
    provider = PublicCaptionProvider()
    fetched = _fetched()
    fetched.to_raw_data = lambda: []

    class FakeAPI:
        def fetch(self, video_id, languages, preserve_formatting):
            return fetched

    provider._build_api = lambda: FakeAPI()
    with pytest.raises(TranscriptUnavailableError) as exc:
        await provider.get_transcript(_video_ref(), ["ru"])
    assert exc.value.code == "transcript_unavailable"


@pytest.mark.asyncio
async def test_adapter_maps_library_exception(monkeypatch):
    import sys
    import types as t

    stub = t.ModuleType("youtube_transcript_api")
    stub.RequestBlocked = type("RequestBlocked", (Exception,), {})
    stub.IpBlocked = type("IpBlocked", (stub.RequestBlocked,), {})
    stub.TranscriptsDisabled = type("TranscriptsDisabled", (Exception,), {})
    stub.NoTranscriptFound = type("NoTranscriptFound", (Exception,), {})
    stub.VideoUnavailable = type("VideoUnavailable", (Exception,), {})
    stub.YouTubeRequestFailed = type("YouTubeRequestFailed", (Exception,), {})
    stub.YouTubeTranscriptApi = type("YouTubeTranscriptApi", (), {})
    stub.YouTubeTranscriptApi.fetch = lambda self, *a, **k: (_ for _ in ()).throw(stub.IpBlocked("blocked"))
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", stub)

    provider = PublicCaptionProvider()
    with pytest.raises(TranscriptProviderError) as exc:
        await provider.get_transcript(_video_ref(), ["ru"])
    assert exc.value.code == "provider_blocked"
    assert exc.value.retryable is True


@pytest.mark.asyncio
async def test_adapter_timeout_is_retryable():
    provider = PublicCaptionProvider(timeout_seconds=0.01)

    class SlowAPI:
        def fetch(self, *args, **kwargs):
            time.sleep(0.05)
            return _fetched()

    provider._build_api = lambda: SlowAPI()
    with pytest.raises(TranscriptProviderError) as exc:
        await provider.get_transcript(_video_ref(), ["ru"])
    assert exc.value.code == "provider_timeout"
    assert exc.value.retryable is True
