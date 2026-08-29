from app.modules.youtube_transcript.operations import _preview_format, _preview_summary


def test_preview_summary_is_short_and_keeps_at_most_two_sentences():
    assert _preview_summary("Первое предложение. Второе предложение. Третье предложение.") == "Первое предложение. Второе предложение."


def test_preview_format_uses_video_volume_without_methodologist_guesswork():
    assert _preview_format(duration_seconds=5 * 60, total_chars=4000) == "brief"
    assert _preview_format(duration_seconds=25 * 60, total_chars=15000) == "standard"
    assert _preview_format(duration_seconds=60 * 60, total_chars=35000) == "detailed"
