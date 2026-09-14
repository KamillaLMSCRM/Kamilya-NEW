from app.modules.ai.architect_schema import CourseStructure
from app.modules.ai.assessment_schema import CourseAssessment, LessonAssessment
from app.modules.ai.pipeline import GenerationState, _generation_completion_message
from app.modules.ai.writer_schema import CourseContent


def test_empty_assessment_policy_roundtrips_without_loss():
    value = LessonAssessment(
        lesson_title="Synthetic terminology",
        quality_policy_version="assessment-drop-only-v1",
        omission_reason="no_valid_questions",
    )
    assert LessonAssessment.from_dict(value.to_dict()) == value


def test_named_missing_quiz_notice_is_persistable_and_idempotent():
    from app.modules.ai.pipeline import _apply_assessment_omission_notices

    state = GenerationState(
        job_id="synthetic",
        structure=CourseStructure(title="Course", description="Description"),
        content=CourseContent(title="Course", description="Description"),
        assessment=CourseAssessment(assessments=[LessonAssessment(
            lesson_title="Synthetic terminology",
            quality_policy_version="assessment-drop-only-v1",
            omission_reason="no_valid_questions",
        )]),
    )
    _apply_assessment_omission_notices(state)
    _apply_assessment_omission_notices(state)
    assert len(state.content.source_warnings) == 1
    assert "Synthetic terminology" in state.structure.description
    assert "без теста" in _generation_completion_message(state.content)
