"""Pure policy for actionable learning signals and action closure."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, Protocol, TypeVar

TrainingIssue = Literal["not_started", "stalled", "overdue", "failed_required_quiz"]
CloseResolution = Literal["observed", "manual", "cancelled"]

MIN_WEAK_QUESTION_RESPONDENTS = 5
MIN_WEAK_QUESTION_INCORRECT_PERCENT = 30.0


class LearningActionValidationError(ValueError):
    """A requested action transition does not meet the public contract."""


class TrainingSignal(Protocol):
    @property
    def deadline_status(self) -> str: ...

    @property
    def computed_status(self) -> str: ...

    @property
    def progress_percent(self) -> int: ...

    @property
    def quiz_attempts_count(self) -> int: ...

    @property
    def best_score(self) -> int | None: ...

    @property
    def failed_required_quiz(self) -> bool: ...


class QuestionSignal(Protocol):
    respondents: int
    incorrect_percent: float


QuestionT = TypeVar("QuestionT", bound=QuestionSignal)


def classify_training_issue(row: TrainingSignal) -> TrainingIssue | None:
    """Map one current enrollment occurrence to its highest-priority issue."""

    if row.computed_status in {"completed", "cancelled", "superseded"}:
        return None
    if row.deadline_status == "overdue":
        return "overdue"
    if row.failed_required_quiz:
        return "failed_required_quiz"
    if row.computed_status == "in_progress" or row.progress_percent > 0:
        return "stalled"
    return "not_started"


def select_weak_questions(questions: Iterable[QuestionT]) -> list[QuestionT]:
    """Return privacy-safe weak signals, strongest and best-supported first."""

    selected = [
        question
        for question in questions
        if question.respondents >= MIN_WEAK_QUESTION_RESPONDENTS
        and question.incorrect_percent >= MIN_WEAK_QUESTION_INCORRECT_PERCENT
    ]
    return sorted(selected, key=lambda item: (-item.incorrect_percent, -item.respondents))


def validate_close_request(*, resolution: CloseResolution, note: str | None) -> None:
    """Observed outcomes are self-evidencing; manual/cancelled closure is explained."""

    if resolution in {"manual", "cancelled"} and not (note or "").strip():
        raise LearningActionValidationError("A reason is required for manual or cancelled closure")
