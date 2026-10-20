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


def test_excluded_primary_source_fragment_is_counted_not_hidden_by_admitted_coverage():
    from app.modules.ai.evidence_engine.engine import EvidenceCourseEngine
    from app.modules.ai.evidence_engine.models import SourceDocument, SourceFact, SourceSection
    facts = (
        SourceFact("good", "Безопасность", "обязанность", "Сотрудник обязан проверить выход.", "section=s;part=1"),
        SourceFact("bad", "Безопасность", "обязанность", "Сотрудник обязан отключить питание в", "section=s;part=2",
                   confidence=0.0, uncertainty="incomplete_source_clause"),
        SourceFact("cover", "Безопасность", "положение", "УТВЕРЖДАЮ", "section=s;part=3",
                   confidence=0.0, uncertainty="source_authoring_metadata"),
    )
    result = EvidenceCourseEngine().generate_from_document(SourceDocument(
        "d", "Безопасность", "narrative", (SourceSection("s", "Безопасность", "primary", facts),)))
    assert result.evaluation.uncertain_fact_count == 1
    assert "uncertain_source_facts_require_review" in result.evaluation.warnings


def test_saved_course_with_good_questions_but_incomplete_source_remains_review_required():
    from types import SimpleNamespace

    from app.modules.ai import pipeline
    from app.modules.ai.assessment_schema import CourseAssessment, LessonAssessment, MCQOption, MCQQuestion
    from app.modules.ai.writer_schema import ModuleContent
    state = SimpleNamespace(
        content=CourseContent("Draft", modules=[ModuleContent("M", [LessonContent("L", content="Rule")])],
                              source_warnings=["Часть исходных фрагментов не разобрана."]),
        assessment=CourseAssessment([LessonAssessment("L", mcq=[MCQQuestion("What?", [MCQOption("A", True)])])]),
        source_analysis={"generation_engine":"evidence_v2", "evidence_v2":{
            "uncertain_source_fact_count":1, "assessment_review":{"coverage":{"requires_review":False}}}},
        errors=[], status="completed", stage="completed", progress=100, message="")
    pipeline._apply_evidence_v2_completion_outcome(state)
    assert state.status == "interrupted" and state.progress == 100
    assert state.errors == ["assessment_coverage_incomplete"]
    assert "исходных" in state.message
    assert "Тесты не покрывают" not in state.message
