from dataclasses import FrozenInstanceError

import pytest

from app.modules.editor_assistant.question_validator import (
    AnswerOption,
    FindingSeverity,
    LanguageAnomalySignal,
    Question,
    QuestionSet,
    QuestionSignals,
    QuestionValidatorInputError,
    SourceSupportSignal,
    ValidatorConfig,
    ValidatorStatus,
    validate_question_set,
)
from app.modules.editor_assistant.taxonomy import EditorQualityIssueLabel


def option(text: str, *, correct: bool = False) -> AnswerOption:
    return AnswerOption(text=text, is_correct=correct)


def issue_codes(result) -> set[EditorQualityIssueLabel]:
    return {finding.code for finding in result.findings}


def test_balanced_question_passes_and_longest_baseline_does_not_claim_truth() -> None:
    result = validate_question_set(
        QuestionSet(
            (
                Question(
                    "q-1",
                        "Что нужно сделать перед публикацией курса?",
                    (
                        option("Проверить содержание", correct=True),
                        option("Открыть курс"),
                        option("Уточнить срок"),
                    ),
                ),
            )
        )
    )

    assert result.status is ValidatorStatus.PASS
    assert result.validator_version == "question-validator-v1"
    assert result.metrics.longest_answer_predictions == 0
    assert result.metrics.longest_answer_correct == 0
    assert result.metrics.longest_answer_unpredicted == 1
    assert result.choose_longest_baseline[0].predicts_keyed_answer is None


def test_malformed_question_and_options_fail_closed_as_content_findings() -> None:
    result = validate_question_set(
        QuestionSet(
            (
                Question(
                    "q-1",
                    "",
                    (
                        option(""),
                        option("Одинаковый ответ"),
                        option("Одинаковый ответ", correct=True),
                    ),
                ),
            )
        )
    )

    assert result.status is ValidatorStatus.FAIL
    assert result.metrics.malformed_questions == 1
    assert EditorQualityIssueLabel.MALFORMED_QUESTION in issue_codes(result)
    assert all(finding.severity == FindingSeverity.ERROR for finding in result.findings)


def test_duplicate_questions_and_near_duplicate_prompts_are_reported() -> None:
    result = validate_question_set(
        QuestionSet(
            (
                Question(
                    "q-1",
                    "Как сотрудник подтверждает завершение обучения?",
                    (option("Через журнал", correct=True), option("Никак")),
                ),
                Question(
                    "q-2",
                    "Как сотрудник подтверждает завершение обучения?",
                    (option("Через журнал", correct=True), option("Никак")),
                ),
                Question(
                    "q-3",
                    "Как сотрудник подтверждает завершение обучения сотрудника?",
                    (option("Через журнал", correct=True), option("Никак")),
                ),
            )
        ),
        ValidatorConfig(duplicate_similarity_threshold=0.80),
    )

    assert result.metrics.duplicate_questions == 2
    assert EditorQualityIssueLabel.DUPLICATE_QUESTION in issue_codes(result)
    assert result.status is ValidatorStatus.FAIL


def test_length_style_and_choose_longest_baseline_are_versioned_signals() -> None:
    questions = tuple(
        Question(
            f"q-{index}",
            f"Какой порядок нужен в ситуации {index}?",
            (
                option("Это всегда единственно правильный и обязательный порядок действий", correct=True),
                option("Проверить шаг"),
                option("Уточнить срок"),
            ),
        )
        for index in range(1, 5)
    )
    result = validate_question_set(
        QuestionSet(questions),
        ValidatorConfig(validator_version="question-validator-v1-test"),
    )

    assert result.validator_version == "question-validator-v1-test"
    assert result.metrics.correct_longest_share == 1.0
    assert result.metrics.longest_answer_accuracy == 1.0
    assert result.status is ValidatorStatus.FAIL
    assert EditorQualityIssueLabel.CORRECT_ANSWER_LENGTH_SIGNAL in issue_codes(result)
    assert EditorQualityIssueLabel.CORRECT_ANSWER_STYLE_SIGNAL in issue_codes(result)


