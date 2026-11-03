"""Offline import smoke for the DEV generation candidate."""

def test_generation_default_modules_import():
    from app.modules.ai import pipeline, worker_lesson_cycle
    from app.modules.ai.evidence_engine import application

    assert callable(pipeline._run_evidence_v2_generation)
    assert callable(worker_lesson_cycle.create_dev_lesson_assessor)
    assert callable(application.generate_evidence_course)


def test_optional_support_evidence_validates_but_is_not_exported():
    import pytest

    from app.modules.ai.assessment_schema import CourseAssessment, LessonAssessment, MCQQuestion
    from app.modules.ai.pipeline import _require_supported_question_export_ready

    evidence = {"source_fact_id": "f", "source_id": "s", "source_revision": "r",
                "source_locator": "p1", "quote": "abc", "quote_start": 0, "quote_end": 3,
                "role": "condition"}
    question = MCQQuestion.from_dict({"question": "q", "supporting_source_evidence": [evidence]})
    assert question.supporting_source_evidence == [evidence]
    with pytest.raises(ValueError, match="support_source_export_unavailable"):
        _require_supported_question_export_ready(CourseAssessment(assessments=[
            LessonAssessment(lesson_title="L", mcq=[question])]))
    with pytest.raises(ValueError):
        MCQQuestion.from_dict({"question": "q", "supporting_source_evidence": [{**evidence, "quote_end": 2}]})
