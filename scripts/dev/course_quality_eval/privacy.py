from __future__ import annotations

import re

from .domain import CourseArtifact, PrivacyViolation

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("phone", re.compile(r"(?<!\d)(?:\+?7|8)[\s()\-]*\d{3}[\s()\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)")),
    ("iin_like_12_digits", re.compile(r"(?<!\d)\d{12}(?!\d)")),
)


def assert_deidentified(artifact: CourseArtifact) -> None:
    fields: list[str] = [artifact.identity.course_title]
    for lesson in artifact.lessons:
        fields.extend((lesson.title, lesson.content, lesson.source, *lesson.objectives))
    for question in artifact.questions:
        fields.extend((question.text, question.explanation, question.source, *question.options))
    text = "\n".join(fields)
    found = [name for name, pattern in _PATTERNS if pattern.search(text)]
    if found:
        raise PrivacyViolation(
            "Privacy preflight blocked external evaluation; detected: " + ", ".join(found)
        )