def test_explicit_evidence_signals_are_required_for_semantic_claims() -> None:
    result = validate_question_set(
        QuestionSet(
            (
                Question(
                    "q-1",
                    "Как обработать обращение клиента?",
                    (
                        option("По утвержденному сценарию", correct=True),
                        option("Сделать что угодно"),
                        option("Передать в архив"),
                    ),
                    signals=QuestionSignals(
                        source_support=SourceSupportSignal.UNSUPPORTED,
                        explicit_plausible_answer_indices=(0, 2),
                        explicit_implausible_distractor_indices=(1,),
                        language_anomaly=LanguageAnomalySignal.MIXED_LANGUAGE,
                    ),
                ),
            )
        )
    )

    codes = issue_codes(result)
    assert EditorQualityIssueLabel.UNSUPPORTED_CORRECT_ANSWER in codes
    assert EditorQualityIssueLabel.MULTIPLE_PLAUSIBLE_CORRECT_ANSWERS in codes
    assert EditorQualityIssueLabel.IMPLAUSIBLE_DISTRACTORS in codes
    assert EditorQualityIssueLabel.LANGUAGE_OR_TRANSLATION_PROBLEM in codes


def test_unassessed_signals_do_not_infer_unsupported_or_multiple_correct() -> None:
    result = validate_question_set(
        QuestionSet(
            (
                Question(
                    "q-1",
                    "Как сохранить результат?",
                    (option("Нажать сохранить", correct=True), option("Закрыть окно")),
                ),
            )
        )
    )

    codes = issue_codes(result)
    assert EditorQualityIssueLabel.UNSUPPORTED_CORRECT_ANSWER not in codes
    assert EditorQualityIssueLabel.MULTIPLE_PLAUSIBLE_CORRECT_ANSWERS not in codes
    assert EditorQualityIssueLabel.LANGUAGE_OR_TRANSLATION_PROBLEM not in codes


def test_rote_recall_and_explanation_leakage_are_deterministic() -> None:
    result = validate_question_set(
        QuestionSet(
            (
                Question(
                    "q-1",
                    "Что такое онбординг?",
                    (
                        option("Онбординг — процесс адаптации сотрудника", correct=True),
                        option("Согласование бюджета"),
                    ),
                    explanation="Онбординг — процесс адаптации сотрудника в компании.",
                ),
            )
        )
    )

    codes = issue_codes(result)
    assert EditorQualityIssueLabel.ROTE_RECALL_ONLY in codes
    assert EditorQualityIssueLabel.EXPLANATION_LEAKED_INTO_ANSWER in codes


def test_invalid_schema_error_does_not_reflect_customer_text() -> None:
    secret_text = "CONFIDENTIAL CUSTOMER TEXT"

    with pytest.raises(QuestionValidatorInputError) as error:
        AnswerOption(secret_text, is_correct="yes")
    assert secret_text not in str(error.value)

    with pytest.raises(QuestionValidatorInputError) as error:
        validate_question_set(object())
    assert secret_text not in str(error.value)


def test_signal_indices_and_bounds_are_rejected_without_provider_calls() -> None:
    with pytest.raises(QuestionValidatorInputError):
        validate_question_set(
            QuestionSet(
                (
                    Question(
                        "q-1",
                        "Вопрос",
                        (option("Да", correct=True), option("Нет")),
                        signals=QuestionSignals(explicit_plausible_answer_indices=(2,)),
                    ),
                )
            )
        )

    with pytest.raises(QuestionValidatorInputError):
        validate_question_set(
            QuestionSet(
                tuple(
                    Question(
                        str(index),
                        "Вопрос",
                        (option("Да", correct=True), option("Нет")),
                    )
                    for index in range(101)
                )
            )
        )


def test_frozen_configuration_and_result_are_immutable() -> None:
    config = ValidatorConfig()
    result = validate_question_set(QuestionSet(()), config)

    with pytest.raises(FrozenInstanceError):
        config.validator_version = "changed"
    with pytest.raises(FrozenInstanceError):
        result.validator_version = "changed"


def test_empty_question_set_is_blocking_malformed_input() -> None:
    result = validate_question_set(QuestionSet(()))

    assert result.status is ValidatorStatus.FAIL
    assert result.metrics.questions_checked == 0
    assert result.findings[0].code is EditorQualityIssueLabel.MALFORMED_QUESTION
    assert result.findings[0].field_path == "questions"
    assert result.findings[0].blocking is True


def test_malformed_structural_issue_cannot_be_disabled() -> None:
    result = validate_question_set(
        QuestionSet(()),
        ValidatorConfig(
            enabled_issue_codes=(EditorQualityIssueLabel.CORRECT_ANSWER_STYLE_SIGNAL,)
        ),
    )

    assert EditorQualityIssueLabel.MALFORMED_QUESTION in issue_codes(result)
    assert result.status is ValidatorStatus.FAIL


def test_implausible_signal_cannot_mark_a_keyed_option() -> None:
    with pytest.raises(QuestionValidatorInputError) as error:
        validate_question_set(
            QuestionSet(
                (
                    Question(
                        "q-1",
                        "Как сохранить результат?",
                        (option("Сохранить", correct=True), option("Закрыть")),
                        signals=QuestionSignals(
                            explicit_implausible_distractor_indices=(0,)
                        ),
                    ),
                )
            )
        )
    assert "Сохранить" not in str(error.value)


