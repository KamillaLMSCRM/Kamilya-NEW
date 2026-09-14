from app.modules.ai.pipeline import _generation_completion_message
from app.modules.ai.writer_schema import CourseContent, LessonContent


def test_uncertain_source_survives_serialization_and_is_not_silent_success():
    content = CourseContent(title="Draft", source_warnings=["Check the scanned rate in the original."])
    restored = CourseContent.from_json(content.to_json())
    assert _generation_completion_message(restored) == "Check the scanned rate in the original."
    lesson = LessonContent(title="Terms", source_chunks=["Rate: [UNREADABLE_PERCENTAGE_VALUE]"])
    assert LessonContent.from_dict(lesson.to_dict()).requires_source_review()
    assert not LessonContent(title="Terms", source_chunks=["Rate: 5%."]).requires_source_review()


def test_source_warning_and_missing_topic_are_both_visible():
    content = CourseContent(title="Draft", omitted_lesson_titles=["Contract"], source_warnings=["Check scan."])
    assert "Contract" in _generation_completion_message(content)
    assert "Check scan." in _generation_completion_message(content)
