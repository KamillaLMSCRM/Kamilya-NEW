"""Public HTTP DTO contract for the single-question editor assistant."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from app.modules.editor_assistant.schemas import (
    EditorApplicability,
    EditorAssistantApplyRequest,
    EditorAssistantApplyResponse,
    EditorAssistantChoiceResponse,
    EditorAssistantFailure,
    EditorAssistantFailureCode,
    EditorAssistantPatchOperation,
    EditorAssistantPatchOption,
    EditorAssistantPreviewRequest,
    EditorAssistantPreviewResponse,
    EditorAssistantProvenance,
    EditorAssistantSourceProjection,
    EditorAssistantSourceReference,
    EditorAssistantValidationIssue,
    EditorAssistantValidationReport,
    EditorIntent,
    EditorPatchPath,
    EditorPreviewState,
    EditorValidationStatus,
    editor_assistant_failure_contract,
)
from app.modules.editor_assistant.taxonomy import EditorQualityIssueLabel

REQUEST_KEY = UUID("11111111-1111-4111-8111-111111111111")
PREVIEW_KEY = UUID("22222222-2222-4222-8222-222222222222")
REQUEST_ID = UUID("33333333-3333-4333-8333-333333333333")
PREVIEW_ID = UUID("44444444-4444-4444-8444-444444444444")
QUESTION_ID = UUID("55555555-5555-4555-8555-555555555555")
CHOICE_IDS = (
    UUID("66666666-6666-4666-8666-666666666666"),
    UUID("77777777-7777-4777-8777-777777777777"),
)
SNAPSHOT_TOKEN = "snapshot_Q0FOT05JQ0FMX1Yx"


def _preview_request_payload() -> dict[str, object]:
    return {
        "request_key": str(REQUEST_KEY),
        "preview_key": str(PREVIEW_KEY),
        "intent": "add_context",
        "instruction": "  Добавьте контекст, не меняя правильный ответ.  ",
    }


def _source_projection() -> EditorAssistantSourceProjection:
    return EditorAssistantSourceProjection(
        source_reference_count=1,
        references=(
            EditorAssistantSourceReference(
                source_id="source_79cc5694bc6546af",
                document_title="Правила обслуживания клиентов",
                locator="с. 4, раздел 2",
            ),
        ),
    )


def _provenance() -> EditorAssistantProvenance:
    return EditorAssistantProvenance(
        prompt_version="question-preview-v1",
        generator_version="editor-assistant-step4-v1",
        validator_version="question-validator-v1",
    )


def _validation(
    status: EditorValidationStatus = EditorValidationStatus.PASS,
) -> EditorAssistantValidationReport:
    if status is EditorValidationStatus.PASS:
        return EditorAssistantValidationReport(status=status, issues=())
    if status is EditorValidationStatus.WARN:
        return EditorAssistantValidationReport(
            status=status,
            issues=(
                EditorAssistantValidationIssue(
                    code="provider_output_invalid",
                    message="Предложение не прошло проверку качества.",
                    blocking=False,
                    field_path="question.answer_options",
                ),
            ),
        )
    return EditorAssistantValidationReport(
        status=status,
        issues=(
            EditorAssistantValidationIssue(
                code="protected_field",
                message="Предложение изменяет защищённое поле.",
                blocking=True,
                field_path="question.answer_options",
            ),
        ),
    )


def _text_operation() -> EditorAssistantPatchOperation:
    return EditorAssistantPatchOperation(
        operation="replace",
        field_path="question.text",
        before_value="Когда сотрудник должен отозвать доступ?",
        after_value="В какой момент после увольнения сотрудника необходимо отозвать доступ?",
    )


def _completed_preview(
    *,
    applicability: EditorApplicability = EditorApplicability.APPLICABLE,
    validation: EditorAssistantValidationReport | None = None,
) -> EditorAssistantPreviewResponse:
    return EditorAssistantPreviewResponse(
        request_id=REQUEST_ID,
        preview_id=PREVIEW_ID,
        state="completed",
        applicability=applicability,
        base_snapshot_token=SNAPSHOT_TOKEN,
        operations=(_text_operation(),),
        validation=validation or _validation(),
        source=_source_projection(),
        provenance=_provenance(),
    )


def _choice(choice_id: UUID, text: str, *, correct: bool) -> EditorAssistantChoiceResponse:
    return EditorAssistantChoiceResponse(
        choice_id=choice_id,
        text=text,
        is_correct=correct,
    )


def test_preview_request_is_a_closed_content_free_command() -> None:
    request = EditorAssistantPreviewRequest.model_validate(_preview_request_payload())

    assert request.request_key == REQUEST_KEY
    assert request.preview_key == PREVIEW_KEY
    assert request.intent is EditorIntent.ADD_CONTEXT
    assert request.instruction == "Добавьте контекст, не меняя правильный ответ."
    assert request.model_dump(mode="json") == {
        "request_key": str(REQUEST_KEY),
        "preview_key": str(PREVIEW_KEY),
        "intent": "add_context",
        "instruction": "Добавьте контекст, не меняя правильный ответ.",
    }


@pytest.mark.parametrize(
    "field,value",
    (
        ("tenant_id", "88888888-8888-4888-8888-888888888888"),
        ("actor_id", "99999999-9999-4999-8999-999999999999"),
        ("source_excerpts", ["private source text"]),
        ("correct_answer_flags", [True, False]),
        ("provider", "internal-provider"),
        ("model", "internal-model"),
        ("raw_prompt", "private prompt"),
        ("raw_response", "private response"),
        ("selected_scope", "question.text"),
        ("question_id", str(QUESTION_ID)),
        ("base_snapshot_token", SNAPSHOT_TOKEN),
    ),
)
def test_preview_request_rejects_client_authored_context(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        EditorAssistantPreviewRequest.model_validate(
            {**_preview_request_payload(), field: value}
        )


@pytest.mark.parametrize(
    "override",
    (
        {"intent": "other"},
        {"request_key": "request-1"},
        {"preview_key": "preview-1"},
        {"instruction": "x" * 8_001},
        {"instruction": "   "},
    ),
)
def test_preview_request_rejects_values_outside_the_frozen_contract(
    override: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        EditorAssistantPreviewRequest.model_validate(
            {**_preview_request_payload(), **override}
        )


def test_patch_operations_are_replace_only_and_path_typed() -> None:
    option_operation = EditorAssistantPatchOperation(
        operation="replace",
        field_path="question.answer_options",
        before_value=(
            EditorAssistantPatchOption(
                choice_id=CHOICE_IDS[0], text="Сразу", is_correct=True
            ),
            EditorAssistantPatchOption(
                choice_id=CHOICE_IDS[1], text="Через месяц", is_correct=False
            ),
        ),
        after_value=(
            EditorAssistantPatchOption(
                choice_id=CHOICE_IDS[0], text="Сразу", is_correct=True
            ),
            EditorAssistantPatchOption(
                choice_id=CHOICE_IDS[1],
                text="После следующей плановой проверки доступа",
                is_correct=False,
            ),
        ),
    )
    assert option_operation.field_path is EditorPatchPath.ANSWER_OPTIONS
    assert option_operation.model_dump(mode="json")["operation"] == "replace"

    for payload in (
        {**_text_operation().model_dump(mode="json"), "operation": "append"},
        {**_text_operation().model_dump(mode="json"), "field_path": "question.points"},
        {**_text_operation().model_dump(mode="json"), "after_value": {"raw": "x"}},
        {
            **option_operation.model_dump(mode="json"),
            "after_value": [
                {"choice_id": str(CHOICE_IDS[0]), "text": "x" * 1_201, "is_correct": True},
                {"choice_id": str(CHOICE_IDS[1]), "text": "Допустимо", "is_correct": False},
            ],
        },
    ):
        with pytest.raises(ValidationError):
            EditorAssistantPatchOperation.model_validate(payload)


def test_preview_rejects_duplicate_or_more_than_three_operation_paths() -> None:
    base = _completed_preview().model_dump(mode="json")
    duplicate = _text_operation().model_copy(
        update={"after_value": "Другая формулировка"}
    )
    with pytest.raises(ValidationError):
        EditorAssistantPreviewResponse.model_validate(
            {**base, "operations": [_text_operation(), duplicate]}
        )

    four_operations = [
        _text_operation().model_dump(mode="json"),
        {
            "operation": "replace",
            "field_path": "question.explanation",
            "before_value": None,
            "after_value": "Пояснение",
        },
        {
            "operation": "replace",
            "field_path": "question.answer_options",
            "before_value": [
                {"choice_id": str(CHOICE_IDS[0]), "text": "A", "is_correct": True},
                {"choice_id": str(CHOICE_IDS[1]), "text": "B", "is_correct": False},
            ],
            "after_value": [
                {"choice_id": str(CHOICE_IDS[0]), "text": "A", "is_correct": True},
                {"choice_id": str(CHOICE_IDS[1]), "text": "C", "is_correct": False},
            ],
        },
        _text_operation().model_dump(mode="json"),
    ]
    with pytest.raises(ValidationError):
        EditorAssistantPreviewResponse.model_validate(
            {**base, "operations": four_operations}
        )


def test_source_projection_is_bounded_and_never_contains_excerpts() -> None:
    source = _source_projection()
    assert source.source_reference_count == len(source.references) == 1
    assert "Правила обслуживания" in source.model_dump_json()

    with pytest.raises(ValidationError):
        EditorAssistantSourceReference.model_validate(
            {
                **source.references[0].model_dump(mode="json"),
                "excerpt": "raw source content",
            }
        )
    with pytest.raises(ValidationError):
        EditorAssistantSourceProjection(
            source_reference_count=2,
            references=source.references,
        )
    with pytest.raises(ValidationError):
        EditorAssistantSourceProjection(
            source_reference_count=9,
            references=tuple(
                EditorAssistantSourceReference(
                    source_id=f"source_{index:016x}",
                    document_title=f"Документ {index}",
                    locator="с. 1",
                )
                for index in range(9)
            ),
        )


def test_provenance_exposes_versions_but_not_provider_routing() -> None:
    provenance = _provenance()
    assert provenance.model_dump(mode="json") == {
        "prompt_version": "question-preview-v1",
        "generator_version": "editor-assistant-step4-v1",
        "validator_version": "question-validator-v1",
    }
    for field in ("provider", "model", "model_id", "chain"):
        with pytest.raises(ValidationError):
            EditorAssistantProvenance.model_validate(
                {**provenance.model_dump(mode="json"), field: "internal"}
            )


def test_validation_issues_use_closed_codes_messages_and_consistent_status() -> None:
    warning = _validation(EditorValidationStatus.WARN)
    assert warning.issues[0].message == "Предложение не прошло проверку качества."

    with pytest.raises(ValidationError):
        EditorAssistantValidationIssue(
            code="out_of_scope",
            message="Arbitrary reflected detail",
            blocking=True,
            field_path="question.text",
        )
    with pytest.raises(ValidationError):
        EditorAssistantValidationIssue(
            code="unknown_issue",
            message="Неизвестная ошибка",
            blocking=True,
            field_path="question.text",
        )
    with pytest.raises(ValidationError):
        EditorAssistantValidationReport(status="pass", issues=warning.issues)
    with pytest.raises(ValidationError):
        EditorAssistantValidationReport(status="warn", issues=())
    with pytest.raises(ValidationError):
        EditorAssistantValidationReport(
            status="fail",
            issues=(warning.issues[0],),
        )
    with pytest.raises(ValidationError):
        EditorAssistantValidationReport(
            status="warn",
            issues=tuple(warning.issues[0] for _ in range(21)),
        )


@pytest.mark.parametrize(
    "code,message",
    (
        (
            "correct_answer_length_signal",
            "Длина правильного ответа заметно отличается от вариантов.",
        ),
        (
            "rote_recall_only",
            "Вопрос похож на проверку запоминания без применения знаний.",
        ),
    ),
)
def test_step3_quality_warnings_serialize_with_fixed_messages(
    code: str,
    message: str,
) -> None:
    issue = EditorAssistantValidationIssue(
        code=code,
        message=message,
        blocking=False,
        field_path="question.text",
    )
    report = EditorAssistantValidationReport(status="warn", issues=(issue,))

    assert issue.code is EditorQualityIssueLabel(code)
    assert report.model_dump(mode="json") == {
        "status": "warn",
        "issues": [
            {
                "code": code,
                "message": message,
                "blocking": False,
                "field_path": "question.text",
            }
        ],
    }


@pytest.mark.parametrize(
    "code,message,path",
    (
        (
            "unsupported_correct_answer",
            "Правильный ответ не подтверждён разрешённым источником.",
            "question.answer_options",
        ),
        (
            "multiple_plausible_correct_answers",
            "Несколько вариантов отмечены как потенциально правильные по явному сигналу.",
            "question.answer_options",
        ),
        (
            "malformed_question",
            "Вопрос или варианты ответа составлены некорректно.",
            "question.text",
        ),
    ),
)
def test_step3_quality_blockers_serialize_with_fixed_messages(
    code: str,
    message: str,
    path: str,
) -> None:
    issue = EditorAssistantValidationIssue(
        code=code,
        message=message,
        blocking=True,
        field_path=path,
    )
    report = EditorAssistantValidationReport(status="fail", issues=(issue,))

    assert report.status is EditorValidationStatus.FAIL
    assert report.issues[0].code is EditorQualityIssueLabel(code)
    assert report.issues[0].message == message


def test_quality_severity_is_report_data_and_other_remains_only_an_issue_code() -> None:
    message = "Длина правильного ответа заметно отличается от вариантов."
    warning = EditorAssistantValidationIssue(
        code="correct_answer_length_signal",
        message=message,
        blocking=False,
        field_path="question.answer_options",
    )
    blocker = EditorAssistantValidationIssue(
        code="correct_answer_length_signal",
        message=message,
        blocking=True,
        field_path="question.answer_options",
    )
    other = EditorAssistantValidationIssue(
        code="other",
        message="Найдена дополнительная проблема качества.",
        blocking=False,
        field_path="question.text",
    )

    assert EditorAssistantValidationReport(status="warn", issues=(warning,)).status == "warn"
    assert EditorAssistantValidationReport(status="fail", issues=(blocker,)).status == "fail"
    assert other.code is EditorQualityIssueLabel.OTHER
    with pytest.raises(ValidationError):
        EditorAssistantPreviewRequest.model_validate(
            {**_preview_request_payload(), "intent": "other"}
        )


def test_quality_projection_rejects_internal_paths_unknown_codes_and_provider_metadata() -> None:
    for internal_path in (
        "questions[0].prompt",
        "questions[0].options[1]",
        "questions[*].options",
    ):
        with pytest.raises(ValidationError):
            EditorAssistantValidationIssue(
                code="rote_recall_only",
                message="Вопрос похож на проверку запоминания без применения знаний.",
                blocking=False,
                field_path=internal_path,
            )

    with pytest.raises(ValidationError):
        EditorAssistantValidationIssue(
            code="unknown_quality_signal",
            message="Неизвестная проблема",
            blocking=False,
            field_path="question.text",
        )

    report = EditorAssistantValidationReport(
        status="warn",
        issues=(
            EditorAssistantValidationIssue(
                code="rote_recall_only",
                message="Вопрос похож на проверку запоминания без применения знаний.",
                blocking=False,
                field_path="question.text",
            ),
        ),
    )
    with pytest.raises(ValidationError):
        EditorAssistantValidationReport.model_validate(
            {**report.model_dump(mode="json"), "provider": "internal-provider"}
        )


def test_preview_state_controls_patch_failure_and_applicability_shapes() -> None:
    pending = EditorAssistantPreviewResponse(
        request_id=REQUEST_ID,
        preview_id=PREVIEW_ID,
        state="pending",
        applicability="not_applicable",
        base_snapshot_token=SNAPSHOT_TOKEN,
        source=EditorAssistantSourceProjection(
            source_reference_count=0,
            references=(),
        ),
    )
    assert pending.operations == ()
    assert pending.failure is None

    completed = _completed_preview()
    assert completed.state is EditorPreviewState.COMPLETED
    assert completed.applicability is EditorApplicability.APPLICABLE
    assert completed.operations
    assert completed.source.source_reference_count == 1
    assert completed.model_dump_json() == completed.model_dump_json()

    warning = _completed_preview(
        applicability=EditorApplicability.APPLICABLE_WITH_WARNINGS,
        validation=_validation(EditorValidationStatus.WARN),
    )
    assert warning.validation is not None
    assert warning.validation.status is EditorValidationStatus.WARN

    failed = EditorAssistantPreviewResponse(
        request_id=REQUEST_ID,
        preview_id=PREVIEW_ID,
        state="failed",
        applicability="requires_new_draft_revision",
        base_snapshot_token=SNAPSHOT_TOKEN,
        source=EditorAssistantSourceProjection(
            source_reference_count=0,
            references=(),
        ),
        failure=EditorAssistantFailure(
            error_code="requires_new_draft_revision",
            message="Для опубликованного курса требуется новая черновая версия.",
        ),
    )
    assert failed.operations == ()
    assert failed.failure is not None

    invalid_payloads = (
        {**pending.model_dump(mode="json"), "operations": [_text_operation()]},
        {**completed.model_dump(mode="json"), "operations": []},
        {**completed.model_dump(mode="json"), "state": "pending"},
        {
            **completed.model_dump(mode="json"),
            "applicability": "applicable_with_warnings",
        },
        {
            **failed.model_dump(mode="json"),
            "operations": [_text_operation()],
        },
        {**failed.model_dump(mode="json"), "failure": None},
    )
    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            EditorAssistantPreviewResponse.model_validate(payload)


def test_failure_catalog_rejects_arbitrary_details_and_message_mismatch() -> None:
    message, applicability = editor_assistant_failure_contract(
        EditorAssistantFailureCode.PROVIDER_TIMEOUT
    )
    failure = EditorAssistantFailure(
        error_code=EditorAssistantFailureCode.PROVIDER_TIMEOUT,
        message=message,
    )
    assert applicability is EditorApplicability.NOT_APPLICABLE
    assert failure.model_dump(mode="json") == {
        "error_code": "provider_timeout",
        "message": "Сервис генерации не ответил вовремя.",
    }
    with pytest.raises(ValidationError):
        EditorAssistantFailure(
            error_code="provider_timeout",
            message="Internal timeout at provider model X",
        )
    with pytest.raises(ValidationError):
        EditorAssistantFailure.model_validate(
            {**failure.model_dump(mode="json"), "detail": "raw provider output"}
        )


@pytest.mark.parametrize(
    ("code", "expected_message", "expected_applicability"),
    (
        (
            EditorAssistantFailureCode.PROVIDER_TIMEOUT,
            "Сервис генерации не ответил вовремя.",
            EditorApplicability.NOT_APPLICABLE,
        ),
        (
            EditorAssistantFailureCode.PROVIDER_UNAVAILABLE,
            "Сервис генерации временно недоступен.",
            EditorApplicability.NOT_APPLICABLE,
        ),
        (
            EditorAssistantFailureCode.PROVIDER_OUTPUT_UNPARSEABLE,
            "Не удалось обработать ответ сервиса генерации.",
            EditorApplicability.NOT_APPLICABLE,
        ),
        (
            EditorAssistantFailureCode.CONTRACT_VIOLATION,
            "Предложение не соответствует требованиям редактора.",
            EditorApplicability.NOT_APPLICABLE,
        ),
        (
            EditorAssistantFailureCode.VALIDATION_BLOCKED,
            "Предложение не прошло проверку качества.",
            EditorApplicability.NOT_APPLICABLE,
        ),
        (
            EditorAssistantFailureCode.STALE_BASE_VERSION,
            "Вопрос был изменён. Обновите данные и повторите запрос.",
            EditorApplicability.STALE,
        ),
        (
            EditorAssistantFailureCode.REJECTED_OUT_OF_SCOPE,
            "Предложение выходит за область выбранного вопроса.",
            EditorApplicability.NOT_APPLICABLE,
        ),
        (
            EditorAssistantFailureCode.SOURCE_EVIDENCE_UNAVAILABLE,
            "Для вопроса недоступны подтверждающие материалы.",
            EditorApplicability.NOT_APPLICABLE,
        ),
        (
            EditorAssistantFailureCode.REQUIRES_NEW_DRAFT_REVISION,
            "Для опубликованного курса требуется новая черновая версия.",
            EditorApplicability.REQUIRES_NEW_DRAFT_REVISION,
        ),
        (
            EditorAssistantFailureCode.INTERNAL_ERROR,
            "Не удалось подготовить предложение.",
            EditorApplicability.NOT_APPLICABLE,
        ),
    ),
)
def test_public_failure_contract_covers_every_closed_code(
    code: EditorAssistantFailureCode,
    expected_message: str,
    expected_applicability: EditorApplicability,
) -> None:
    message, applicability = editor_assistant_failure_contract(code)

    assert message == expected_message
    assert applicability is expected_applicability
    assert EditorAssistantFailure(error_code=code, message=message).message == message


def test_apply_request_contains_only_preview_identity_and_snapshot() -> None:
    request = EditorAssistantApplyRequest(
        preview_id=PREVIEW_ID,
        apply_key=REQUEST_KEY,
        base_snapshot_token=SNAPSHOT_TOKEN,
    )
    assert request.model_dump(mode="json") == {
        "preview_id": str(PREVIEW_ID),
        "apply_key": str(REQUEST_KEY),
        "base_snapshot_token": SNAPSHOT_TOKEN,
    }
    for field in ("operations", "patch", "question", "new_draft_revision_id"):
        with pytest.raises(ValidationError):
            EditorAssistantApplyRequest.model_validate(
                {**request.model_dump(mode="json"), field: []}
            )


def test_apply_response_is_one_persisted_single_correct_question() -> None:
    response = EditorAssistantApplyResponse(
        question_id=QUESTION_ID,
        text="Когда необходимо отозвать доступ сотрудника?",
        explanation="Сразу после прекращения трудовых отношений.",
        options=(
            _choice(CHOICE_IDS[0], "Сразу после увольнения", correct=True),
            _choice(CHOICE_IDS[1], "После плановой проверки", correct=False),
        ),
        persisted_snapshot_token="snapshot_UEVSU0lTVEVEX1Yy",
    )
    assert [choice.choice_id for choice in response.options] == list(CHOICE_IDS)
    assert sum(choice.is_correct for choice in response.options) == 1
    assert response.model_dump(mode="json")["question_id"] == str(QUESTION_ID)

    invalid_options = (
        (
            _choice(CHOICE_IDS[0], "A", correct=True),
            _choice(CHOICE_IDS[0], "B", correct=False),
        ),
        (
            _choice(CHOICE_IDS[0], "A", correct=False),
            _choice(CHOICE_IDS[1], "B", correct=False),
        ),
        (
            _choice(CHOICE_IDS[0], "A", correct=True),
            _choice(CHOICE_IDS[1], "B", correct=True),
        ),
    )
    for options in invalid_options:
        with pytest.raises(ValidationError):
            EditorAssistantApplyResponse(
                question_id=QUESTION_ID,
                text="Вопрос",
                explanation=None,
                options=options,
                persisted_snapshot_token="snapshot_UEVSU0lTVEVEX1Yy",
            )

    with pytest.raises(ValidationError):
        EditorAssistantApplyResponse(
            question_id=QUESTION_ID,
            text="Вопрос",
            explanation=None,
            options=tuple(
                _choice(UUID(int=index + 1), f"Вариант {index}", correct=index == 0)
                for index in range(21)
            ),
            persisted_snapshot_token="snapshot_UEVSU0lTVEVEX1Yy",
        )
