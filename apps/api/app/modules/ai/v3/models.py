"""V3 Generation Engine data contracts: Curriculum, Lessons, Scenarios, and Questions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class DistractorCategory(str, Enum):
    PROCEDURAL_CONFUSION = "procedural_confusion"    # Перепутаны этапы, регламенты или необходимые действия
    ROLE_CONFUSION = "role_confusion"                # Перепутаны участники (оценщик, АУП РД, аудит, директор)
    TIMING_VIOLATION = "timing_violation"            # Нарушен срок (сразу, 1 день, 2 дня, плановая проверка)
    UNAUTHORIZED_ACTION = "unauthorized_action"      # Самовольное действие, сокрытие, устное решение


@dataclass(frozen=True)
class RuleEntity:
    rule_id: str
    section: str
    title: str
    statement: str
    conditions: tuple[str, ...] = ()
    exceptions: tuple[str, ...] = ()
    actors: tuple[str, ...] = ()
    timing: str = ""
    consequences: str = ""
    source_quote: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentRuleModel:
    document_title: str
    document_sha256: str
    rules: tuple[RuleEntity, ...]
    overview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class V3Option:
    text: str
    is_correct: bool
    distractor_category: DistractorCategory | None = None
    distractor_rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.distractor_category:
            data["distractor_category"] = self.distractor_category.value
        return data


@dataclass(frozen=True)
class V3Question:
    question_id: str
    scenario_premise: str                           # Жизненная рабочая фабула (кто, где, при каких условиях)
    prompt: str                                     # Конкретный вопрос сотруднику («Какое решение принять?»)
    options: tuple[V3Option, ...]                   # Ровно 4 варианта (1 верный + 3 реалистичные ошибки)
    explanation: str                                # Обучающее обоснование со ссылкой на норму
    rule_id: str                                    # Связь с конкретным правилом источника
    source_quote: str                               # Точная цитата основания из регламента

    @property
    def full_rendered_stem(self) -> str:
        return f"Ситуация: {self.scenario_premise}\n\nВопрос: {self.prompt}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "scenario_premise": self.scenario_premise,
            "prompt": self.prompt,
            "full_rendered_stem": self.full_rendered_stem,
            "options": [opt.to_dict() for opt in self.options],
            "explanation": self.explanation,
            "rule_id": self.rule_id,
            "source_quote": self.source_quote,
        }


@dataclass(frozen=True)
class V3Lesson:
    lesson_id: str
    title: str
    module_title: str
    content: str                                    # Практический, структурированный обучающий текст
    covered_rule_ids: tuple[str, ...]
    questions: tuple[V3Question, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "lesson_id": self.lesson_id,
            "title": self.title,
            "module_title": self.module_title,
            "content": self.content,
            "covered_rule_ids": list(self.covered_rule_ids),
            "questions": [q.to_dict() for q in self.questions],
        }


@dataclass(frozen=True)
class V3Course:
    course_id: str
    title: str
    document_sha256: str
    lessons: tuple[V3Lesson, ...]
    quality_verdict: str = "verified"

    def to_dict(self) -> dict[str, Any]:
        return {
            "course_id": self.course_id,
            "title": self.title,
            "document_sha256": self.document_sha256,
            "lessons": [lesson.to_dict() for lesson in self.lessons],
            "quality_verdict": self.quality_verdict,
        }
