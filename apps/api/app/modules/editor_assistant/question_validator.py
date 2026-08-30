"""Pure deterministic quality checks for generated assessment questions.

This module deliberately has no provider, persistence, network, or framework
dependencies.  Signals that require source or answer-key evidence are explicit
inputs; the validator never infers semantic truth from wording alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from statistics import median
from typing import Final

from .taxonomy import EditorQualityIssueLabel


class QuestionValidatorInputError(ValueError):
    """Raised when the validator input is outside its bounded schema."""


class ValidatorStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class FindingSeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


class SourceSupportSignal(StrEnum):
    """Explicit source contract signal; ``UNASSESSED`` makes no claim."""

    UNASSESSED = "unassessed"
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


class LanguageAnomalySignal(StrEnum):
    """Explicit deterministic language signal; no language detection is run."""

    NONE = "none"
    MIXED_LANGUAGE = "mixed_language"
    TRANSLATION_MISMATCH = "translation_mismatch"
    UNSUPPORTED_LOCALE = "unsupported_locale"


_MAX_SIGNAL_INDICES: Final = 8
_MAX_VALIDATOR_VERSION_LENGTH: Final = 64
_FIELD_PATH_RE: Final = re.compile(r"^[A-Za-z0-9_.*\[\]-]{1,128}$")
_OPAQUE_CODE_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TOKEN_RE: Final = re.compile(r"\w+", re.UNICODE)


_ISSUE_MESSAGES: Final[dict[EditorQualityIssueLabel, str]] = {
    EditorQualityIssueLabel.CORRECT_ANSWER_LENGTH_SIGNAL:
        "Длина правильного ответа заметно отличается от вариантов.",
    EditorQualityIssueLabel.CORRECT_ANSWER_STYLE_SIGNAL:
        "Стиль или маркеры уверенности выделяют правильный ответ.",
    EditorQualityIssueLabel.IMPLAUSIBLE_DISTRACTORS:
        "Есть вариант, который не отвечает на вопрос или выглядит неправдоподобно.",
    EditorQualityIssueLabel.MULTIPLE_PLAUSIBLE_CORRECT_ANSWERS:
        "Несколько вариантов отмечены как потенциально правильные по явному сигналу.",
    EditorQualityIssueLabel.UNSUPPORTED_CORRECT_ANSWER:
        "Правильный ответ не подтверждён разрешённым источником.",
    EditorQualityIssueLabel.MALFORMED_QUESTION:
        "Вопрос или варианты ответа составлены некорректно.",
    EditorQualityIssueLabel.DUPLICATE_QUESTION:
        "Вопрос дублирует другой вопрос в этом тесте.",
    EditorQualityIssueLabel.ROTE_RECALL_ONLY:
        "Вопрос похож на проверку запоминания без применения знаний.",
    EditorQualityIssueLabel.LANGUAGE_OR_TRANSLATION_PROBLEM:
        "Есть явный сигнал языковой или переводческой проблемы.",
    EditorQualityIssueLabel.EXPLANATION_LEAKED_INTO_ANSWER:
        "Объяснение попало в текст варианта ответа.",
    EditorQualityIssueLabel.OTHER: "Найдена дополнительная проблема качества.",
}

# Structural malformed input is always a safety blocker. It cannot be
# disabled by configuration; all other labels remain configurable signals.
_NON_DISABLEABLE_ISSUE_CODES: Final = frozenset(
    {EditorQualityIssueLabel.MALFORMED_QUESTION}
)


def _fixed_input_error() -> QuestionValidatorInputError:
    return QuestionValidatorInputError("Некорректные данные валидатора")


def _require_bounded_text(value: object, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise _fixed_input_error()
    return re.sub(r"\s+", " ", value).strip()


def _require_code(value: object, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or not _OPAQUE_CODE_RE.fullmatch(value)
    ):
        raise _fixed_input_error()
    return value


def _normalize_text(value: str) -> str:
    return " ".join(_TOKEN_RE.findall(value.casefold()))


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(_TOKEN_RE.findall(value.casefold()))


def _token_similarity(left: str, right: str) -> float:
    left_tokens = set(_tokens(left))
    right_tokens = set(_tokens(right))
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


@dataclass(frozen=True, slots=True)
class ValidatorConfig:
    """Immutable, versioned thresholds and bounded validator settings."""

    validator_version: str = "question-validator-v1"
    max_questions: int = 100
    max_options: int = 8
    max_question_id_length: int = 128
    max_prompt_length: int = 2_000
    max_option_length: int = 1_200
    max_explanation_length: int = 3_000
    correct_answer_length_warn_ratio: float = 1.35
    distractor_length_tolerance: float = 0.25
    min_balanced_distractors: int = 2
    longest_answer_warn_share: float = 0.40
    longest_answer_block_share: float = 0.50
    choose_longest_pass_score: float = 0.80
    min_quiz_sample_size: int = 4
    duplicate_similarity_threshold: float = 0.90
    near_duplicate_option_similarity_threshold: float = 0.90
    enabled_issue_codes: tuple[EditorQualityIssueLabel, ...] = tuple(
        EditorQualityIssueLabel
    )
    style_markers: tuple[str, ...] = (
        "всегда",
        "никогда",
        "только",
        "обязательно",
        "точно",
        "always",
        "never",
        "must",
    )
    rote_recall_markers: tuple[str, ...] = (
        "что такое",
        "что означает",
        "определите термин",
        "назовите",
        "перечислите",
        "what is",
        "what does",
        "define",
        "name the",
        "list the",
    )
    application_markers: tuple[str, ...] = (
        "ситуац",
        "пример",
        "как поступить",
        "что сделать",
        "кейс",
        "scenario",
        "example",
        "what should",
    )

    def __post_init__(self) -> None:
        version = _require_code(self.validator_version, _MAX_VALIDATOR_VERSION_LENGTH)
        object.__setattr__(self, "validator_version", version)
        integer_fields = (
            "max_questions",
            "max_options",
            "max_question_id_length",
            "max_prompt_length",
            "max_option_length",
            "max_explanation_length",
            "min_balanced_distractors",
            "min_quiz_sample_size",
        )
        for name in integer_fields:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise _fixed_input_error()
        if self.max_options < 2 or self.min_balanced_distractors > self.max_options - 1:
            raise _fixed_input_error()
        ratio_fields = (
            "correct_answer_length_warn_ratio",
            "distractor_length_tolerance",
            "longest_answer_warn_share",
            "longest_answer_block_share",
            "choose_longest_pass_score",
            "duplicate_similarity_threshold",
            "near_duplicate_option_similarity_threshold",
        )
        for name in ratio_fields:
            value = getattr(self, name)
            if not isinstance(value, float | int) or isinstance(value, bool):
                raise _fixed_input_error()
            if name == "correct_answer_length_warn_ratio":
                valid = value > 1.0
            elif name == "distractor_length_tolerance":
                valid = 0.0 < value < 1.0
            else:
                valid = 0.0 < value <= 1.0
            if not valid:
                raise _fixed_input_error()
        if self.longest_answer_block_share < self.longest_answer_warn_share:
            raise _fixed_input_error()
        for name in (
            "style_markers",
            "rote_recall_markers",
            "application_markers",
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple) or not values or any(
                not isinstance(item, str) or not item.strip() or len(item) > 80
                for item in values
            ):
                raise _fixed_input_error()
        try:
            codes = tuple(EditorQualityIssueLabel(code) for code in self.enabled_issue_codes)
        except (TypeError, ValueError):
            raise _fixed_input_error() from None
        if not codes or len(set(codes)) != len(codes):
            raise _fixed_input_error()
        object.__setattr__(self, "enabled_issue_codes", codes)


@dataclass(frozen=True, slots=True)
class AnswerOption:
    text: str
    is_correct: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.is_correct, bool):
            raise _fixed_input_error()
        object.__setattr__(self, "text", _require_bounded_text(self.text, 1_200))


@dataclass(frozen=True, slots=True)
class QuestionSignals:
    """Explicit evidence supplied by a deterministic upstream contract."""

    source_support: SourceSupportSignal = SourceSupportSignal.UNASSESSED
    explicit_plausible_answer_indices: tuple[int, ...] = ()
    explicit_implausible_distractor_indices: tuple[int, ...] = ()
    language_anomaly: LanguageAnomalySignal = LanguageAnomalySignal.NONE

    def __post_init__(self) -> None:
        try:
            source_support = SourceSupportSignal(self.source_support)
            language_anomaly = LanguageAnomalySignal(self.language_anomaly)
        except (TypeError, ValueError):
            raise _fixed_input_error() from None
        object.__setattr__(self, "source_support", source_support)
        object.__setattr__(self, "language_anomaly", language_anomaly)
        for name in (
            "explicit_plausible_answer_indices",
            "explicit_implausible_distractor_indices",
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple) or len(values) > _MAX_SIGNAL_INDICES:
                raise _fixed_input_error()
            if any(
                not isinstance(index, int) or isinstance(index, bool) or index < 0
                for index in values
            ) or len(set(values)) != len(values):
                raise _fixed_input_error()
            object.__setattr__(self, name, tuple(sorted(values)))


@dataclass(frozen=True, slots=True)
class Question:
    question_id: str
    prompt: str
    options: tuple[AnswerOption, ...]
    explanation: str = ""
    signals: QuestionSignals = QuestionSignals()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "question_id",
            _require_code(self.question_id, 128),
        )
        object.__setattr__(
            self,
            "prompt",
            _require_bounded_text(self.prompt, 2_000),
        )
        options = tuple(self.options)
        if len(options) > 8 or not all(isinstance(option, AnswerOption) for option in options):
            raise _fixed_input_error()
        object.__setattr__(self, "options", options)
        object.__setattr__(
            self,
            "explanation",
            _require_bounded_text(self.explanation, 3_000),
        )
        if not isinstance(self.signals, QuestionSignals):
            raise _fixed_input_error()


@dataclass(frozen=True, slots=True)
class QuestionSet:
    questions: tuple[Question, ...]
    locale: str = "ru-RU"

    def __post_init__(self) -> None:
        questions = tuple(self.questions)
        if len(questions) > 100 or not all(isinstance(item, Question) for item in questions):
            raise _fixed_input_error()
        object.__setattr__(self, "questions", questions)
        object.__setattr__(self, "locale", _require_code(self.locale, 32))


@dataclass(frozen=True, slots=True)
class QuestionFinding:
    code: EditorQualityIssueLabel
    severity: FindingSeverity
    blocking: bool
    field_path: str
    message: str

    def __post_init__(self) -> None:
        try:
            code = EditorQualityIssueLabel(self.code)
            severity = FindingSeverity(self.severity)
        except (TypeError, ValueError):
            raise _fixed_input_error() from None
        field_path = _require_bounded_text(self.field_path, 128)
        if not _FIELD_PATH_RE.fullmatch(field_path) or not isinstance(self.blocking, bool):
            raise _fixed_input_error()
        if self.message != _ISSUE_MESSAGES[code]:
            raise _fixed_input_error()
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "field_path", field_path)


@dataclass(frozen=True, slots=True)
class LongestAnswerPrediction:
    question_index: int
    predicted_option_index: int | None
    keyed_option_index: int | None
    predicts_keyed_answer: bool | None


@dataclass(frozen=True, slots=True)
class DeterministicMetrics:
    questions_checked: int
    eligible_questions: int
    malformed_questions: int
    duplicate_questions: int
    longest_answer_predictions: int
    longest_answer_unpredicted: int
    longest_answer_correct: int
    longest_answer_accuracy: float | None
    correct_longest_share: float | None
    issue_count: int
    blocking_issue_count: int


@dataclass(frozen=True, slots=True)
class QuestionValidationResult:
    validator_version: str
    status: ValidatorStatus
    findings: tuple[QuestionFinding, ...]
    metrics: DeterministicMetrics
    choose_longest_baseline: tuple[LongestAnswerPrediction, ...]


def _message(code: EditorQualityIssueLabel) -> str:
    return _ISSUE_MESSAGES[code]


def _finding(
    code: EditorQualityIssueLabel,
    field_path: str,
    *,
    blocking: bool = False,
) -> QuestionFinding:
    severity = FindingSeverity.ERROR if blocking else FindingSeverity.WARNING
    return QuestionFinding(code, severity, blocking, field_path, _message(code))


def _option_lengths(question: Question) -> tuple[int, ...]:
    return tuple(max(1, len(_tokens(option.text))) for option in question.options)


def _unique_longest_index(lengths: tuple[int, ...]) -> int | None:
    if not lengths:
        return None
    longest = max(lengths)
    if lengths.count(longest) != 1:
        return None
    return lengths.index(longest)


def _has_terminal_style(text: str) -> bool:
    return bool(re.search(r"[.!?;:]\s*$", text))


def _looks_rote_recall(question: Question, correct_text: str, config: ValidatorConfig) -> bool:
    prompt = _normalize_text(question.prompt)
    if any(marker in prompt for marker in config.application_markers):
        return False
    marker = next(
        (marker for marker in config.rote_recall_markers if marker in prompt),
        None,
    )
    if marker is None:
        return False
    after_marker = prompt.split(marker, 1)[1].strip()
    prompt_term = after_marker.split(" ", 1)[0] if after_marker else ""
    return bool(prompt_term and prompt_term in _normalize_text(correct_text))


def _explanation_is_leaked(question: Question) -> bool:
    explanation_tokens = _tokens(question.explanation)
    if len(explanation_tokens) < 4:
        return False
    phrase = " ".join(explanation_tokens[:4])
    return any(phrase in _normalize_text(option.text) for option in question.options)


def _validate_signal_indices(question: Question) -> None:
    option_count = len(question.options)
    for indices in (
        question.signals.explicit_plausible_answer_indices,
        question.signals.explicit_implausible_distractor_indices,
    ):
        if any(index >= option_count for index in indices):
            raise _fixed_input_error()
    correct_indices = {
        option_index
        for option_index, option in enumerate(question.options)
        if option.is_correct
    }
    if any(
        index in correct_indices
        for index in question.signals.explicit_implausible_distractor_indices
    ):
        raise _fixed_input_error()


def validate_question_set(
    question_set: QuestionSet,
    config: ValidatorConfig | None = None,
) -> QuestionValidationResult:
    """Return a deterministic quality report for one bounded question set.

    Invalid schemas raise :class:`QuestionValidatorInputError` with a fixed
    message.  Content problems are represented as findings so a methodologist
    can review them.  No semantic, ML, provider, or source retrieval work is
    performed here.
    """

    if not isinstance(question_set, QuestionSet):
        raise _fixed_input_error()
    config = config or ValidatorConfig()
    if not isinstance(config, ValidatorConfig):
        raise _fixed_input_error()
    if len(question_set.questions) > config.max_questions:
        raise _fixed_input_error()
    for question in question_set.questions:
        _validate_signal_indices(question)
        if (
            len(question.question_id) > config.max_question_id_length
            or len(question.prompt) > config.max_prompt_length
            or len(question.explanation) > config.max_explanation_length
            or len(question.options) > config.max_options
            or any(len(option.text) > config.max_option_length for option in question.options)
        ):
            raise _fixed_input_error()
    findings: list[QuestionFinding] = []
    seen_findings: set[tuple[EditorQualityIssueLabel, str, bool]] = set()
    baseline: list[LongestAnswerPrediction] = []
    malformed_count = 0
    duplicate_count = 0
    longest_correct_count = 0

    def add(
        code: EditorQualityIssueLabel,
        field_path: str,
        *,
        blocking: bool = False,
    ) -> None:
        if code not in config.enabled_issue_codes and code not in _NON_DISABLEABLE_ISSUE_CODES:
            return
        key = (code, field_path, blocking)
        if key not in seen_findings:
            findings.append(_finding(code, field_path, blocking=blocking))
            seen_findings.add(key)

    normalized_prompts = [_normalize_text(item.prompt) for item in question_set.questions]
    if not question_set.questions:
        add(EditorQualityIssueLabel.MALFORMED_QUESTION, "questions", blocking=True)
    for index, question in enumerate(question_set.questions):
        question_path = f"questions[{index}]"
        option_path = f"{question_path}.options"
        correct_indices = [
            option_index
            for option_index, option in enumerate(question.options)
            if option.is_correct
        ]
        question_malformed = False
        if not question.prompt or len(question.options) < 2:
            add(EditorQualityIssueLabel.MALFORMED_QUESTION, question_path, blocking=True)
            question_malformed = True
        if len(correct_indices) != 1:
            add(EditorQualityIssueLabel.MALFORMED_QUESTION, option_path, blocking=True)
            question_malformed = True
            if len(correct_indices) > 1:
                add(
                    EditorQualityIssueLabel.MULTIPLE_PLAUSIBLE_CORRECT_ANSWERS,
                    option_path,
                    blocking=True,
                )
        for option_index, option in enumerate(question.options):
            if not option.text:
                add(
                    EditorQualityIssueLabel.MALFORMED_QUESTION,
                    f"{option_path}[{option_index}]",
                    blocking=True,
                )
                question_malformed = True
        normalized_options = [_normalize_text(option.text) for option in question.options]
        for left_index, left in enumerate(normalized_options):
            for right_index in range(left_index + 1, len(normalized_options)):
                right = normalized_options[right_index]
                if left and left == right or (
                    left
                    and right
                    and _token_similarity(left, right)
                    >= config.near_duplicate_option_similarity_threshold
                ):
                    add(EditorQualityIssueLabel.MALFORMED_QUESTION, option_path, blocking=True)
                    question_malformed = True
                    break
            if question_malformed and normalized_options:
                break
        if question_malformed:
            malformed_count += 1
            continue
        if len(correct_indices) != 1 or len(question.options) < 2:
            continue
        correct_index = correct_indices[0]
        correct_text = question.options[correct_index].text
        lengths = _option_lengths(question)
        predicted_index = _unique_longest_index(lengths)
        predicts_keyed = predicted_index == correct_index if predicted_index is not None else None
        baseline.append(
            LongestAnswerPrediction(
                index,
                predicted_index,
                correct_index,
                predicts_keyed,
            )
        )
        if predicts_keyed:
            longest_correct_count += 1
            add(
                EditorQualityIssueLabel.CORRECT_ANSWER_LENGTH_SIGNAL,
                option_path,
                blocking=False,
            )
        distractor_lengths = [
            length for option_index, length in enumerate(lengths) if option_index != correct_index
        ]
        median_distractor_length = median(distractor_lengths)
        if median_distractor_length and lengths[correct_index] > (
            median_distractor_length * config.correct_answer_length_warn_ratio
        ):
            add(
                EditorQualityIssueLabel.CORRECT_ANSWER_LENGTH_SIGNAL,
                option_path,
            )
        close_distractors = sum(
            abs(length - lengths[correct_index]) / lengths[correct_index]
            <= config.distractor_length_tolerance
            for option_index, length in enumerate(lengths)
            if option_index != correct_index
        )
        if (
            len(distractor_lengths) >= config.min_balanced_distractors
            and close_distractors < config.min_balanced_distractors
        ):
            add(EditorQualityIssueLabel.CORRECT_ANSWER_LENGTH_SIGNAL, option_path)
        correct_markers = set(_tokens(correct_text)) & set(
            marker for value in config.style_markers for marker in _tokens(value)
        )
        distractor_markers = set(
            token
            for option_index, option in enumerate(question.options)
            if option_index != correct_index
            for token in _tokens(option.text)
        )
        if correct_markers - distractor_markers or (
            _has_terminal_style(correct_text)
            and not any(
                _has_terminal_style(option.text)
                for option_index, option in enumerate(question.options)
                if option_index != correct_index
            )
        ):
            add(EditorQualityIssueLabel.CORRECT_ANSWER_STYLE_SIGNAL, option_path)
        if _looks_rote_recall(question, correct_text, config):
            add(EditorQualityIssueLabel.ROTE_RECALL_ONLY, f"{question_path}.prompt")
        if _explanation_is_leaked(question):
            add(
                EditorQualityIssueLabel.EXPLANATION_LEAKED_INTO_ANSWER,
                f"{question_path}.explanation",
                blocking=True,
            )
        signals = question.signals
        if signals.source_support is SourceSupportSignal.UNSUPPORTED:
            add(
                EditorQualityIssueLabel.UNSUPPORTED_CORRECT_ANSWER,
                f"{question_path}.options[{correct_index}]",
                blocking=True,
            )
        if len(signals.explicit_plausible_answer_indices) > 1:
            add(
                EditorQualityIssueLabel.MULTIPLE_PLAUSIBLE_CORRECT_ANSWERS,
                option_path,
                blocking=True,
            )
        if signals.explicit_implausible_distractor_indices:
            add(
                EditorQualityIssueLabel.IMPLAUSIBLE_DISTRACTORS,
                option_path,
            )
        if signals.language_anomaly is not LanguageAnomalySignal.NONE:
            add(
                EditorQualityIssueLabel.LANGUAGE_OR_TRANSLATION_PROBLEM,
                question_path,
            )

    duplicate_indices: set[int] = set()
    for left_index, left_prompt in enumerate(normalized_prompts):
        if not left_prompt:
            continue
        for right_index in range(left_index + 1, len(normalized_prompts)):
            right_prompt = normalized_prompts[right_index]
            if right_prompt and (
                left_prompt == right_prompt
                or _token_similarity(left_prompt, right_prompt)
                >= config.duplicate_similarity_threshold
            ):
                duplicate_indices.add(right_index)
    duplicate_count = len(duplicate_indices)
    for right_index in sorted(duplicate_indices):
        add(
            EditorQualityIssueLabel.DUPLICATE_QUESTION,
            f"questions[{right_index}].prompt",
            blocking=True,
        )

    eligible_count = len(baseline)
    prediction_count = sum(
        prediction.predicted_option_index is not None for prediction in baseline
    )
    unpredicted_count = eligible_count - prediction_count
    longest_accuracy = (
        longest_correct_count / prediction_count if prediction_count else None
    )
    correct_longest_share = (
        longest_correct_count / eligible_count
        if eligible_count
        else None
    )
    if (
        correct_longest_share is not None
        and eligible_count >= config.min_quiz_sample_size
        and correct_longest_share > config.longest_answer_warn_share
    ):
        add(
            EditorQualityIssueLabel.CORRECT_ANSWER_LENGTH_SIGNAL,
            "questions[*].options",
            blocking=correct_longest_share > config.longest_answer_block_share,
        )
    if (
        longest_accuracy is not None
        and eligible_count >= config.min_quiz_sample_size
        and longest_accuracy >= config.choose_longest_pass_score
    ):
        add(
            EditorQualityIssueLabel.CORRECT_ANSWER_LENGTH_SIGNAL,
            "questions[*].options",
            blocking=True,
        )
    blocking_count = sum(item.blocking for item in findings)
    status = (
        ValidatorStatus.FAIL
        if blocking_count
        else ValidatorStatus.WARN
        if findings
        else ValidatorStatus.PASS
    )
    metrics = DeterministicMetrics(
        questions_checked=len(question_set.questions),
        eligible_questions=eligible_count,
        malformed_questions=malformed_count,
        duplicate_questions=duplicate_count,
        longest_answer_predictions=prediction_count,
        longest_answer_unpredicted=unpredicted_count,
        longest_answer_correct=longest_correct_count,
        longest_answer_accuracy=longest_accuracy,
        correct_longest_share=correct_longest_share,
        issue_count=len(findings),
        blocking_issue_count=blocking_count,
    )
    return QuestionValidationResult(
        validator_version=config.validator_version,
        status=status,
        findings=tuple(findings),
        metrics=metrics,
        choose_longest_baseline=tuple(baseline),
    )


__all__ = [
    "AnswerOption",
    "DeterministicMetrics",
    "FindingSeverity",
    "LanguageAnomalySignal",
    "LongestAnswerPrediction",
    "Question",
    "QuestionFinding",
    "QuestionSet",
    "QuestionSignals",
    "QuestionValidationResult",
    "QuestionValidatorInputError",
    "SourceSupportSignal",
    "ValidatorConfig",
    "ValidatorStatus",
    "validate_question_set",
]
