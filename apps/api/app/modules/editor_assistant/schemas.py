"""Strict public HTTP DTOs for the single-question editor assistant.

The models in this module are transport contracts only. They expose no tenant
authority, provider routing, raw prompts, source excerpts, or mutation logic.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .question_validator import _ISSUE_MESSAGES as _QUALITY_ISSUE_MESSAGES
from .taxonomy import EditorQualityIssueLabel

_OPAQUE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{15,159}$")
_OPAQUE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_MAX_SERIALIZED_PREVIEW_BYTES = 65_536


class _StrictDTO(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class EditorIntent(StrEnum):
    REWRITE_WORDING = "rewrite_wording"
    SIMPLIFY_LANGUAGE = "simplify_language"
    ADD_CONTEXT = "add_context"
    REGENERATE_DISTRACTORS = "regenerate_distractors"
    BALANCE_ANSWER_LENGTH = "balance_answer_length"
    CHANGE_DIFFICULTY = "change_difficulty"
    MAKE_SCENARIO_BASED = "make_scenario_based"
    ADD_OR_REWRITE_EXPLANATION = "add_or_rewrite_explanation"
    FIX_SOURCE_GROUNDING = "fix_source_grounding"


class EditorPreviewState(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class EditorApplicability(StrEnum):
    APPLICABLE = "applicable"
    APPLICABLE_WITH_WARNINGS = "applicable_with_warnings"
    REQUIRES_NEW_DRAFT_REVISION = "requires_new_draft_revision"
    NOT_APPLICABLE = "not_applicable"
    STALE = "stale"


class EditorPatchPath(StrEnum):
    TEXT = "question.text"
    ANSWER_OPTIONS = "question.answer_options"
    EXPLANATION = "question.explanation"


class EditorValidationStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class EditorValidationIssueCode(StrEnum):
    INVALID_OPERATION = "invalid_operation"
    OUT_OF_SCOPE = "out_of_scope"
    MISSING_SOURCE_EVIDENCE = "missing_source_evidence"
    PROTECTED_FIELD = "protected_field"
    INVALID_BASE_SNAPSHOT = "invalid_base_snapshot"
    PUBLISHED_CONTENT_REQUIRES_DRAFT = "published_content_requires_draft"
    PROVIDER_OUTPUT_INVALID = "provider_output_invalid"


class EditorAssistantFailureCode(StrEnum):
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_OUTPUT_UNPARSEABLE = "provider_output_unparseable"
    CONTRACT_VIOLATION = "contract_violation"
    VALIDATION_BLOCKED = "validation_blocked"
    STALE_BASE_VERSION = "stale_base_version"
    REJECTED_OUT_OF_SCOPE = "rejected_out_of_scope"
    SOURCE_EVIDENCE_UNAVAILABLE = "source_evidence_unavailable"
    REQUIRES_NEW_DRAFT_REVISION = "requires_new_draft_revision"
    INTERNAL_ERROR = "internal_error"


_ISSUE_MESSAGES: dict[EditorValidationIssueCode, str] = {
    EditorValidationIssueCode.INVALID_OPERATION: "Предложение содержит недопустимое изменение.",
    EditorValidationIssueCode.OUT_OF_SCOPE: "Предложение выходит за область выбранного вопроса.",
    EditorValidationIssueCode.MISSING_SOURCE_EVIDENCE: "Недостаточно данных из исходного документа.",
    EditorValidationIssueCode.PROTECTED_FIELD: "Предложение изменяет защищённое поле.",
    EditorValidationIssueCode.INVALID_BASE_SNAPSHOT: "Исходная версия вопроса изменилась.",
    EditorValidationIssueCode.PUBLISHED_CONTENT_REQUIRES_DRAFT: (
        "Для опубликованного курса требуется новая черновая версия."
    ),
    EditorValidationIssueCode.PROVIDER_OUTPUT_INVALID: (
        "Предложение не прошло проверку качества."
    ),
}

_FAILURE_CONTRACTS: dict[
    EditorAssistantFailureCode,
    tuple[str, EditorApplicability],
] = {
    EditorAssistantFailureCode.PROVIDER_TIMEOUT: (
        "Сервис генерации не ответил вовремя.",
        EditorApplicability.NOT_APPLICABLE,
    ),
    EditorAssistantFailureCode.PROVIDER_UNAVAILABLE: (
        "Сервис генерации временно недоступен.",
        EditorApplicability.NOT_APPLICABLE,
    ),
    EditorAssistantFailureCode.PROVIDER_OUTPUT_UNPARSEABLE: (
        "Не удалось обработать ответ сервиса генерации.",
        EditorApplicability.NOT_APPLICABLE,
    ),
    EditorAssistantFailureCode.CONTRACT_VIOLATION: (
        "Предложение не соответствует требованиям редактора.",
        EditorApplicability.NOT_APPLICABLE,
    ),
    EditorAssistantFailureCode.VALIDATION_BLOCKED: (
        "Предложение не прошло проверку качества.",
        EditorApplicability.NOT_APPLICABLE,
    ),
    EditorAssistantFailureCode.STALE_BASE_VERSION: (
        "Вопрос был изменён. Обновите данные и повторите запрос.",
        EditorApplicability.STALE,
    ),
    EditorAssistantFailureCode.REJECTED_OUT_OF_SCOPE: (
        "Предложение выходит за область выбранного вопроса.",
        EditorApplicability.NOT_APPLICABLE,
    ),
    EditorAssistantFailureCode.SOURCE_EVIDENCE_UNAVAILABLE: (
        "Для вопроса недоступны подтверждающие материалы.",
        EditorApplicability.NOT_APPLICABLE,
    ),
    EditorAssistantFailureCode.REQUIRES_NEW_DRAFT_REVISION: (
        "Для опубликованного курса требуется новая черновая версия.",
        EditorApplicability.REQUIRES_NEW_DRAFT_REVISION,
    ),
    EditorAssistantFailureCode.INTERNAL_ERROR: (
        "Не удалось подготовить предложение.",
        EditorApplicability.NOT_APPLICABLE,
    ),
}


def editor_assistant_failure_contract(
    code: EditorAssistantFailureCode | str,
) -> tuple[str, EditorApplicability]:
    """Return the canonical public message and applicability for one code."""

    normalized = EditorAssistantFailureCode(code)
    return _FAILURE_CONTRACTS[normalized]


def _require_opaque_token(value: str) -> str:
    if not _OPAQUE_TOKEN.fullmatch(value):
        raise ValueError("Invalid opaque snapshot token")
    return value


def _require_safe_metadata(value: str) -> str:
    if any(ord(character) < 32 for character in value):
        raise ValueError("Invalid safe metadata")
    return value


class EditorAssistantPreviewRequest(_StrictDTO):
    request_key: UUID
    preview_key: UUID
    intent: EditorIntent
    instruction: str = Field(min_length=1, max_length=8_000)

    @field_validator("instruction", mode="before")
    @classmethod
    def _strip_instruction(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class EditorAssistantErrorResponse(_StrictDTO):
    """Bounded public HTTP error body with no internal diagnostic fields."""

    detail: str = Field(min_length=1, max_length=240)


class EditorAssistantPatchOption(_StrictDTO):
    choice_id: UUID
    text: str = Field(min_length=1, max_length=1_000)
    is_correct: bool


PatchValue = str | tuple[EditorAssistantPatchOption, ...] | None


class EditorAssistantPatchOperation(_StrictDTO):
    operation: Literal["replace"]
    field_path: EditorPatchPath
    before_value: PatchValue
    after_value: PatchValue

    @model_validator(mode="after")
    def _validate_values_for_path(self) -> EditorAssistantPatchOperation:
        before = self.before_value
        after = self.after_value
        if self.field_path is EditorPatchPath.TEXT:
            if not isinstance(before, str) or not isinstance(after, str):
                raise ValueError("Question text operation requires strings")
            if not before or not after or len(before) > 4_000 or len(after) > 4_000:
                raise ValueError("Question text is outside bounds")
        elif self.field_path is EditorPatchPath.EXPLANATION:
            for value in (before, after):
                if value is not None and (
                    not isinstance(value, str) or not value or len(value) > 6_000
                ):
                    raise ValueError("Question explanation is outside bounds")
        else:
            if not isinstance(before, tuple) or not isinstance(after, tuple):
                raise ValueError("Answer option operation requires option lists")
            if not 2 <= len(before) <= 20 or not 2 <= len(after) <= 20:
                raise ValueError("Answer option count is outside bounds")
            before_ids = tuple(option.choice_id for option in before)
            after_ids = tuple(option.choice_id for option in after)
            if len(set(before_ids)) != len(before_ids) or len(set(after_ids)) != len(after_ids):
                raise ValueError("Answer option identifiers must be unique")
            if before_ids != after_ids:
                raise ValueError("Answer option identity and order must be preserved")
            before_correct = tuple(option.is_correct for option in before)
            after_correct = tuple(option.is_correct for option in after)
            if sum(before_correct) != 1 or before_correct != after_correct:
                raise ValueError("Correct answer identity must be preserved")
            correct_index = before_correct.index(True)
            if before[correct_index].text != after[correct_index].text:
                raise ValueError("Correct answer text must be preserved")
        if before == after:
            raise ValueError("Patch operation must change content")
        return self


class EditorAssistantValidationIssue(_StrictDTO):
    code: EditorValidationIssueCode | EditorQualityIssueLabel
    message: str
    blocking: bool
    field_path: EditorPatchPath

    @model_validator(mode="after")
    def _require_catalog_message(self) -> EditorAssistantValidationIssue:
        expected_message = (
            _QUALITY_ISSUE_MESSAGES[self.code]
            if isinstance(self.code, EditorQualityIssueLabel)
            else _ISSUE_MESSAGES[self.code]
        )
        if self.message != expected_message:
            raise ValueError("Validation issue message does not match catalog")
        return self


class EditorAssistantValidationReport(_StrictDTO):
    status: EditorValidationStatus
    issues: tuple[EditorAssistantValidationIssue, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def _validate_status_shape(self) -> EditorAssistantValidationReport:
        if self.status is EditorValidationStatus.PASS and self.issues:
            raise ValueError("Passing validation cannot include issues")
        if self.status is EditorValidationStatus.WARN and (
            not self.issues or any(issue.blocking for issue in self.issues)
        ):
            raise ValueError("Warning validation requires non-blocking issues")
        if self.status is EditorValidationStatus.FAIL and not any(
            issue.blocking for issue in self.issues
        ):
            raise ValueError("Failed validation requires a blocking issue")
        return self


class EditorAssistantSourceReference(_StrictDTO):
    source_id: str = Field(min_length=1, max_length=120, pattern=_OPAQUE_REFERENCE.pattern)
    document_title: str = Field(min_length=1, max_length=240)
    locator: str = Field(min_length=1, max_length=240)

    @field_validator("document_title", "locator")
    @classmethod
    def _validate_safe_metadata(cls, value: str) -> str:
        return _require_safe_metadata(value)


class EditorAssistantSourceProjection(_StrictDTO):
    source_reference_count: int = Field(ge=0, le=8)
    references: tuple[EditorAssistantSourceReference, ...] = Field(max_length=8)

    @model_validator(mode="after")
    def _validate_count(self) -> EditorAssistantSourceProjection:
        if self.source_reference_count != len(self.references):
            raise ValueError("Source reference count does not match references")
        source_ids = tuple(reference.source_id for reference in self.references)
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("Source references must be unique")
        return self


class EditorAssistantProvenance(_StrictDTO):
    prompt_version: str = Field(min_length=1, max_length=120, pattern=_SAFE_VERSION.pattern)
    generator_version: str = Field(min_length=1, max_length=120, pattern=_SAFE_VERSION.pattern)
    validator_version: str = Field(min_length=1, max_length=120, pattern=_SAFE_VERSION.pattern)


class EditorAssistantFailure(_StrictDTO):
    error_code: EditorAssistantFailureCode
    message: str

    @model_validator(mode="after")
    def _require_catalog_message(self) -> EditorAssistantFailure:
        expected_message, _ = editor_assistant_failure_contract(self.error_code)
        if self.message != expected_message:
            raise ValueError("Failure message does not match catalog")
        return self


class EditorAssistantPreviewResponse(_StrictDTO):
    request_id: UUID
    preview_id: UUID
    state: EditorPreviewState
    applicability: EditorApplicability
    base_snapshot_token: str = Field(min_length=16, max_length=160)
    operations: tuple[EditorAssistantPatchOperation, ...] = Field(
        default=(),
        max_length=3,
    )
    validation: EditorAssistantValidationReport | None = None
    source: EditorAssistantSourceProjection
    provenance: EditorAssistantProvenance | None = None
    failure: EditorAssistantFailure | None = None

    @field_validator("base_snapshot_token")
    @classmethod
    def _validate_snapshot_token(cls, value: str) -> str:
        return _require_opaque_token(value)

    @model_validator(mode="after")
    def _validate_response_shape(self) -> EditorAssistantPreviewResponse:
        paths = tuple(operation.field_path for operation in self.operations)
        if len(set(paths)) != len(paths):
            raise ValueError("Patch operation paths must be unique")

        if self.state is EditorPreviewState.PENDING:
            if (
                self.applicability is not EditorApplicability.NOT_APPLICABLE
                or self.operations
                or self.validation is not None
                or self.provenance is not None
                or self.failure is not None
                or self.source.source_reference_count != 0
            ):
                raise ValueError("Pending preview has an invalid response shape")
        elif self.state is EditorPreviewState.COMPLETED:
            if self.applicability not in {
                EditorApplicability.APPLICABLE,
                EditorApplicability.APPLICABLE_WITH_WARNINGS,
            }:
                raise ValueError("Completed preview has invalid applicability")
            if (
                not self.operations
                or self.validation is None
                or self.provenance is None
                or self.failure is not None
                or self.source.source_reference_count < 1
            ):
                raise ValueError("Completed preview is missing patch metadata")
            expected_validation = (
                EditorValidationStatus.WARN
                if self.applicability is EditorApplicability.APPLICABLE_WITH_WARNINGS
                else EditorValidationStatus.PASS
            )
            if self.validation.status is not expected_validation:
                raise ValueError("Applicability and validation status do not match")
        else:
            if (
                self.operations
                or self.validation is not None
                or self.provenance is not None
                or self.failure is None
                or self.source.source_reference_count != 0
            ):
                raise ValueError("Failed preview has an invalid response shape")
            _, expected_applicability = editor_assistant_failure_contract(
                self.failure.error_code
            )
            if self.applicability is not expected_applicability:
                raise ValueError("Failure and applicability do not match")

        if len(self.model_dump_json().encode("utf-8")) > _MAX_SERIALIZED_PREVIEW_BYTES:
            raise ValueError("Serialized preview exceeds durable result limit")
        return self


class EditorAssistantApplyRequest(_StrictDTO):
    preview_id: UUID
    apply_key: UUID
    base_snapshot_token: str = Field(min_length=16, max_length=160)

    @field_validator("base_snapshot_token")
    @classmethod
    def _validate_snapshot_token(cls, value: str) -> str:
        return _require_opaque_token(value)


class EditorAssistantChoiceResponse(_StrictDTO):
    choice_id: UUID
    text: str = Field(min_length=1, max_length=1_000)
    is_correct: bool


class EditorAssistantApplyResponse(_StrictDTO):
    question_id: UUID
    text: str = Field(min_length=1, max_length=4_000)
    explanation: str | None = Field(default=None, max_length=6_000)
    options: tuple[EditorAssistantChoiceResponse, ...] = Field(
        min_length=2,
        max_length=20,
    )
    persisted_snapshot_token: str = Field(min_length=16, max_length=160)

    @field_validator("persisted_snapshot_token")
    @classmethod
    def _validate_snapshot_token(cls, value: str) -> str:
        return _require_opaque_token(value)

    @model_validator(mode="after")
    def _validate_single_correct_question(self) -> EditorAssistantApplyResponse:
        choice_ids = tuple(choice.choice_id for choice in self.options)
        if len(set(choice_ids)) != len(choice_ids):
            raise ValueError("Choice identifiers must be unique")
        if sum(choice.is_correct for choice in self.options) != 1:
            raise ValueError("Question must have exactly one correct answer")
        return self


__all__ = [
    "EditorApplicability",
    "EditorAssistantApplyRequest",
    "EditorAssistantApplyResponse",
    "EditorAssistantChoiceResponse",
    "EditorAssistantErrorResponse",
    "EditorAssistantFailure",
    "EditorAssistantFailureCode",
    "EditorAssistantPatchOperation",
    "EditorAssistantPatchOption",
    "EditorAssistantPreviewRequest",
    "EditorAssistantPreviewResponse",
    "EditorAssistantProvenance",
    "EditorAssistantSourceProjection",
    "EditorAssistantSourceReference",
    "EditorAssistantValidationIssue",
    "EditorAssistantValidationReport",
    "EditorIntent",
    "EditorPatchPath",
    "EditorPreviewState",
    "EditorValidationIssueCode",
    "EditorValidationStatus",
    "editor_assistant_failure_contract",
]
