from __future__ import annotations

import pytest

from app.modules.editor_assistant.question_validator import (
    DeterministicMetrics,
    FindingSeverity,
    QuestionFinding,
    QuestionValidationResult,
    ValidatorStatus,
)
from app.modules.editor_assistant.schemas import (
    EditorPatchPath,
    EditorValidationStatus,
)
from app.modules.editor_assistant.taxonomy import EditorQualityIssueLabel
from app.modules.editor_assistant.validation_projection import (
    EditorAssistantValidationProjectionError,
    project_validation_report,
)

MESSAGES = {
    "correct_answer_length_signal": "Длина правильного ответа заметно отличается от вариантов.",
    "correct_answer_style_signal": "Стиль или маркеры уверенности выделяют правильный ответ.",
    "implausible_distractors": "Есть вариант, который не отвечает на вопрос или выглядит неправдоподобно.",
    "multiple_plausible_correct_answers": "Несколько вариантов отмечены как потенциально правильные по явному сигналу.",
    "unsupported_correct_answer": "Правильный ответ не подтверждён разрешённым источником.",
    "malformed_question": "Вопрос или варианты ответа составлены некорректно.",
    "duplicate_question": "Вопрос дублирует другой вопрос в этом тесте.",
    "rote_recall_only": "Вопрос похож на проверку запоминания без применения знаний.",
    "language_or_translation_problem": "Есть явный сигнал языковой или переводческой проблемы.",
    "explanation_leaked_into_answer": "Объяснение попало в текст варианта ответа.",
    "other": "Найдена дополнительная проблема качества.",
}


def finding(
    code: str,
    path: str,
    *,
    blocking: bool = False,
) -> QuestionFinding:
    return QuestionFinding(
        code=EditorQualityIssueLabel(code),
        severity=FindingSeverity.ERROR if blocking else FindingSeverity.WARNING,
        blocking=blocking,
        field_path=path,
        message=MESSAGES[code],
    )


def validation_result(
    status: ValidatorStatus,
    findings: tuple[QuestionFinding, ...],
) -> QuestionValidationResult:
    return QuestionValidationResult(
        validator_version="question-validator-v1",
        status=status,
        findings=findings,
        metrics=DeterministicMetrics(
            questions_checked=1,
            eligible_questions=1,
            malformed_questions=0,
            duplicate_questions=0,
            longest_answer_predictions=0,
            longest_answer_unpredicted=0,
            longest_answer_correct=0,
            longest_answer_accuracy=None,
            correct_longest_share=None,
            issue_count=len(findings),
            blocking_issue_count=sum(item.blocking for item in findings),
        ),
        choose_longest_baseline=(),
    )


def test_pass_projection_has_no_issues() -> None:
    report = project_validation_report(())

    assert report.status is EditorValidationStatus.PASS
    assert report.issues == ()


def test_warning_length_signal_preserves_label_message_and_flag() -> None:
    report = project_validation_report(
        validation_result(
            ValidatorStatus.WARN,
            (finding("correct_answer_length_signal", "questions[0].options"),),
        )
    )

    issue = report.issues[0]
    assert report.status is EditorValidationStatus.WARN
    assert issue.code is EditorQualityIssueLabel.CORRECT_ANSWER_LENGTH_SIGNAL
    assert issue.message == MESSAGES["correct_answer_length_signal"]
    assert issue.blocking is False
    assert issue.field_path is EditorPatchPath.ANSWER_OPTIONS


def test_blocking_unsupported_answer_projects_to_fail() -> None:
    report = project_validation_report(
        (finding("unsupported_correct_answer", "questions[0].options[1]", blocking=True),)
    )

    assert report.status is EditorValidationStatus.FAIL
    assert report.issues[0].code is EditorQualityIssueLabel.UNSUPPORTED_CORRECT_ANSWER
    assert report.issues[0].message == MESSAGES["unsupported_correct_answer"]
    assert report.issues[0].blocking is True
    assert report.issues[0].field_path is EditorPatchPath.ANSWER_OPTIONS


@pytest.mark.parametrize(
    ("internal_path", "public_path", "code", "blocking"),
    (
        ("questions", EditorPatchPath.TEXT, "malformed_question", True),
        ("questions[0]", EditorPatchPath.TEXT, "duplicate_question", True),
        ("questions[0].prompt", EditorPatchPath.TEXT, "rote_recall_only", False),
        ("questions[0].options", EditorPatchPath.ANSWER_OPTIONS, "implausible_distractors", False),
        ("questions[0].options[1]", EditorPatchPath.ANSWER_OPTIONS, "unsupported_correct_answer", True),
        ("questions[*].options", EditorPatchPath.ANSWER_OPTIONS, "correct_answer_style_signal", False),
        (
            "questions[0].explanation",
            EditorPatchPath.EXPLANATION,
            "explanation_leaked_into_answer",
            True,
        ),
    ),
)
def test_all_recognized_validator_paths_are_canonicalized(
    internal_path: str,
    public_path: EditorPatchPath,
    code: str,
    blocking: bool,
) -> None:
    report = project_validation_report((finding(code, internal_path, blocking=blocking),))

    assert report.issues[0].field_path is public_path


def test_mixed_warning_and_blocking_findings_yield_fail() -> None:
    report = project_validation_report(
        (
            finding("correct_answer_length_signal", "questions[0].options"),
            finding("malformed_question", "questions[0]", blocking=True),
        )
    )

    assert report.status is EditorValidationStatus.FAIL
    assert [issue.blocking for issue in report.issues] == [False, True]


def test_duplicate_projection_is_deterministic_and_keeps_first_order() -> None:
    report = project_validation_report(
        (
            finding("correct_answer_length_signal", "questions[0].options"),
            finding("correct_answer_length_signal", "questions[*].options"),
            finding("correct_answer_length_signal", "questions[0].options[1]"),
            finding("correct_answer_length_signal", "questions[0].options"),
        )
    )

    assert [issue.field_path for issue in report.issues] == [
        EditorPatchPath.ANSWER_OPTIONS,
    ]
    assert len(report.issues) == 1


def test_unknown_path_is_rejected_without_echoing_raw_path() -> None:
    raw_path = "questions[0].provider_secret"

    with pytest.raises(EditorAssistantValidationProjectionError) as error:
        project_validation_report((finding("other", raw_path),))

    assert error.value.code == "validation_projection_failed"
    assert raw_path not in str(error.value)
    assert str(error.value) == "Не удалось подготовить отчёт проверки качества."


def test_more_than_twenty_distinct_public_issues_fails_closed() -> None:
    codes = tuple(MESSAGES)
    findings = tuple(
        finding(
            codes[index % len(codes)],
            (
                "questions[0]"
                if index % 3 == 0
                else "questions[0].options"
                if index % 3 == 1
                else "questions[0].explanation"
            ),
            blocking=index % 2 == 0,
        )
        for index in range(21)
    )

    with pytest.raises(EditorAssistantValidationProjectionError) as error:
        project_validation_report(findings)

    assert error.value.code == "validation_projection_failed"
    assert str(error.value) == "Не удалось подготовить отчёт проверки качества."


def test_public_result_contains_no_provider_metadata() -> None:
    report = project_validation_report(
        (finding("other", "questions[0].prompt"),)
    )
    payload = report.model_dump(mode="json")

    assert set(payload) == {"status", "issues"}
    assert not any(
        forbidden in str(payload)
        for forbidden in ("provider", "model", "raw_instruction", "source_excerpt", "tenant")
    )
