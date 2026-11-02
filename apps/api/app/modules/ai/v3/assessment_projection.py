"""Canonical learner-facing assessment projection for a V3 lesson."""

from app.modules.ai.assessment_schema import MCQOption, MCQQuestion
from app.modules.ai.v3.models import V3Lesson, V3Question


def _project_question(question: V3Question, *, pool_group: str | None = None) -> MCQQuestion:
    return MCQQuestion(
        question=question.full_rendered_stem,
        options=[MCQOption(text=option.text, is_correct=option.is_correct) for option in question.options],
        explanation=question.explanation,
        source_quote=question.source_quote,
        pool_group=pool_group,
    )


def project_lesson_questions(lesson: V3Lesson) -> list[MCQQuestion]:
    """Match adapter case order, variant seeds, and flat-question fallback."""
    if lesson.cases:
        return [
            _project_question(variant.assemble_question(seed=100 + case_index * 10 + variant_index),
                              pool_group=case.case_id)
            for case_index, case in enumerate(lesson.cases, 1)
            for variant_index, variant in enumerate(case.variants, 1)
        ]
    return [_project_question(question) for question in lesson.questions]
