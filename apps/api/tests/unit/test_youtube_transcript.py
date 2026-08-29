"""Deterministic unit tests for the YouTube transcript seam. No network."""

import hashlib
from datetime import UTC, datetime

import pytest

from app.modules.youtube_transcript.normalizer import normalize_transcript
from app.modules.youtube_transcript.provider import (
    MAX_TOTAL_CHARS,
    TranscriptAcquisitionError,
    TranscriptResult,
    TranscriptSegment,
    validate_transcript,
)
from app.modules.youtube_transcript.url_resolver import (
    YouTubeURLValidationError,
    extract_video_id,
)


def _result(**overrides) -> TranscriptResult:
    filler_a = "Первый фрагмент текста с достаточным объёмом для валидации. " * 3
    filler_b = "Второй фрагмент текста с достаточным объёмом для валидации. " * 3
    defaults = dict(
        source_type="youtube",
        video_id="dQw4w9WgXcQ",
        source_url="https://youtu.be/dQw4w9WgXcQ",
        canonical_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        title="Тестовое видео",
        channel="Kamilya",
        language="ru",
        is_auto_generated=True,
        segments=[
            TranscriptSegment(0.0, 4.0, filler_a),
            TranscriptSegment(4.0, 9.5, filler_b),
        ],
        retrieved_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
        provider="fake",
        duration_seconds=9.5,
    )
    defaults.update(overrides)
    return TranscriptResult(**defaults)


class TestURLResolver:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
        ],
    )
    def test_canonical_forms_extract_same_id(self, url):
        ref = extract_video_id(url)
        assert ref.video_id == "dQw4w9WgXcQ"
        assert ref.canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    @pytest.mark.parametrize(
        "url,code",
        [
            ("http://www.youtube.com/watch?v=dQw4w9WgXcQ", "invalid_url"),
            ("ftp://youtu.be/dQw4w9WgXcQ", "invalid_url"),
            ("https://evil.example.com/watch?v=dQw4w9WgXcQ", "invalid_url"),
            ("https://localhost/watch?v=dQw4w9WgXcQ", "invalid_url"),
            ("https://127.0.0.1/watch?v=dQw4w9WgXcQ", "invalid_url"),
            ("https://169.254.169.254/latest/meta-data", "invalid_url"),
            ("https://www.youtube.com/watch?v=short", "invalid_url"),
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123", "playlist_not_supported"),
            ("", "invalid_url"),
        ],
    )
    def test_rejections(self, url, code):
        with pytest.raises(YouTubeURLValidationError) as exc:
            extract_video_id(url)
        assert exc.value.code == code

    def test_error_is_ui_ready_russian(self):
        with pytest.raises(YouTubeURLValidationError) as exc:
            extract_video_id("https://evil.example.com/")
        assert "youtube.com" in exc.value.message_ru


class TestLimits:
    def test_video_too_long_is_terminal(self):
        result = _result(duration_seconds=7201)
        with pytest.raises(TranscriptAcquisitionError) as exc:
            validate_transcript(result)
        assert exc.value.code == "video_too_long"
        assert not exc.value.retryable

    def test_too_short_is_terminal(self):
        result = _result(segments=[TranscriptSegment(0, 1, "коротко")])
        with pytest.raises(TranscriptAcquisitionError) as exc:
            validate_transcript(result)
        assert exc.value.code == "transcript_too_short"

    def test_too_large_is_terminal(self):
        filler = "слово " * 100
        segments = [TranscriptSegment(float(i), float(i + 1), filler) for i in range(1000)]
        assert sum(len(s.text) for s in segments) > MAX_TOTAL_CHARS
        with pytest.raises(TranscriptAcquisitionError) as exc:
            validate_transcript(_result(segments=segments))
        assert exc.value.code == "transcript_too_large"


class TestNormalization:
    def test_provenance_and_revision_are_deterministic(self):
        first = normalize_transcript(_result())
        second = normalize_transcript(_result())
        assert first.source_revision == second.source_revision
        assert first.content_sha256 == second.content_sha256
        assert first.source_revision == f"document:{first.content_sha256}"
        assert first.provenance["video_id"] == "dQw4w9WgXcQ"
        assert first.provenance["language"] == "ru"
        assert first.provenance["is_auto_generated"] is True
        assert first.provenance["retrieved_at"] == "2026-08-29T12:00:00+00:00"
        assert first.filename == "youtube-dQw4w9WgXcQ-ru.md"

    def test_content_hash_is_stable_and_sensitive_to_text(self):
        base = normalize_transcript(_result())
        filler = "Изменённый текст с достаточным объёмом для валидации. " * 3
        changed = normalize_transcript(
            _result(segments=[TranscriptSegment(0.0, 4.0, filler), TranscriptSegment(4.0, 9.5, filler)])
        )
        assert base.content_sha256 != changed.content_sha256
        assert len(base.content_sha256) == 64

    def test_plain_text_keeps_timestamp_markers(self):
        normalized = normalize_transcript(_result())
        assert "[00:00] " in normalized.plain_text
        assert "[00:04] " in normalized.plain_text
        assert "фрагмент текста" in normalized.plain_text
        assert normalized.content_sha256 == hashlib.sha256(normalized.plain_text.encode("utf-8")).hexdigest()

    def test_language_field_from_provider_is_kept(self):
        normalized = normalize_transcript(_result(language="kk"))
        assert normalized.provenance["language"] == "kk"