def test_opaque_codes_reject_spaces_and_prose() -> None:
    with pytest.raises(QuestionValidatorInputError):
        Question("question 1", "Вопрос", (option("Да", correct=True), option("Нет")))
    with pytest.raises(QuestionValidatorInputError):
        QuestionSet((), locale="Русский язык")
    with pytest.raises(QuestionValidatorInputError):
        ValidatorConfig(validator_version="version for customers")


def longest_question(index: int, *, keyed_is_longest: bool) -> Question:
    correct = "Подробный правильный ответ" if keyed_is_longest else "Ключевой ответ"
    distractor = "Короткий вариант" if keyed_is_longest else "Подробный альтернативный вариант"
    return Question(
        f"threshold-{index}",
        f"Как выполнить действие {index}?",
        (option(correct, correct=True), option(distractor), option("Иной шаг")),
    )


def test_quiz_thresholds_do_not_overfire_below_minimum_sample() -> None:
    result = validate_question_set(
        QuestionSet(
            tuple(longest_question(index, keyed_is_longest=True) for index in range(3))
        )
    )

    assert result.metrics.eligible_questions == 3
    assert result.metrics.longest_answer_predictions == 3
    assert result.metrics.longest_answer_accuracy == 1.0
    assert result.metrics.correct_longest_share == 1.0
    assert not any(
        finding.field_path == "questions[*].options" for finding in result.findings
    )
    assert result.status is not ValidatorStatus.FAIL


def test_longest_share_exact_warn_boundary_does_not_warn() -> None:
    result = validate_question_set(
        QuestionSet(
            tuple(
                longest_question(index, keyed_is_longest=index < 2)
                for index in range(5)
            )
        )
    )

    assert result.metrics.correct_longest_share == 0.4
    assert not any(
        finding.field_path == "questions[*].options" for finding in result.findings
    )


def test_longest_share_half_warns_but_does_not_block() -> None:
    result = validate_question_set(
        QuestionSet(
            tuple(
                longest_question(index, keyed_is_longest=index < 2)
                for index in range(4)
            )
        )
    )

    wildcard_findings = [
        finding
        for finding in result.findings
        if finding.field_path == "questions[*].options"
    ]
    assert result.metrics.correct_longest_share == 0.5
    assert len(wildcard_findings) == 1
    assert wildcard_findings[0].blocking is False


def test_longest_share_above_block_boundary_blocks() -> None:
    result = validate_question_set(
        QuestionSet(
            tuple(
                longest_question(index, keyed_is_longest=index < 3)
                for index in range(5)
            )
        )
    )

    assert result.metrics.correct_longest_share == 0.6
    assert any(
        finding.field_path == "questions[*].options" and finding.blocking
        for finding in result.findings
    )
    assert result.status is ValidatorStatus.FAIL


def test_choose_longest_exact_pass_score_blocks_only_with_eligible_sample() -> None:
    result = validate_question_set(
        QuestionSet(
            tuple(
                longest_question(index, keyed_is_longest=index < 4)
                for index in range(5)
            )
        ),
        ValidatorConfig(choose_longest_pass_score=0.8, longest_answer_block_share=0.9),
    )

    assert result.metrics.longest_answer_predictions == 5
    assert result.metrics.longest_answer_accuracy == 0.8
    assert any(
        finding.field_path == "questions[*].options" and finding.blocking
        for finding in result.findings
    )


def test_choose_longest_below_pass_score_does_not_block() -> None:
    result = validate_question_set(
        QuestionSet(
            tuple(
                longest_question(index, keyed_is_longest=index < 3)
                for index in range(5)
            )
        ),
        ValidatorConfig(choose_longest_pass_score=0.8, longest_answer_block_share=0.9),
    )

    assert result.metrics.longest_answer_accuracy == 0.6
    assert not any(
        finding.field_path == "questions[*].options" and finding.blocking
        for finding in result.findings
    )


def test_choose_longest_tie_is_reported_as_unpredicted() -> None:
    result = validate_question_set(
        QuestionSet(
            (
                Question(
                    "q-1",
                    "Что выбрать?",
                    (
                        option("Первый вариант", correct=True),
                        option("Второй ответ"),
                    ),
                ),
            )
        )
    )

    prediction = result.choose_longest_baseline[0]
    assert prediction.predicted_option_index is None
    assert prediction.predicts_keyed_answer is None
    assert result.metrics.longest_answer_predictions == 0
