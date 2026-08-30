"""Pure single-question AI preview adapter.

The adapter is separate from full course generation. It asks a provider for
one strict JSON candidate, validates it against the selected question and
bounded evidence, and returns a preview-only ``StructuredEditPatch``. It never
applies or persists content.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.modules.ai.llm_client import (
    ResilientLLMClient,
    ValidatedCallFailureReason,
    ValidatedLLMResult,
)
from app.modules.editor_assistant.patch_contract import (
    ContentLifecycle,
    ContentVersionSnapshot,
    EditorTargetEntityType,
    PatchApplicabilityStatus,
    PatchOperation,
    PatchOperationType,
    ProviderProvenance,
    SourceEvidenceReference,
    StaleBaseVersionError,
    StructuredEditCommand,
    StructuredEditPatch,
    ValidationIssue,
    ValidationReport,
    ValidationStatus,
    project_patch_analytics,
)
from app.modules.editor_assistant.question_validator import (
    AnswerOption,
    Question,
    QuestionSet,
    QuestionValidationResult,
    ValidatorStatus,
    validate_question_set,
)


class QuestionPreviewError(ValueError):
    """Safe, non-reflecting preview error."""

    validated_failure_reason = ValidatedCallFailureReason.CONTRACT_VIOLATION


class UnsupportedPreviewIntentError(QuestionPreviewError):
    """The normalized intent is outside the Step 4 contract."""

    validated_failure_reason = ValidatedCallFailureReason.REJECTED_OUT_OF_SCOPE


class ProviderOutputUnparseableError(QuestionPreviewError):
    """The provider response is malformed or outside parser bounds."""

    validated_failure_reason = ValidatedCallFailureReason.PROVIDER_OUTPUT_UNPARSEABLE


class RejectedOutOfScopeError(QuestionPreviewError):
    """The proposal changes fields outside the requested scope."""

    validated_failure_reason = ValidatedCallFailureReason.REJECTED_OUT_OF_SCOPE


class SourceEvidenceUnavailableError(QuestionPreviewError):
    """The proposal is not supported by approved source evidence."""

    validated_failure_reason = ValidatedCallFailureReason.SOURCE_EVIDENCE_UNAVAILABLE


class ValidationBlockedError(QuestionPreviewError):
    """The deterministic question validator rejected the proposal."""

    validated_failure_reason = ValidatedCallFailureReason.VALIDATION_BLOCKED


class PreviewIntent(StrEnum):
    WORDING = "wording"
    ADD_CONTEXT = "add_context"
    DISTRACTORS = "distractors"
    ANSWER_BALANCE = "answer_balance"
    DIFFICULTY = "difficulty"
    SCENARIO = "scenario"
    EXPLANATION = "explanation"
    SOURCE_VERIFICATION = "source_verification"


_INTENT_ALIASES = {
    "rewrite_wording": PreviewIntent.WORDING,
    "simplify_language": PreviewIntent.WORDING,
    "regenerate_distractors": PreviewIntent.DISTRACTORS,
    "balance_answer_length": PreviewIntent.ANSWER_BALANCE,
    "change_difficulty": PreviewIntent.DIFFICULTY,
    "make_scenario_based": PreviewIntent.SCENARIO,
    "add_or_rewrite_explanation": PreviewIntent.EXPLANATION,
    "fix_source_grounding": PreviewIntent.SOURCE_VERIFICATION,
}

_INTENT_FIELDS: dict[PreviewIntent, frozenset[str]] = {
    PreviewIntent.WORDING: frozenset({"question.text"}),
    PreviewIntent.ADD_CONTEXT: frozenset({"question.text"}),
    PreviewIntent.DISTRACTORS: frozenset({"question.answer_options"}),
    PreviewIntent.ANSWER_BALANCE: frozenset({"question.answer_options"}),
    PreviewIntent.DIFFICULTY: frozenset({"question.text", "question.answer_options"}),
    PreviewIntent.SCENARIO: frozenset({"question.text", "question.answer_options"}),
    PreviewIntent.EXPLANATION: frozenset({"question.explanation"}),
    PreviewIntent.SOURCE_VERIFICATION: frozenset(
        {"question.text", "question.answer_options", "question.explanation"}
    ),
}

_MAX_EVIDENCE = 8
_MAX_EVIDENCE_EXCERPT = 1_200
_MAX_PROMPT = 24_000
_PROMPT_VERSION = "question-preview-v1"
_GENERATOR_VERSION = "editor-assistant-step4-v1"


def _invalid() -> QuestionPreviewError:
    return ProviderOutputUnparseableError("Некорректные данные предпросмотра")


def normalize_preview_intent(value: PreviewIntent | str) -> PreviewIntent:
    if isinstance(value, PreviewIntent):
        return value
    if not isinstance(value, str):
        raise UnsupportedPreviewIntentError("Неподдерживаемый запрос редактора")
    normalized = value.strip().casefold()
    try:
        return PreviewIntent(normalized)
    except ValueError:
        try:
            return _INTENT_ALIASES[normalized]
        except KeyError:
            raise UnsupportedPreviewIntentError("Неподдерживаемый запрос редактора") from None


@dataclass(frozen=True, slots=True)
class SourceEvidenceExcerpt:
    """Bounded provider-only source excerpt paired with an opaque reference."""

    reference: SourceEvidenceReference
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.reference, SourceEvidenceReference) or not isinstance(self.text, str):
            raise _invalid()
        text = " ".join(self.text.split())
        if not text or len(text) > _MAX_EVIDENCE_EXCERPT:
            raise _invalid()
        object.__setattr__(self, "text", text)


@dataclass(frozen=True, slots=True)
class QuestionPreviewContext:
    """Immutable, bounded context for one question preview."""

    command: StructuredEditCommand
    question: Question
    intent: PreviewIntent | str
    evidence: tuple[SourceEvidenceExcerpt, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.command, StructuredEditCommand) or not isinstance(self.question, Question):
            raise _invalid()
        if self.command.target.entity_type is not EditorTargetEntityType.QUESTION:
            raise _invalid()
        if self.question.question_id != self.command.target.entity_id:
            raise _invalid()
        object.__setattr__(self, "intent", normalize_preview_intent(self.intent))
        evidence = tuple(self.evidence)
        if not evidence or len(evidence) > _MAX_EVIDENCE:
            raise _invalid()
        if not all(isinstance(item, SourceEvidenceExcerpt) for item in evidence):
            raise _invalid()
        identifiers = [item.reference.source_id for item in evidence]
        if len(set(identifiers)) != len(identifiers):
            raise _invalid()
        object.__setattr__(self, "evidence", evidence)


@dataclass(frozen=True, slots=True)
class _Candidate:
    question: Question
    source_ids: tuple[str, ...]
    validation: QuestionValidationResult


@dataclass(frozen=True, slots=True)
class QuestionPreviewOutcome:
    """Validated preview patch paired with the exact final-question result."""

    patch: StructuredEditPatch
    validation_result: QuestionValidationResult


def _require_bounded_string(value: object, maximum: int) -> str:
    if not isinstance(value, str):
        raise _invalid()
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum:
        raise _invalid()
    return normalized


def _parse_candidate(raw: str, context: QuestionPreviewContext) -> _Candidate:
    if not isinstance(raw, str) or len(raw) > _MAX_PROMPT:
        raise _invalid()
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        raise _invalid() from None
    if not isinstance(value, Mapping):
        raise _invalid()
    expected = {
        "prompt",
        "options",
        "explanation",
        "correct_option_index",
        "source_reference_ids",
        "source_supported",
    }
    if set(value) != expected:
        raise _invalid()
    prompt = _require_bounded_string(value["prompt"], 2_000)
    explanation = _require_bounded_string(value["explanation"], 3_000)
    raw_options = value["options"]
    if not isinstance(raw_options, Sequence) or isinstance(raw_options, str | bytes):
        raise _invalid()
    if len(raw_options) != len(context.question.options) or len(raw_options) < 2:
        raise _invalid()
    options: list[AnswerOption] = []
    for item in raw_options:
        if not isinstance(item, Mapping) or set(item) != {"text", "is_correct"}:
            raise _invalid()
        if not isinstance(item["is_correct"], bool):
            raise _invalid()
        options.append(AnswerOption(_require_bounded_string(item["text"], 1_200), item["is_correct"]))

    current_correct = [index for index, option in enumerate(context.question.options) if option.is_correct]
    if len(current_correct) != 1:
        raise _invalid()
    correct_index = value["correct_option_index"]
    if isinstance(correct_index, bool) or not isinstance(correct_index, int) or correct_index != current_correct[0]:
        raise QuestionPreviewError("Предложение нарушает сохранение правильного ответа")
    if sum(option.is_correct for option in options) != 1 or not options[correct_index].is_correct:
        raise QuestionPreviewError("Предложение нарушает сохранение правильного ответа")
    if options[correct_index].text != context.question.options[correct_index].text:
        raise QuestionPreviewError("Предложение нарушает сохранение правильного ответа")

    raw_source_ids = value["source_reference_ids"]
    if not isinstance(raw_source_ids, Sequence) or isinstance(raw_source_ids, str | bytes):
        raise _invalid()
    if (
        not raw_source_ids
        or len(raw_source_ids) > _MAX_EVIDENCE
        or any(not isinstance(item, str) for item in raw_source_ids)
    ):
        raise _invalid()
    source_ids = tuple(raw_source_ids)
    allowed_ids = {item.reference.source_id for item in context.evidence}
    if len(set(source_ids)) != len(source_ids) or not set(source_ids) <= allowed_ids:
        raise SourceEvidenceUnavailableError("Предложение не подтверждено источником")
    if value["source_supported"] is not True:
        raise SourceEvidenceUnavailableError("Предложение не подтверждено источником")

    candidate = Question(
        question_id=context.question.question_id,
        prompt=prompt,
        options=tuple(options),
        explanation=explanation,
        signals=context.question.signals,
    )
    changed_fields = {
        field
        for field, before, after in (
            ("question.text", context.question.prompt, candidate.prompt),
            ("question.answer_options", context.question.options, candidate.options),
            ("question.explanation", context.question.explanation, candidate.explanation),
        )
        if before != after
    }
    if not changed_fields or not changed_fields <= _INTENT_FIELDS[context.intent]:
        raise RejectedOutOfScopeError("Предложение выходит за область выбранного запроса")

    constraints = context.command.operation_constraints
    for field in changed_fields:
        if not (
            field == context.command.target.selected_scope
            or field.startswith(f"{context.command.target.selected_scope}.")
        ):
            raise RejectedOutOfScopeError("Предложение выходит за выбранную область")
        if constraints.allowed_field_paths and field not in constraints.allowed_field_paths:
            raise RejectedOutOfScopeError("Предложение содержит недопустимое поле")
        if any(
            field == protected or field.startswith(f"{protected}.")
            for protected in constraints.protected_field_paths
        ):
            raise QuestionPreviewError("Предложение изменяет защищённое поле")

    validation = validate_question_set(QuestionSet((candidate,), locale=context.command.locale))
    if validation.status is ValidatorStatus.FAIL:
        raise ValidationBlockedError("Предложение не прошло проверку качества")
    return _Candidate(question=candidate, source_ids=source_ids, validation=validation)


def _prompt(context: QuestionPreviewContext) -> str:
    current_correct_option_index = next(
        (index for index, option in enumerate(context.question.options) if option.is_correct),
        None,
    )
    if current_correct_option_index is None:
        raise _invalid()
    prompt = json.dumps(
        {
            "task": "Return one JSON question candidate only.",
            "intent": context.intent.value,
            "locale": context.command.locale,
            "raw_instruction": context.command.instruction_text,
            "rules": {
                "preserve_correct_answer_index": current_correct_option_index,
                "preserve_exact_correct_answer_text": context.question.options[current_correct_option_index].text,
                "preserve_correct_answer_flag": True,
                "preserve_option_count": len(context.question.options),
                "selected_scope": context.command.target.selected_scope,
                "protected_fields": list(context.command.operation_constraints.protected_field_paths),
                "ground_only_in_source_evidence": True,
            },
            "question": {
                "text": context.question.prompt,
                "answer_options": [
                    {"text": option.text, "is_correct": option.is_correct}
                    for option in context.question.options
                ],
                "explanation": context.question.explanation,
                "current_correct_option_index": current_correct_option_index,
                "current_correct_answer_text": context.question.options[current_correct_option_index].text,
            },
            "source_evidence": [
                {
                    "id": item.reference.source_id,
                    "locator": item.reference.locator,
                    "excerpt": item.text,
                }
                for item in context.evidence
            ],
            "output_schema": {
                "prompt": "string",
                "options": [{"text": "string", "is_correct": "boolean"}],
                "explanation": "string",
                "correct_option_index": "integer",
                "source_reference_ids": ["string"],
                "source_supported": "boolean",
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(prompt) > _MAX_PROMPT:
        raise _invalid()
    return prompt


def _validation_report(result: QuestionValidationResult) -> ValidationReport:
    issues = tuple(
        ValidationIssue(code="provider_output_invalid", blocking=item.blocking)
        for item in result.findings
    )
    return ValidationReport(
        status=ValidationStatus(result.status.value),
        issues=issues,
        validator_version=result.validator_version,
    )


def _patch(
    context: QuestionPreviewContext,
    candidate: _Candidate,
    provider: ValidatedLLMResult[_Candidate],
    validation: QuestionValidationResult,
) -> StructuredEditPatch:
    before = context.question
    after = candidate.question
    operations = tuple(
        PatchOperation(
            target=context.command.target,
            field_path=field,
            operation=PatchOperationType.REPLACE,
            before_value=before_value,
            after_value=after_value,
        )
        for field, before_value, after_value in (
            ("question.text", before.prompt, after.prompt),
            ("question.answer_options", before.options, after.options),
            ("question.explanation", before.explanation, after.explanation),
        )
        if before_value != after_value
    )
    applicability = (
        PatchApplicabilityStatus.REQUIRES_NEW_DRAFT_REVISION
        if context.command.base_snapshot.lifecycle is ContentLifecycle.PUBLISHED
        else PatchApplicabilityStatus.APPLICABLE
    )
    return StructuredEditPatch(
        request_key=context.command.request_key,
        preview_key=context.command.preview_key,
        target=context.command.target,
        base_snapshot=context.command.base_snapshot,
        operations=operations,
        source_evidence=tuple(
            item.reference
            for item in context.evidence
            if item.reference.source_id in candidate.source_ids
        ),
        validation_report=_validation_report(validation),
        provider_provenance=ProviderProvenance(
            provider=provider.provider,
            model_id=provider.model_id,
            prompt_version=_PROMPT_VERSION,
            generator_version=_GENERATOR_VERSION,
        ),
        applicability_status=applicability,
    )


async def preview_question(
    context: QuestionPreviewContext,
    llm: ResilientLLMClient,
    current_snapshot: ContentVersionSnapshot,
) -> StructuredEditPatch:
    """Return a validated, non-mutating preview for one question."""

    return (
        await preview_question_with_validation(context, llm, current_snapshot)
    ).patch


async def preview_question_with_validation(
    context: QuestionPreviewContext,
    llm: ResilientLLMClient,
    current_snapshot: ContentVersionSnapshot,
) -> QuestionPreviewOutcome:
    """Return a preview patch and the exact validation of its final proposal."""

    if not isinstance(llm, ResilientLLMClient):
        raise _invalid()
    if current_snapshot != context.command.base_snapshot:
        raise StaleBaseVersionError("Editor base version is stale")
    if context.question.question_id != context.command.target.entity_id:
        raise _invalid()
    prompt = _prompt(context)

    def parse_and_validate(raw: str) -> _Candidate:
        return _parse_candidate(raw, context)

    provider_result = await llm.ainvoke_validated(
        prompt,
        parse_and_validate,
        response_format={"type": "json_object"},
    )
    validation = provider_result.value.validation
    patch = _patch(context, provider_result.value, provider_result, validation)
    return QuestionPreviewOutcome(patch=patch, validation_result=validation)


def project_question_preview_analytics(patch: StructuredEditPatch) -> dict[str, Any]:
    """Project only closed technical fields; never content or evidence text."""

    data = project_patch_analytics(patch)
    return {
        key: data[key]
        for key in (
            "target_entity_type",
            "operation_count",
            "source_reference_count",
            "validation_status",
            "applicability_status",
            "content_lifecycle",
            "provider",
            "model_id",
            "prompt_version",
            "generator_version",
            "validator_version",
        )
    }


__all__ = [
    "PreviewIntent",
    "ProviderOutputUnparseableError",
    "QuestionPreviewContext",
    "QuestionPreviewError",
    "QuestionPreviewOutcome",
    "RejectedOutOfScopeError",
    "SourceEvidenceExcerpt",
    "SourceEvidenceUnavailableError",
    "UnsupportedPreviewIntentError",
    "ValidationBlockedError",
    "normalize_preview_intent",
    "preview_question",
    "preview_question_with_validation",
    "project_question_preview_analytics",
]

UnsupportedPreviewIntent = UnsupportedPreviewIntentError
