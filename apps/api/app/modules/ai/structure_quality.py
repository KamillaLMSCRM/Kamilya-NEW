"""Deterministic admission policy for learner-visible course structures."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.modules.ai.architect_schema import CourseStructure

_ASSESSMENT_ONLY_LESSON_RE = re.compile(
    r"(?:"
    r"контрол\w*\s+ознакомлен\w*|"
    r"итогов\w*\s+(?:тест\w*|викторин\w*)|"
    r"(?:пройти|прохожден\w*)\s+(?:итогов\w*\s+)?тест\w*|"
    r"проверк\w*\s+усвоен\w*|"
    r"(?:итогов\w*\s+)?проверк\w*\s+знани\w*|"
    r"тесттен\s+өту|қорытынды\s+тест|білімді\s+тексер\w*|"
    r"(?:take|pass)\s+(?:the\s+)?(?:final\s+)?quiz|"
    r"(?:final\s+)?knowledge\s+check|"
    r"(?:final\s+)?(?:quiz|assessment)\s+(?:lesson|check)"
    r")",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class StructureQualityIssue:
    code: str
    lesson_title: str


def course_structure_quality_issues(
    structure: CourseStructure,
) -> tuple[StructureQualityIssue, ...]:
    """Return source-independent defects that must never consume a lesson slot."""
    issues: list[StructureQualityIssue] = []
    for module in structure.modules:
        for lesson in module.lessons:
            objective_text = " ".join(objective.text for objective in lesson.objectives)
            learner_scope = " ".join(
                part for part in (lesson.title, lesson.description, objective_text) if part
            )
            if _ASSESSMENT_ONLY_LESSON_RE.search(learner_scope):
                issues.append(
                    StructureQualityIssue(
                        code="assessment_only_lesson",
                        lesson_title=lesson.title,
                    )
                )
    return tuple(issues)


__all__ = ["StructureQualityIssue", "course_structure_quality_issues"]
