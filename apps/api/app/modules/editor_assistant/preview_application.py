"""Pure application orchestration for one methodologist question preview.

The module consumes a trusted, already-resolved question context and an
injected Step 4 adapter. It performs no authentication, database access,
persistence, telemetry, provider selection, or content mutation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable
from typing import Protocol
from uuid import UUID

import httpx

from app.modules.ai.llm_client import (
    AllProvidersFailedError,
    ProviderFailedError,
    ValidatedCallFailureReason,
)
from app.modules.ai.question_preview import (
    PreviewIntent,
    QuestionPreviewContext,
    QuestionPreviewError,
    QuestionPreviewOutcome,
    SourceEvidenceExcerpt,
)

from .patch_contract import (
    ContentLifecycle,
    ContentVersionSnapshot,
    EditorTarget,
    EditorTargetEntityType,
    OperationConstraints,
    PatchApplicabilityStatus,
    PatchContractError,
    PatchOperationType,
    SourceEvidenceReference,
    StaleBaseVersionError,
    StructuredEditCommand,
)
from .question_context import ResolvedQuestionContext
from .question_validator import (
    AnswerOption,
    Question,
    QuestionSignals,
    SourceSupportSignal,
)
from .schemas import (
    EditorApplicability,
    EditorAssistantFailure,
    EditorAssistantFailureCode,
    EditorAssistantPatchOperation,
    EditorAssistantPatchOption,
    EditorAssistantPreviewRequest,
    EditorAssistantPreviewResponse,
    EditorAssistantProvenance,
    EditorAssistantSourceProjection,
    EditorAssistantSourceReference,
    EditorIntent,
    EditorPatchPath,
    EditorPreviewState,
    EditorValidationStatus,
    editor_assistant_failure_contract,
)
from .validation_projection import project_validation_report


class QuestionPreviewAdapter(Protocol):
    """Injected offline-testable boundary around the Step 4 adapter."""

    def __call__(
        self,
        context: QuestionPreviewContext,
    ) -> Awaitable[QuestionPreviewOutcome]: ...


class PreviewIdentityFactory(Protocol):
    """Supply non-persisted identities for one preview response."""

    def __call__(
        self,
        request: EditorAssistantPreviewRequest,
    ) -> tuple[UUID, UUID]: ...


_IntentContract = tuple[PreviewIntent, str, tuple[str, ...]]
_ALL_PUBLIC_PATHS = (
    EditorPatchPath.TEXT.value,
    EditorPatchPath.ANSWER_OPTIONS.value,
    EditorPatchPath.EXPLANATION.value,
)
_INTENT_CONTRACTS: dict[EditorIntent, _IntentContract] = {
    EditorIntent.REWRITE_WORDING: (
        PreviewIntent.WORDING,
        EditorPatchPath.TEXT.value,
        (EditorPatchPath.TEXT.value,),
    ),
    EditorIntent.SIMPLIFY_LANGUAGE: (
        PreviewIntent.WORDING,
        EditorPatchPath.TEXT.value,
        (EditorPatchPath.TEXT.value,),
    ),
    EditorIntent.ADD_CONTEXT: (
        PreviewIntent.ADD_CONTEXT,
        EditorPatchPath.TEXT.value,
        (EditorPatchPath.TEXT.value,),
    ),
    EditorIntent.REGENERATE_DISTRACTORS: (
        PreviewIntent.DISTRACTORS,
        EditorPatchPath.ANSWER_OPTIONS.value,
        (EditorPatchPath.ANSWER_OPTIONS.value,),
    ),
    EditorIntent.BALANCE_ANSWER_LENGTH: (
        PreviewIntent.ANSWER_BALANCE,
        EditorPatchPath.ANSWER_OPTIONS.value,
        (EditorPatchPath.ANSWER_OPTIONS.value,),
    ),
    EditorIntent.CHANGE_DIFFICULTY: (
        PreviewIntent.DIFFICULTY,
        "question",
        (EditorPatchPath.TEXT.value, EditorPatchPath.ANSWER_OPTIONS.value),
    ),
    EditorIntent.MAKE_SCENARIO_BASED: (
        PreviewIntent.SCENARIO,
        "question",
        (EditorPatchPath.TEXT.value, EditorPatchPath.ANSWER_OPTIONS.value),
    ),
    EditorIntent.ADD_OR_REWRITE_EXPLANATION: (
        PreviewIntent.EXPLANATION,
        EditorPatchPath.EXPLANATION.value,
        (EditorPatchPath.EXPLANATION.value,),
    ),
    EditorIntent.FIX_SOURCE_GROUNDING: (
        PreviewIntent.SOURCE_VERIFICATION,
        "question",
        _ALL_PUBLIC_PATHS,
    ),
}

_TRANSPORT_FAILURE_REASONS = frozenset(
    {
        ValidatedCallFailureReason.PROVIDER_TIMEOUT,
        ValidatedCallFailureReason.PROVIDER_UNAVAILABLE,
    }
)


class _ApplicationFailure(ValueError):  # noqa: N818 - bounded application outcome
    def __init__(self, code: EditorAssistantFailureCode) -> None:
        self.code = code
        message, _ = editor_assistant_failure_contract(code)
        super().__init__(message)


def _snapshot_token(fingerprint: object) -> str:
    value = fingerprint if isinstance(fingerprint, str) else "invalid"
    return hashlib.sha256(
        f"kamilya-question-preview-v1:{value}".encode()
    ).hexdigest()


def _validated_reason_code(reason: object) -> EditorAssistantFailureCode:
    try:
        normalized = ValidatedCallFailureReason(reason)
        return EditorAssistantFailureCode(normalized.value)
    except (TypeError, ValueError):
        return EditorAssistantFailureCode.CONTRACT_VIOLATION


def _all_providers_failure_code(
    error: AllProvidersFailedError,
) -> EditorAssistantFailureCode:
    if not error.reasons:
        return EditorAssistantFailureCode.PROVIDER_UNAVAILABLE
    try:
        reasons = tuple(ValidatedCallFailureReason(reason) for reason in error.reasons)
    except (TypeError, ValueError):
        return EditorAssistantFailureCode.CONTRACT_VIOLATION
    non_transport_reasons = {
        reason for reason in reasons if reason not in _TRANSPORT_FAILURE_REASONS
    }
    if len(non_transport_reasons) > 1:
        return EditorAssistantFailureCode.CONTRACT_VIOLATION
    if len(non_transport_reasons) == 1:
        return _validated_reason_code(next(iter(non_transport_reasons)))
    if all(
        reason is ValidatedCallFailureReason.PROVIDER_TIMEOUT for reason in reasons
    ):
        return EditorAssistantFailureCode.PROVIDER_TIMEOUT
    if any(
        reason is ValidatedCallFailureReason.PROVIDER_UNAVAILABLE
        for reason in reasons
    ):
        return EditorAssistantFailureCode.PROVIDER_UNAVAILABLE
    return EditorAssistantFailureCode.CONTRACT_VIOLATION


def _failure_code(error: Exception) -> EditorAssistantFailureCode:
    if isinstance(error, _ApplicationFailure):
        return error.code
    if isinstance(error, TimeoutError):
        return EditorAssistantFailureCode.PROVIDER_TIMEOUT
    if isinstance(error, ProviderFailedError):
        if isinstance(error.last_exc, TimeoutError | httpx.TimeoutException):
            return EditorAssistantFailureCode.PROVIDER_TIMEOUT
        return EditorAssistantFailureCode.PROVIDER_UNAVAILABLE
    if isinstance(error, AllProvidersFailedError):
        return _all_providers_failure_code(error)
    if isinstance(error, StaleBaseVersionError):
        return EditorAssistantFailureCode.STALE_BASE_VERSION
    if isinstance(error, QuestionPreviewError):
        return _validated_reason_code(
            getattr(error, "validated_failure_reason", None)
        )
    if isinstance(error, PatchContractError):
        return EditorAssistantFailureCode.CONTRACT_VIOLATION
    return EditorAssistantFailureCode.INTERNAL_ERROR


def _failed_response(
    request_id: UUID,
    preview_id: UUID,
    snapshot_token: str,
    code: EditorAssistantFailureCode,
) -> EditorAssistantPreviewResponse:
    message, applicability = editor_assistant_failure_contract(code)
    return EditorAssistantPreviewResponse(
        request_id=request_id,
        preview_id=preview_id,
        state=EditorPreviewState.FAILED,
        applicability=applicability,
        base_snapshot_token=snapshot_token,
        source=EditorAssistantSourceProjection(
            source_reference_count=0,
            references=(),
        ),
        failure=EditorAssistantFailure(
            error_code=code,
            message=message,
        ),
    )


def _build_preview_context(
    context: ResolvedQuestionContext,
    request: EditorAssistantPreviewRequest,
) -> QuestionPreviewContext:
    try:
        preview_intent, selected_scope, allowed_paths = _INTENT_CONTRACTS[
            request.intent
        ]
    except KeyError:
        raise _ApplicationFailure(
            EditorAssistantFailureCode.REJECTED_OUT_OF_SCOPE
        ) from None

    if (
        context.question_type != "MCQ"
        or not context.choices
        or len({choice.choice_id for choice in context.choices})
        != len(context.choices)
        or len({choice.order_index for choice in context.choices})
        != len(context.choices)
        or sum(choice.is_correct for choice in context.choices) != 1
        or context.correct_choice_id
        != next(choice.choice_id for choice in context.choices if choice.is_correct)
    ):
        raise _ApplicationFailure(EditorAssistantFailureCode.CONTRACT_VIOLATION)

    target = EditorTarget(
        EditorTargetEntityType.QUESTION,
        str(context.question_id),
        selected_scope,
    )
    snapshot = ContentVersionSnapshot(
        target=target,
        version=f"ctx-{context.snapshot_fingerprint[:32]}",
        content_hash=context.snapshot_fingerprint,
        lifecycle=ContentLifecycle.DRAFT,
    )
    command = StructuredEditCommand(
        request_key=str(request.request_key),
        preview_key=str(request.preview_key),
        target=target,
        base_snapshot=snapshot,
        operation_constraints=OperationConstraints(
            allowed_operations=(PatchOperationType.REPLACE,),
            allowed_field_paths=allowed_paths,
            protected_field_paths=(),
            require_source_evidence=True,
            max_operations=len(allowed_paths),
        ),
        instruction_text=request.instruction,
        locale=context.locale,
    )
    question = Question(
        question_id=str(context.question_id),
        prompt=context.question_text,
        options=tuple(
            AnswerOption(choice.text, choice.is_correct) for choice in context.choices
        ),
        explanation=context.explanation or "",
        signals=QuestionSignals(source_support=SourceSupportSignal.SUPPORTED),
    )

    facts_by_source = {fact.source_id: fact for fact in context.source_facts}
    evidence: list[SourceEvidenceExcerpt] = []
    for reference in context.source_references:
        fact = facts_by_source.get(reference.source_id)
        if fact is None or fact.content_sha256 != reference.content_sha256:
            raise _ApplicationFailure(
                EditorAssistantFailureCode.SOURCE_EVIDENCE_UNAVAILABLE
            )
        evidence.append(
            SourceEvidenceExcerpt(
                SourceEvidenceReference(
                    str(reference.source_id),
                    reference.locator,
                    reference.content_sha256,
                ),
                fact.text,
            )
        )
    if not evidence:
        raise _ApplicationFailure(
            EditorAssistantFailureCode.SOURCE_EVIDENCE_UNAVAILABLE
        )
    return QuestionPreviewContext(
        command=command,
        question=question,
        intent=preview_intent,
        evidence=tuple(evidence),
    )


def _public_options(
    context: ResolvedQuestionContext,
    value: object,
    *,
    require_current: bool,
) -> tuple[EditorAssistantPatchOption, ...]:
    if not isinstance(value, tuple) or len(value) != len(context.choices):
        raise _ApplicationFailure(EditorAssistantFailureCode.CONTRACT_VIOLATION)
    public: list[EditorAssistantPatchOption] = []
    for choice, option in zip(context.choices, value, strict=True):
        if not isinstance(option, AnswerOption):
            raise _ApplicationFailure(EditorAssistantFailureCode.CONTRACT_VIOLATION)
        if require_current and (
            option.text != choice.text or option.is_correct is not choice.is_correct
        ):
            raise _ApplicationFailure(EditorAssistantFailureCode.CONTRACT_VIOLATION)
        if option.is_correct is not choice.is_correct:
            raise _ApplicationFailure(EditorAssistantFailureCode.CONTRACT_VIOLATION)
        if choice.choice_id == context.correct_choice_id and option.text != choice.text:
            raise _ApplicationFailure(EditorAssistantFailureCode.CONTRACT_VIOLATION)
        public.append(
            EditorAssistantPatchOption(
                choice_id=choice.choice_id,
                text=option.text,
                is_correct=option.is_correct,
            )
        )
    return tuple(public)


def _public_operations(
    context: ResolvedQuestionContext,
    preview_context: QuestionPreviewContext,
    outcome: QuestionPreviewOutcome,
) -> tuple[EditorAssistantPatchOperation, ...]:
    patch = outcome.patch
    if (
        patch.request_key != preview_context.command.request_key
        or patch.preview_key != preview_context.command.preview_key
        or patch.target != preview_context.command.target
        or patch.base_snapshot != preview_context.command.base_snapshot
    ):
        raise _ApplicationFailure(EditorAssistantFailureCode.CONTRACT_VIOLATION)
    if patch.applicability_status is PatchApplicabilityStatus.REQUIRES_NEW_DRAFT_REVISION:
        raise _ApplicationFailure(
            EditorAssistantFailureCode.REQUIRES_NEW_DRAFT_REVISION
        )
    if patch.applicability_status is not PatchApplicabilityStatus.APPLICABLE:
        raise _ApplicationFailure(EditorAssistantFailureCode.CONTRACT_VIOLATION)

    operations: list[EditorAssistantPatchOperation] = []
    for operation in patch.operations:
        if (
            operation.target != preview_context.command.target
            or operation.operation is not PatchOperationType.REPLACE
        ):
            raise _ApplicationFailure(EditorAssistantFailureCode.CONTRACT_VIOLATION)
        try:
            path = EditorPatchPath(operation.field_path)
        except ValueError:
            raise _ApplicationFailure(
                EditorAssistantFailureCode.REJECTED_OUT_OF_SCOPE
            ) from None
        if operation.field_path not in preview_context.command.operation_constraints.allowed_field_paths:
            raise _ApplicationFailure(
                EditorAssistantFailureCode.REJECTED_OUT_OF_SCOPE
            )
        if path is EditorPatchPath.TEXT:
            if operation.before_value != context.question_text:
                raise _ApplicationFailure(
                    EditorAssistantFailureCode.CONTRACT_VIOLATION
                )
            before_value = context.question_text
            after_value = operation.after_value
        elif path is EditorPatchPath.EXPLANATION:
            current = context.explanation or ""
            if operation.before_value != current:
                raise _ApplicationFailure(
                    EditorAssistantFailureCode.CONTRACT_VIOLATION
                )
            before_value = context.explanation
            after_value = operation.after_value
        else:
            before_value = _public_options(
                context,
                operation.before_value,
                require_current=True,
            )
            after_value = _public_options(
                context,
                operation.after_value,
                require_current=False,
            )
        operations.append(
            EditorAssistantPatchOperation(
                operation="replace",
                field_path=path,
                before_value=before_value,
                after_value=after_value,
            )
        )
    if not operations:
        raise _ApplicationFailure(EditorAssistantFailureCode.CONTRACT_VIOLATION)
    return tuple(operations)


def _public_source(
    context: ResolvedQuestionContext,
    outcome: QuestionPreviewOutcome,
) -> EditorAssistantSourceProjection:
    references_by_id = {
        str(reference.source_id): reference for reference in context.source_references
    }
    public: list[EditorAssistantSourceReference] = []
    seen: set[str] = set()
    for evidence in outcome.patch.source_evidence:
        reference = references_by_id.get(evidence.source_id)
        if (
            reference is None
            or evidence.source_id in seen
            or evidence.locator != reference.locator
            or evidence.evidence_hash != reference.content_sha256
        ):
            raise _ApplicationFailure(EditorAssistantFailureCode.CONTRACT_VIOLATION)
        seen.add(evidence.source_id)
        public.append(
            EditorAssistantSourceReference(
                source_id=evidence.source_id,
                document_title=reference.document_title,
                locator=reference.locator,
            )
        )
    if not public:
        raise _ApplicationFailure(
            EditorAssistantFailureCode.SOURCE_EVIDENCE_UNAVAILABLE
        )
    return EditorAssistantSourceProjection(
        source_reference_count=len(public),
        references=tuple(public),
    )


async def create_question_preview_response(
    context: ResolvedQuestionContext,
    request: EditorAssistantPreviewRequest,
    adapter: QuestionPreviewAdapter,
    identity_factory: PreviewIdentityFactory,
) -> EditorAssistantPreviewResponse:
    """Return one pure completed or bounded failed public preview response."""

    request_id = request.request_key
    preview_id = request.preview_key
    snapshot_token = _snapshot_token(context.snapshot_fingerprint)
    try:
        request_id, preview_id = identity_factory(request)
        if not isinstance(request_id, UUID) or not isinstance(preview_id, UUID):
            raise _ApplicationFailure(EditorAssistantFailureCode.INTERNAL_ERROR)
        preview_context = _build_preview_context(context, request)
        outcome = await adapter(preview_context)
        if not isinstance(outcome, QuestionPreviewOutcome):
            raise _ApplicationFailure(EditorAssistantFailureCode.CONTRACT_VIOLATION)
        validation = project_validation_report(outcome.validation_result)
        if validation.status is EditorValidationStatus.FAIL:
            raise _ApplicationFailure(EditorAssistantFailureCode.VALIDATION_BLOCKED)
        operations = _public_operations(context, preview_context, outcome)
        source = _public_source(context, outcome)
        response = EditorAssistantPreviewResponse(
            request_id=request_id,
            preview_id=preview_id,
            state=EditorPreviewState.COMPLETED,
            applicability=(
                EditorApplicability.APPLICABLE_WITH_WARNINGS
                if validation.status is EditorValidationStatus.WARN
                else EditorApplicability.APPLICABLE
            ),
            base_snapshot_token=snapshot_token,
            operations=operations,
            validation=validation,
            source=source,
            provenance=EditorAssistantProvenance(
                prompt_version=outcome.patch.provider_provenance.prompt_version,
                generator_version=outcome.patch.provider_provenance.generator_version,
                validator_version=outcome.validation_result.validator_version,
            ),
        )
        return response
    except Exception as error:
        return _failed_response(
            request_id,
            preview_id,
            snapshot_token,
            _failure_code(error),
        )


__all__ = [
    "PreviewIdentityFactory",
    "QuestionPreviewAdapter",
    "create_question_preview_response",
]
