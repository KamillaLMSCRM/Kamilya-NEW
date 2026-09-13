"""Generated lessons should always expose a realistic reading duration."""

from app.modules.ai.pipeline import _estimate_lesson_duration_seconds


def test_estimate_lesson_duration_uses_reading_rate_and_two_minute_floor():
    assert _estimate_lesson_duration_seconds("") == 120
    assert _estimate_lesson_duration_seconds("слово " * 300) == 120
    assert _estimate_lesson_duration_seconds("слово " * 301) == 180
    assert _estimate_lesson_duration_seconds("слово " * 750) == 300


def test_estimate_lesson_duration_includes_one_minute_per_assessment_question():
    assert _estimate_lesson_duration_seconds("слово " * 300, 3) == 300
    assert _estimate_lesson_duration_seconds("слово " * 301, 5) == 480
