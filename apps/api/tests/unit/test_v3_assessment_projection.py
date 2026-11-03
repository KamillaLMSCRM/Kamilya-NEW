"""The shared projection must retain the legacy adapter's exact assessment payload."""
from app.modules.ai.assessment_schema import MCQOption, MCQQuestion
from app.modules.ai.v3.adapter import v3_course_to_generation_artifacts
from app.modules.ai.v3.assessment_projection import project_lesson_questions
from app.modules.ai.v3.models import V3Course, V3Lesson, V3Option, V3Question, V3QuestionVariant, V3ScenarioCase


def _legacy_projection(lesson):
    result = []
    if lesson.cases:
        for ci, case in enumerate(lesson.cases, 1):
            for vi, variant in enumerate(case.variants, 1):
                q = variant.assemble_question(seed=100 + ci * 10 + vi)
                result.append(MCQQuestion(question=q.full_rendered_stem,
                    options=[MCQOption(text=o.text, is_correct=o.is_correct) for o in q.options],
                    explanation=q.explanation, source_quote=q.source_quote, pool_group=case.case_id))
    elif lesson.questions:
        for q in lesson.questions:
            result.append(MCQQuestion(question=q.full_rendered_stem,
                options=[MCQOption(text=o.text, is_correct=o.is_correct) for o in q.options],
                explanation=q.explanation, source_quote=q.source_quote))
    return result


def _variant(identifier):
    return V3QuestionVariant(identifier, "Context", "Situation", "Which term?", V3Option("24 months", True),
        tuple(V3Option(x, False) for x in ("6 months", "12 months", "18 months", "30 months")),
        "Source says 24 months", "24 months")


def test_case_and_variant_order_seeds_and_pool_payload():
    cases = (V3ScenarioCase("a", "r", "objective", (_variant("a1"), _variant("a2"))),
             V3ScenarioCase("b", "r", "objective", (_variant("b1"),)))
    ignored = V3Question("flat", "", "ignored", (), "", "r", "")
    lesson = V3Lesson("l", "title", "module", "body", ("r",), cases=cases, questions=(ignored,))
    actual = project_lesson_questions(lesson)
    assert actual == _legacy_projection(lesson)
    course = V3Course("course", "title", "a" * 64, (lesson,))
    assert v3_course_to_generation_artifacts(course).assessment.assessments[0].mcq == _legacy_projection(lesson)
    assert [q.pool_group for q in actual] == ["a", "a", "b"]
    assert [[o.text for o in q.options] for q in actual] == [
        [o.text for o in v.assemble_question(seed=seed).options]
        for v, seed in zip((cases[0].variants[0], cases[0].variants[1], cases[1].variants[0]),
                           (111, 112, 121), strict=True)]


def test_flat_fallback_empty_cases_and_empty_questions():
    q = V3Question("q", "Scenario", "Warranty?", (V3Option("24", True), V3Option("18", False)),
                   "24 months", "r", "Warranty: 24")
    lesson = V3Lesson("l", "title", "module", "body", ("r",), questions=(q,))
    assert project_lesson_questions(lesson) == _legacy_projection(lesson)
    assert project_lesson_questions(V3Lesson("l", "", "", "", ())) == []
    # Presence of a case, even without variants, suppresses flat fallback.
    with_empty_case = V3Lesson("l", "", "", "", (), cases=(V3ScenarioCase("a", "r", "", ()),), questions=(q,))
    assert project_lesson_questions(with_empty_case) == []
