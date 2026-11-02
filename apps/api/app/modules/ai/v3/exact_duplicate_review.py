"""Identify exact cross-lesson duplicates without inferring semantic equivalence."""
from __future__ import annotations

from app.modules.ai.v3.assessment_projection import project_lesson_questions
from app.modules.ai.v3.models import V3Lesson


def has_cross_lesson_duplicate(lessons: list[V3Lesson]) -> bool:
    """Detect a shared whitespace-normalized full stem without exposing content."""
    occurrences: dict[str, int] = {}
    for lesson_index, lesson in enumerate(lessons, 1):
        for question in project_lesson_questions(lesson):
            stem = " ".join(question.question.split())
            if stem and stem in occurrences and occurrences[stem] != lesson_index:
                return True
            if stem:
                occurrences[stem] = lesson_index
    return False
