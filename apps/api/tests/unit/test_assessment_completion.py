from unittest.mock import AsyncMock

import pytest

from app.modules.ai import assessment_completion as completion
from app.modules.ai.assessment_audit import AssessmentAuditError, AssessmentAuditResult
from app.modules.ai.assessment_schema import CourseAssessment, LessonAssessment, MCQOption, MCQQuestion
from app.modules.ai.writer_schema import CourseContent, LessonContent, ModuleContent


def fixture_data():
    lesson = LessonContent(title="Equipment", objectives=["Identify power", "Identify storage"],
                           content="Original lesson", source_chunks=["Alpha uses solar power and removable storage."])
    question = MCQQuestion("How is Alpha powered?", [MCQOption("Solar", True), MCQOption("Diesel", False)], source_quote=lesson.source_chunks[0])
    content = CourseContent("Synthetic", modules=[ModuleContent("Module", [lesson])])
    assessment = CourseAssessment([LessonAssessment(lesson.title, mcq=[question])])
    return content, assessment, question


@pytest.mark.asyncio
async def test_one_focused_supplement_preserves_originals_and_reaudits_union(monkeypatch):
    content, assessment, original = fixture_data()
    extra = MCQQuestion("Which storage?", [MCQOption("Removable", True)], source_quote="removable storage")
    initial = AssessmentAuditResult(assessment, [(0, 1)], [])
    final = AssessmentAuditResult(assessment, [], [])
    audit = AsyncMock(side_effect=[initial, final])
    generate = AsyncMock(return_value=LessonAssessment("Temporary scope", mcq=[extra]))
    monkeypatch.setattr(completion, "audit_course_assessment", audit)
    monkeypatch.setattr(completion, "generate_lesson_assessment", generate)
    result = await completion.finalize_course_assessment(object(), content, assessment)
    assert result is final
    assert result.uncovered_objectives == [(0, 1)]  # Earlier concern cannot disappear silently.
    assert generate.await_count == 1 and audit.await_count == 2
    focused = generate.call_args.args[1]
    assert focused.objectives == ["Identify storage"]
    assert focused.source_chunks is content.modules[0].lessons[0].source_chunks
    assert focused.title == "Identify storage"
    assert content.modules[0].lessons[0].title == "Equipment"
    union = audit.call_args.args[2]
    assert union.assessments[0].lesson_title == "Equipment"
    assert union.assessments[0].mcq == [original, extra]
    assert union.assessments[0].mcq[0] is original
    assert assessment.assessments[0].mcq == [original]
    assert generate.call_args.kwargs["excluded_fact_keys"]


@pytest.mark.asyncio
@pytest.mark.parametrize("has_gap", [True, False])
async def test_empty_supplement_or_no_gap_never_loops(monkeypatch, has_gap):
    content, assessment, _ = fixture_data()
    initial = AssessmentAuditResult(assessment, [(0, 1)] if has_gap else [], [])
    audit = AsyncMock(return_value=initial)
    generate = AsyncMock(return_value=LessonAssessment("Empty"))
    monkeypatch.setattr(completion, "audit_course_assessment", audit)
    monkeypatch.setattr(completion, "generate_lesson_assessment", generate)
    assert await completion.finalize_course_assessment(object(), content, assessment) is initial
    assert audit.await_count == 1
    assert generate.await_count == int(has_gap)


@pytest.mark.asyncio
async def test_invalid_final_audit_never_returns_initial_as_success(monkeypatch):
    content, assessment, question = fixture_data()
    monkeypatch.setattr(completion, "audit_course_assessment", AsyncMock(side_effect=[
        AssessmentAuditResult(assessment, [(0, 1)], []), ValueError("invalid verdict")]))
    monkeypatch.setattr(completion, "generate_lesson_assessment", AsyncMock(return_value=LessonAssessment("Extra", mcq=[question])))
    with pytest.raises(ValueError, match="invalid verdict"):
        await completion.finalize_course_assessment(object(), content, assessment)


@pytest.mark.asyncio
@pytest.mark.parametrize("recovers", [True, False])
async def test_contract_retry_is_bounded_and_never_regenerates_content(monkeypatch, recovers):
    content, assessment, _ = fixture_data()
    accepted = AssessmentAuditResult(assessment, [], [])
    audit = AsyncMock(side_effect=[AssessmentAuditError("bad verdict"), accepted if recovers else AssessmentAuditError("still bad")])
    generate = AsyncMock()
    monkeypatch.setattr(completion, "audit_course_assessment", audit)
    monkeypatch.setattr(completion, "generate_lesson_assessment", generate)
    if recovers:
        assert await completion.finalize_course_assessment(object(), content, assessment) is accepted
    else:
        with pytest.raises(AssessmentAuditError):
            await completion.finalize_course_assessment(object(), content, assessment)
    assert audit.await_count == 2
    generate.assert_not_awaited()
