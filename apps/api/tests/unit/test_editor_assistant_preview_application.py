"""Public-seam tests for pure single-question preview orchestration."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from app.modules.ai.llm_client import (
    AllProvidersFailedError,
    ValidatedCallFailureReason,
)
from app.modules.ai.question_preview import (
    PreviewIntent,
    ProviderOutputUnparseableError,
    QuestionPreviewError,
    QuestionPreviewOutcome,
    RejectedOutOfScopeError,
    SourceEvidenceUnavailableError,
    ValidationBlockedError,
)
from app.modules.editor_assistant.patch_contract import (
    PatchApplicabilityStatus,
    PatchOperation,
    PatchOperationType,
    ProviderProvenance,
    StructuredEditPatch,
    ValidationIssue,
    ValidationReport,
    ValidationStatus,
)
from app.modules.editor_assistant.preview_application import (
    create_question_preview_response,
)
from app.modules.editor_assistant.question_context import (
    QuestionChoiceContext,
    QuestionSourceFact,
    QuestionSourceReference,
    ResolvedQuestionContext,
)
from app.modules.editor_assistant.question_validator import (
    AnswerOption,
    Question,
    QuestionSet,
    QuestionSignals,
    SourceSupportSignal,
    validate_question_set,
)
from app.modules.editor_assistant.schemas import (
    EditorApplicability,
    EditorAssistantFailureCode,
    EditorAssistantPreviewRequest,
    EditorIntent,
    EditorPatchPath,
    EditorPreviewState,
    EditorValidationStatus,
)
from app.modules.editor_assistant.taxonomy import EditorQualityIssueLabel

REQUEST_ID = UUID("10000000-0000-4000-8000-000000000001")
PREVIEW_ID = UUID("20000000-0000-4000-8000-000000000002")


def _resolved_context() -> ResolvedQuestionContext:
    choices = (
        QuestionChoiceContext(
            UUID("30000000-0000-4000-8000-000000000001"),
            "Use the approved route",
            True,
            0,
        ),
        QuestionChoiceContext(
            UUID("30000000-0000-4000-8000-000000000002"),
            "Ask an unrelated person",
            False,
            1,
        ),
        QuestionChoiceContext(
            UUID("30000000-0000-4000-8000-000000000003"),
            "Ignore the documented process",
            False,
            2,
        ),
    )
    source_id = UUID("40000000-0000-4000-8000-000000000001")
    return ResolvedQuestionContext(
        tenant_id=UUID("50000000-0000-4000-8000-000000000001"),
        course_id=UUID("60000000-0000-4000-8000-000000000001"),
        module_id=UUID("70000000-0000-4000-8000-000000000001"),
        lesson_id=UUID("80000000-0000-4000-8000-000000000001"),
        quiz_id=UUID("90000000-0000-4000-8000-000000000001"),
        question_id=UUID("a0000000-0000-4000-8000-000000000001"),
        question_type="MCQ",
        question_text="What is the approved access route?",
        choices=choices,
        correct_choice_id=choices[0].choice_id,
        explanation="The documented route is the controlled path.",
        locale="en-US",
        source_references=(
            QuestionSourceReference(
                source_id,
                "Access policy",
                "page-1",
                "b" * 64,
            ),
        ),
        source_facts=(
            QuestionSourceFact(
                "fact-1",
                source_id,
                "The approved route is the documented controlled path.",
                "page-1",
                "b" * 64,
            ),
        ),
        snapshot_fingerprint="a" * 64,
    )


def _request(intent: EditorIntent = EditorIntent.REWRITE_WORDING) -> EditorAssistantPreviewRequest:
    return EditorAssistantPreviewRequest(
        request_key=UUID("b0000000-0000-4000-8000-000000000001"),
        preview_key=UUID("c0000000-0000-4000-8000-000000000001"),
        intent=intent,
        instruction="Make the question clearer.",
    )


def _identity(_request: EditorAssistantPreviewRequest) -> tuple[UUID, UUID]:
    return REQUEST_ID, PREVIEW_ID


def _outcome(
    preview_context,
    *,
    field_path: str = "question.text",
    signals: QuestionSignals | None = None,
    oversized: bool = False,
) -> QuestionPreviewOutcome:
    before = preview_context.question
    prompt = before.prompt
    options = before.options
    explanation = before.explanation
    if field_path == "question.text":
        prompt = "X" * 70_000 if oversized else "Which approved route must an employee use?"
        before_value = before.prompt
        after_value = prompt
    elif field_path == "question.answer_options":
        options = (
            before.options[0],
            AnswerOption("Use an unapproved route", False),
            AnswerOption("Skip the approved route", False),
        )
        before_value = before.options
        after_value = options
    elif field_path == "question.explanation":
        explanation = "The approved route keeps access controlled and auditable."
        before_value = before.explanation
        after_value = explanation
    else:
        before_value = before.prompt
        after_value = "Escaped internal value"
    candidate = Question(
        question_id=before.question_id,
        prompt=prompt if len(prompt) <= 2_000 else before.prompt,
        options=options,
        explanation=explanation,
        signals=signals or before.signals,
    )
    validation = validate_question_set(
        QuestionSet((candidate,), locale=preview_context.command.locale)
    )
    generic_issues = tuple(
        ValidationIssue("provider_output_invalid", finding.blocking)
        for finding in validation.findings
    )
    patch = StructuredEditPatch(
        request_key=preview_context.command.request_key,
        preview_key=preview_context.command.preview_key,
        target=preview_context.command.target,
        base_snapshot=preview_context.command.base_snapshot,
        operations=(
            PatchOperation(
                target=preview_context.command.target,
                field_path=field_path,
                operation=PatchOperationType.REPLACE,
                before_value=before_value,
                after_value=after_value,
            ),
        ),
        source_evidence=tuple(
            evidence.reference for evidence in preview_context.evidence
        ),
        validation_report=ValidationReport(
            ValidationStatus(validation.status.value),
            generic_issues,
            validation.validator_version,
        ),
        provider_provenance=ProviderProvenance(
            "secret-provider",
            "secret-model",
            "question-preview-v1",
            "editor-assistant-step4-v1",
        ),
        applicability_status=PatchApplicabilityStatus.APPLICABLE,
    )
    return QuestionPreviewOutcome(patch, validation)


@pytest.mark.asyncio
async def test_text_preview_returns_completed_public_response() -> None:
    async def adapter(preview_context):
        before = preview_context.question
        after = Question(
            question_id=before.question_id,
            prompt="Which approved access route must an employee use?",
            options=before.options,
            explanation=before.explanation,
        )
        validation = validate_question_set(
            QuestionSet((after,), locale=preview_context.command.locale)
        )
        patch = StructuredEditPatch(
            request_key=preview_context.command.request_key,
            preview_key=preview_context.command.preview_key,
            target=preview_context.command.target,
            base_snapshot=preview_context.command.base_snapshot,
            operations=(
                PatchOperation(
                    target=preview_context.command.target,
                    field_path="question.text",
                    operation=PatchOperationType.REPLACE,
                    before_value=before.prompt,
                    after_value=after.prompt,
                ),
            ),
            source_evidence=tuple(
                evidence.reference for evidence in preview_context.evidence
            ),
            validation_report=ValidationReport(ValidationStatus.PASS),
            provider_provenance=ProviderProvenance(
                "secret-provider",
                "secret-model",
                "question-preview-v1",
                "editor-assistant-step4-v1",
            ),
            applicability_status=PatchApplicabilityStatus.APPLICABLE,
        )
        return QuestionPreviewOutcome(patch, validation)

    response = await create_question_preview_response(
        _resolved_context(),
        _request(),
        adapter,
        _identity,
    )

    assert response.request_id == REQUEST_ID
    assert response.preview_id == PREVIEW_ID
    assert response.state is EditorPreviewState.COMPLETED
    assert response.operations[0].field_path is EditorPatchPath.TEXT
    assert response.operations[0].after_value == (
        "Which approved access route must an employee use?"
    )
    serialized = response.model_dump_json()
    assert "secret-provider" not in serialized
    assert "secret-model" not in serialized
    assert "The approved route is the documented controlled path." not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("public_intent", "adapter_intent", "selected_scope", "patch_path"),
    (
        (
            EditorIntent.REWRITE_WORDING,
            PreviewIntent.WORDING,
            "question.text",
            "question.text",
        ),
        (
            EditorIntent.SIMPLIFY_LANGUAGE,
            PreviewIntent.WORDING,
            "question.text",
            "question.text",
        ),
        (
            EditorIntent.ADD_CONTEXT,
            PreviewIntent.ADD_CONTEXT,
            "question.text",
            "question.text",
        ),
        (
            EditorIntent.REGENERATE_DISTRACTORS,
            PreviewIntent.DISTRACTORS,
            "question.answer_options",
            "question.answer_options",
        ),
        (
            EditorIntent.BALANCE_ANSWER_LENGTH,
            PreviewIntent.ANSWER_BALANCE,
            "question.answer_options",
            "question.answer_options",
        ),
        (
            EditorIntent.CHANGE_DIFFICULTY,
            PreviewIntent.DIFFICULTY,
            "question",
            "question.text",
        ),
        (
            EditorIntent.MAKE_SCENARIO_BASED,
            PreviewIntent.SCENARIO,
            "question",
            "question.text",
        ),
        (
            EditorIntent.ADD_OR_REWRITE_EXPLANATION,
            PreviewIntent.EXPLANATION,
            "question.explanation",
            "question.explanation",
        ),
        (
            EditorIntent.FIX_SOURCE_GROUNDING,
            PreviewIntent.SOURCE_VERIFICATION,
            "question",
            "question.text",
        ),
    ),
)
async def test_each_public_intent_maps_explicitly_to_step4_contract(
    public_intent: EditorIntent,
    adapter_intent: PreviewIntent,
    selected_scope: str,
    patch_path: str,
) -> None:
    async def adapter(preview_context):
        assert preview_context.intent is adapter_intent
        assert preview_context.command.target.selected_scope == selected_scope
        return _outcome(preview_context, field_path=patch_path)

    response = await create_question_preview_response(
        _resolved_context(),
        _request(public_intent),
        adapter,
        _identity,
    )

    assert response.state is EditorPreviewState.COMPLETED


@pytest.mark.asyncio
async def test_answer_option_patch_preserves_ids_order_and_correct_answer() -> None:
    async def adapter(preview_context):
        return _outcome(preview_context, field_path="question.answer_options")

    context = _resolved_context()
    response = await create_question_preview_response(
        context,
        _request(EditorIntent.REGENERATE_DISTRACTORS),
        adapter,
        _identity,
    )

    operation = response.operations[0]
    assert operation.field_path is EditorPatchPath.ANSWER_OPTIONS
    assert tuple(option.choice_id for option in operation.after_value) == tuple(
        choice.choice_id for choice in context.choices
    )
    assert tuple(option.is_correct for option in operation.after_value) == (
        True,
        False,
        False,
    )
    assert operation.after_value[0].text == context.choices[0].text


@pytest.mark.asyncio
async def test_explanation_patch_preserves_explanation_boundary() -> None:
    async def adapter(preview_context):
        return _outcome(preview_context, field_path="question.explanation")

    response = await create_question_preview_response(
        _resolved_context(),
        _request(EditorIntent.ADD_OR_REWRITE_EXPLANATION),
        adapter,
        _identity,
    )

    operation = response.operations[0]
    assert operation.field_path is EditorPatchPath.EXPLANATION
    assert operation.before_value == "The documented route is the controlled path."
    assert operation.after_value == (
        "The approved route keeps access controlled and auditable."
    )


@pytest.mark.asyncio
async def test_warning_projects_real_quality_label_and_completes() -> None:
    async def adapter(preview_context):
        return _outcome(
            preview_context,
            signals=QuestionSignals(explicit_implausible_distractor_indices=(1,)),
        )

    response = await create_question_preview_response(
        _resolved_context(),
        _request(),
        adapter,
        _identity,
    )

    assert response.state is EditorPreviewState.COMPLETED
    assert response.applicability is EditorApplicability.APPLICABLE_WITH_WARNINGS
    assert response.validation.status is EditorValidationStatus.WARN
    assert response.validation.issues[0].code is (
        EditorQualityIssueLabel.IMPLAUSIBLE_DISTRACTORS
    )


@pytest.mark.asyncio
async def test_blocking_validation_fails_closed_without_patch() -> None:
    async def adapter(preview_context):
        return _outcome(
            preview_context,
            signals=QuestionSignals(source_support=SourceSupportSignal.UNSUPPORTED),
        )

    response = await create_question_preview_response(
        _resolved_context(),
        _request(),
        adapter,
        _identity,
    )

    assert response.state is EditorPreviewState.FAILED
    assert response.operations == ()
    assert response.validation is None
    assert response.failure.error_code is EditorAssistantFailureCode.VALIDATION_BLOCKED


@pytest.mark.asyncio
async def test_source_projection_exposes_references_but_not_source_facts() -> None:
    async def adapter(preview_context):
        return _outcome(preview_context)

    request = _request()
    response = await create_question_preview_response(
        _resolved_context(),
        request,
        adapter,
        _identity,
    )

    assert response.source.references[0].document_title == "Access policy"
    assert response.source.references[0].locator == "page-1"
    serialized = response.model_dump_json()
    assert request.instruction not in serialized
    assert "fact-1" not in serialized
    assert "documented controlled path" not in serialized
    assert "secret-provider" not in serialized
    assert "secret-model" not in serialized
    assert "tenant_id" not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_code"),
    (
        (TimeoutError("private timeout detail"), EditorAssistantFailureCode.PROVIDER_TIMEOUT),
        (
            AllProvidersFailedError("private provider detail"),
            EditorAssistantFailureCode.PROVIDER_UNAVAILABLE,
        ),
        (
            ProviderOutputUnparseableError("private parser detail"),
            EditorAssistantFailureCode.PROVIDER_OUTPUT_UNPARSEABLE,
        ),
        (
            QuestionPreviewError("private contract detail"),
            EditorAssistantFailureCode.CONTRACT_VIOLATION,
        ),
        (
            RejectedOutOfScopeError("private scope detail"),
            EditorAssistantFailureCode.REJECTED_OUT_OF_SCOPE,
        ),
        (
            SourceEvidenceUnavailableError("private source detail"),
            EditorAssistantFailureCode.SOURCE_EVIDENCE_UNAVAILABLE,
        ),
        (
            ValidationBlockedError("private validation detail"),
            EditorAssistantFailureCode.VALIDATION_BLOCKED,
        ),
    ),
)
async def test_adapter_failures_map_to_closed_public_catalog(
    error: Exception,
    expected_code: EditorAssistantFailureCode,
) -> None:
    async def adapter(_preview_context):
        raise error

    response = await create_question_preview_response(
        _resolved_context(),
        _request(),
        adapter,
        _identity,
    )

    assert response.state is EditorPreviewState.FAILED
    assert response.failure.error_code is expected_code
    assert "private" not in response.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reasons", "expected_code"),
    (
        (
            (
                ValidatedCallFailureReason.PROVIDER_TIMEOUT,
                ValidatedCallFailureReason.PROVIDER_TIMEOUT,
            ),
            EditorAssistantFailureCode.PROVIDER_TIMEOUT,
        ),
        (
            (
                ValidatedCallFailureReason.PROVIDER_TIMEOUT,
                ValidatedCallFailureReason.PROVIDER_UNAVAILABLE,
            ),
            EditorAssistantFailureCode.PROVIDER_UNAVAILABLE,
        ),
        (
            (
                ValidatedCallFailureReason.PROVIDER_TIMEOUT,
                ValidatedCallFailureReason.VALIDATION_BLOCKED,
                ValidatedCallFailureReason.PROVIDER_UNAVAILABLE,
            ),
            EditorAssistantFailureCode.VALIDATION_BLOCKED,
        ),
        (
            (
                ValidatedCallFailureReason.PROVIDER_OUTPUT_UNPARSEABLE,
                ValidatedCallFailureReason.PROVIDER_TIMEOUT,
            ),
            EditorAssistantFailureCode.PROVIDER_OUTPUT_UNPARSEABLE,
        ),
        (
            (
                ValidatedCallFailureReason.PROVIDER_OUTPUT_UNPARSEABLE,
                ValidatedCallFailureReason.REJECTED_OUT_OF_SCOPE,
            ),
            EditorAssistantFailureCode.CONTRACT_VIOLATION,
        ),
        ((), EditorAssistantFailureCode.PROVIDER_UNAVAILABLE),
    ),
)
async def test_typed_failover_reasons_reduce_deterministically(
    reasons: tuple[ValidatedCallFailureReason, ...],
    expected_code: EditorAssistantFailureCode,
) -> None:
    async def adapter(_preview_context):
        raise AllProvidersFailedError("PRIVATE failover exception text", reasons)

    response = await create_question_preview_response(
        _resolved_context(),
        _request(),
        adapter,
        _identity,
    )

    assert response.failure.error_code is expected_code
    serialized = response.model_dump_json()
    assert "PRIVATE" not in serialized
    assert "failover exception text" not in serialized


@pytest.mark.asyncio
async def test_malformed_direct_typed_reason_fails_closed() -> None:
    class MalformedTypedPreviewError(QuestionPreviewError):
        validated_failure_reason = "not-a-validated-reason"

    async def adapter(_preview_context):
        raise MalformedTypedPreviewError("PRIVATE malformed reason text")

    response = await create_question_preview_response(
        _resolved_context(),
        _request(),
        adapter,
        _identity,
    )

    assert response.failure.error_code is EditorAssistantFailureCode.CONTRACT_VIOLATION
    assert "PRIVATE" not in response.model_dump_json()


@pytest.mark.asyncio
async def test_unknown_exception_is_sanitized_as_internal_error() -> None:
    async def adapter(_preview_context):
        raise RuntimeError("SECRET arbitrary exception text")

    response = await create_question_preview_response(
        _resolved_context(),
        _request(),
        adapter,
        _identity,
    )

    assert response.failure.error_code is EditorAssistantFailureCode.INTERNAL_ERROR
    assert "SECRET" not in response.model_dump_json()


@pytest.mark.asyncio
async def test_snapshot_token_is_deterministic_opaque_and_context_bound() -> None:
    async def adapter(preview_context):
        return _outcome(preview_context)

    context = _resolved_context()
    first = await create_question_preview_response(
        context,
        _request(),
        adapter,
        _identity,
    )
    second = await create_question_preview_response(
        context,
        _request(),
        adapter,
        _identity,
    )
    changed = await create_question_preview_response(
        replace(context, snapshot_fingerprint="d" * 64),
        _request(),
        adapter,
        _identity,
    )

    assert first.base_snapshot_token == second.base_snapshot_token
    assert first.base_snapshot_token != context.snapshot_fingerprint
    assert first.base_snapshot_token != changed.base_snapshot_token
    assert len(first.base_snapshot_token) == 64


@pytest.mark.asyncio
async def test_oversized_adapter_output_fails_closed_under_dto_limit() -> None:
    async def adapter(preview_context):
        return _outcome(preview_context, oversized=True)

    response = await create_question_preview_response(
        _resolved_context(),
        _request(),
        adapter,
        _identity,
    )

    assert response.state is EditorPreviewState.FAILED
    assert response.operations == ()
    assert response.failure.error_code is EditorAssistantFailureCode.INTERNAL_ERROR
    assert len(response.model_dump_json().encode("utf-8")) < 65_536


@pytest.mark.asyncio
async def test_noncanonical_internal_patch_path_is_rejected() -> None:
    async def adapter(preview_context):
        return _outcome(preview_context, field_path="question.internal_text")

    response = await create_question_preview_response(
        _resolved_context(),
        _request(),
        adapter,
        _identity,
    )

    assert response.state is EditorPreviewState.FAILED
    assert response.failure.error_code is EditorAssistantFailureCode.REJECTED_OUT_OF_SCOPE
