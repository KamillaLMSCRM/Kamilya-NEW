"""V3 Generation Engine data contracts: Curriculum, Lessons, Scenarios, and Questions."""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class DistractorCategory(str, Enum):
    PROCEDURAL_CONFUSION = "procedural_confusion"              # Перепутаны этапы, регламенты или необходимые действия
    ROLE_CONFUSION = "role_confusion"                          # Перепутаны участники (оценщик, АУП РД, аудит, директор)
    TIMING_VIOLATION = "timing_violation"                      # Нарушен срок (сразу, 1 день, 2 дня, плановая проверка)
    UNAUTHORIZED_ACTION = "unauthorized_action"                # Самовольное действие, сокрытие, обход системы
    CALCULATION_OR_THRESHOLD_ERROR = "threshold_error"         # Ошибка границы лимита, неверное сложение билетов


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
class V3QuestionVariant:
    """A concrete context variant of a scenario with varied branch context and distractor formulations."""
    variant_id: str
    branch_context: str                             # e.g. "Филиал в Павлодаре (Группа 1)" or "Филиал в Шымкенте (Группа 2)"
    scenario_premise: str
    prompt: str
    correct_option: V3Option
    distractor_pool: tuple[V3Option, ...]           # Pool of 3-5 distinct plausible wrong formulations
    explanation: str
    source_quote: str

    def assemble_question(self, seed: int | None = None) -> V3Question:
        """Selects 3 distractors from the pool, merges with correct option, and produces a concrete 4-option question."""
        rng = random.Random(seed) if seed is not None else random.Random()
        distractors = list(self.distractor_pool)
        if len(distractors) > 3:
            distractors = rng.sample(distractors, 3)
        combined = [self.correct_option, *distractors]
        rng.shuffle(combined)
        stem_premise = self.scenario_premise
        if self.branch_context and not stem_premise.startswith(f"[{self.branch_context}]"):
            stem_premise = f"[{self.branch_context}] {stem_premise}"
        return V3Question(
            question_id=f"{self.variant_id}-assembled",
            scenario_premise=stem_premise,
            prompt=self.prompt,
            options=tuple(combined),
            explanation=self.explanation,
            rule_id=self.variant_id,
            source_quote=self.source_quote,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "branch_context": self.branch_context,
            "scenario_premise": self.scenario_premise,
            "prompt": self.prompt,
            "correct_option": self.correct_option.to_dict(),
            "distractor_pool": [opt.to_dict() for opt in self.distractor_pool],
            "explanation": self.explanation,
            "source_quote": self.source_quote,
        }


@dataclass(frozen=True)
class V3ScenarioCase:
    """A master assessment case linked to a rule, containing multiple branch/distractor variants."""
    case_id: str
    rule_id: str
    learning_objective: str
    variants: tuple[V3QuestionVariant, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "rule_id": self.rule_id,
            "learning_objective": self.learning_objective,
            "variants": [v.to_dict() for v in self.variants],
        }


@dataclass(frozen=True)
class V3Lesson:
    lesson_id: str
    title: str
    module_title: str
    content: str                                    # Практический, структурированный обучающий текст
    covered_rule_ids: tuple[str, ...]
    cases: tuple[V3ScenarioCase, ...] = ()          # Банк вариативных кейсов
    questions: tuple[V3Question, ...] = ()          # Собранные конкретные вопросы (для совместимости)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lesson_id": self.lesson_id,
            "title": self.title,
            "module_title": self.module_title,
            "content": self.content,
            "covered_rule_ids": list(self.covered_rule_ids),
            "cases": [c.to_dict() for c in self.cases],
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
