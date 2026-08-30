"""Pure structured-edit contract for the contextual editor assistant.

This module deliberately has no database, provider, or content-store
dependency.  It defines the boundary between a selected editor target and a
future provider/apply implementation.  Preview produces a validated plan;
it never writes course or assessment content.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class PatchContractError(ValueError):
    """Safe, non-reflecting contract validation error."""


class StaleBaseVersionError(PatchContractError):
    """The preview/apply snapshot no longer matches the current target."""


class PatchIdempotencyCollisionError(PatchContractError):
    """A request or preview key was reused for a different payload."""


class PreviewInProgressError(PatchContractError):
    """An identical preview is already owned by another in-flight request."""


class PreviewClaimOwnershipError(PatchContractError):
    """A preview completion or release was attempted without its owner token."""


class PatchOperationType(StrEnum):
    REPLACE = "replace"
    APPEND = "append"
    REMOVE = "remove"


class EditorTargetEntityType(StrEnum):
    COURSE = "course"
    MODULE = "module"
    LESSON = "lesson"
    QUIZ = "quiz"
    QUESTION = "question"
    ANSWER_OPTION = "answer_option"
    EXPLANATION = "explanation"


class ContentLifecycle(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class PatchApplicabilityStatus(StrEnum):
    APPLICABLE = "applicable"
    REQUIRES_NEW_DRAFT_REVISION = "requires_new_draft_revision"
    INVALID = "invalid"


class ValidationStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class PreviewClaimState(StrEnum):
    NEW_OWNER = "new_owner"
    COMPLETED = "completed"
    PENDING = "pending"


class PatchValidationIssueCode(StrEnum):
    INVALID_OPERATION = "invalid_operation"
    OUT_OF_SCOPE = "out_of_scope"
    MISSING_SOURCE_EVIDENCE = "missing_source_evidence"
    PROTECTED_FIELD = "protected_field"
    INVALID_BASE_SNAPSHOT = "invalid_base_snapshot"
    PUBLISHED_CONTENT_REQUIRES_DRAFT = "published_content_requires_draft"
    PROVIDER_OUTPUT_INVALID = "provider_output_invalid"


_OPAQUE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_FIELD_PATH = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$")
_MAX_SCOPE_LENGTH = 160
_MAX_OPERATIONS = 32
_MAX_SOURCE_REFERENCES = 64


def _require_opaque(value: str, *, key: bool = False) -> str:
    if not isinstance(value, str):
        raise PatchContractError("Invalid editor contract value")
    normalized = value.strip()
    if not normalized or len(normalized) > 120:
        raise PatchContractError("Invalid editor contract value")
    if key and not _OPAQUE_KEY.fullmatch(normalized):
        raise PatchContractError("Invalid editor contract value")
    return normalized


def _require_code(value: str) -> str:
    normalized = _require_opaque(value)
    if not _CODE.fullmatch(normalized):
        raise PatchContractError("Invalid editor provenance value")
    return normalized


def _require_field_path(value: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise PatchContractError("Invalid editor field path")
    normalized = value.strip()
    if allow_empty and not normalized:
        return normalized
    if not normalized or len(normalized) > _MAX_SCOPE_LENGTH or not _FIELD_PATH.fullmatch(normalized):
        raise PatchContractError("Invalid editor field path")
    return normalized


def _path_is_within(path: str, scope: str) -> bool:
    return path == scope or path.startswith(f"{scope}.")


@dataclass(frozen=True)
class EditorTarget:
    """The exact selected entity and field scope for one edit request."""

    entity_type: EditorTargetEntityType
    entity_id: str
    selected_scope: str

    def __post_init__(self) -> None:
        try:
            entity_type = EditorTargetEntityType(self.entity_type)
        except (TypeError, ValueError):
            raise PatchContractError("Invalid editor target") from None
        object.__setattr__(self, "entity_type", entity_type)
        object.__setattr__(self, "entity_id", _require_opaque(self.entity_id, key=True))
        object.__setattr__(
            self,
            "selected_scope",
            _require_field_path(self.selected_scope),
        )


@dataclass(frozen=True)
class ContentVersionSnapshot:
    """Immutable identity of the content observed before preview."""

    target: EditorTarget
    version: str
    content_hash: str
    lifecycle: ContentLifecycle

    def __post_init__(self) -> None:
        if not isinstance(self.target, EditorTarget):
            raise PatchContractError("Invalid editor base snapshot")
        object.__setattr__(self, "version", _require_opaque(self.version))
        if not isinstance(self.content_hash, str) or not _SHA256.fullmatch(self.content_hash):
            raise PatchContractError("Invalid editor base snapshot")
        try:
            lifecycle = ContentLifecycle(self.lifecycle)
        except (TypeError, ValueError):
            raise PatchContractError("Invalid editor base snapshot") from None
        object.__setattr__(self, "lifecycle", lifecycle)


@dataclass(frozen=True)
class OperationConstraints:
    """Explicit server-side limits for the proposed field operations."""

    allowed_operations: tuple[PatchOperationType, ...] = (
        PatchOperationType.REPLACE,
        PatchOperationType.APPEND,
        PatchOperationType.REMOVE,
    )
    allowed_field_paths: tuple[str, ...] = ()
    protected_field_paths: tuple[str, ...] = ()
    require_source_evidence: bool = True
    max_operations: int = _MAX_OPERATIONS

    def __post_init__(self) -> None:
        try:
            operations = tuple(PatchOperationType(item) for item in self.allowed_operations)
        except (TypeError, ValueError):
            raise PatchContractError("Invalid editor operation constraints") from None
        if not operations or len(set(operations)) != len(operations):
            raise PatchContractError("Invalid editor operation constraints")
        object.__setattr__(self, "allowed_operations", operations)

        for field_name in ("allowed_field_paths", "protected_field_paths"):
            values = tuple(_require_field_path(item) for item in getattr(self, field_name))
            if len(set(values)) != len(values):
                raise PatchContractError("Invalid editor operation constraints")
            object.__setattr__(self, field_name, values)

        if not isinstance(self.require_source_evidence, bool):
            raise PatchContractError("Invalid editor operation constraints")
        if (
            isinstance(self.max_operations, bool)
            or not isinstance(self.max_operations, int)
            or self.max_operations < 1
            or self.max_operations > _MAX_OPERATIONS
        ):
            raise PatchContractError("Invalid editor operation constraints")


@dataclass(frozen=True)
class StructuredEditCommand:
    """Provider-independent command for one selected-target preview."""

    request_key: str
    preview_key: str
    target: EditorTarget
    base_snapshot: ContentVersionSnapshot
    operation_constraints: OperationConstraints
    instruction_text: str
    locale: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_key", _require_opaque(self.request_key, key=True))
        object.__setattr__(self, "preview_key", _require_opaque(self.preview_key, key=True))
        if not isinstance(self.target, EditorTarget) or self.base_snapshot.target != self.target:
            raise PatchContractError("Invalid editor command target")
        if not isinstance(self.operation_constraints, OperationConstraints):
            raise PatchContractError("Invalid editor operation constraints")
        if not isinstance(self.instruction_text, str):
            raise PatchContractError("Invalid editor instruction")
        instruction = self.instruction_text.strip()
        if not instruction or len(instruction) > 8_000:
            raise PatchContractError("Invalid editor instruction")
        object.__setattr__(self, "instruction_text", instruction)
        if not isinstance(self.locale, str) or not self.locale.strip() or len(self.locale.strip()) > 16:
            raise PatchContractError("Invalid editor locale")
        object.__setattr__(self, "locale", self.locale.strip())


@dataclass(frozen=True)
class SourceEvidenceReference:
    """Opaque source locator; source text is intentionally not part of the contract."""

    source_id: str
    locator: str
    evidence_hash: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _require_opaque(self.source_id, key=True))
        object.__setattr__(self, "locator", _require_opaque(self.locator))
        if self.evidence_hash is not None and not _SHA256.fullmatch(self.evidence_hash):
            raise PatchContractError("Invalid editor source reference")


@dataclass(frozen=True)
class PatchOperation:
    """One exact field operation with preview-comparable before/after data."""

    target: EditorTarget
    field_path: str
    operation: PatchOperationType
    before_hash: str | None = None
    after_hash: str | None = None
    before_value: Any = None
    after_value: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.target, EditorTarget):
            raise PatchContractError("Invalid editor patch operation")
        object.__setattr__(self, "field_path", _require_field_path(self.field_path))
        try:
            operation = PatchOperationType(self.operation)
        except (TypeError, ValueError):
            raise PatchContractError("Invalid editor patch operation") from None
        object.__setattr__(self, "operation", operation)
        for name in ("before_hash", "after_hash"):
            value = getattr(self, name)
            if value is not None and not _SHA256.fullmatch(value):
                raise PatchContractError("Invalid editor patch operation")
        if self.before_hash is None and self.before_value is None:
            raise PatchContractError("Invalid editor patch operation")
        if self.after_hash is None and self.after_value is None:
            raise PatchContractError("Invalid editor patch operation")


@dataclass(frozen=True)
class ValidationIssue:
    code: PatchValidationIssueCode
    blocking: bool

    def __post_init__(self) -> None:
        try:
            code = PatchValidationIssueCode(self.code)
        except (TypeError, ValueError):
            raise PatchContractError("Invalid editor validation report") from None
        object.__setattr__(self, "code", code)
        if not isinstance(self.blocking, bool):
            raise PatchContractError("Invalid editor validation report")


@dataclass(frozen=True)
class ValidationReport:
    status: ValidationStatus
    issues: tuple[ValidationIssue, ...] = ()
    validator_version: str = "contract-v1"

    def __post_init__(self) -> None:
        try:
            status = ValidationStatus(self.status)
        except (TypeError, ValueError):
            raise PatchContractError("Invalid editor validation report") from None
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "issues", tuple(self.issues))
        object.__setattr__(self, "validator_version", _require_code(self.validator_version))
        if not all(isinstance(issue, ValidationIssue) for issue in self.issues):
            raise PatchContractError("Invalid editor validation report")
        has_issues = bool(self.issues)
        has_blocking = any(issue.blocking for issue in self.issues)
        if status is ValidationStatus.PASS and has_issues:
            raise PatchContractError("Invalid editor validation report")
        if status is ValidationStatus.WARN and (not has_issues or has_blocking):
            raise PatchContractError("Invalid editor validation report")
        if status is ValidationStatus.FAIL and (not has_issues or not has_blocking):
            raise PatchContractError("Invalid editor validation report")


@dataclass(frozen=True)
class ProviderProvenance:
    provider: str
    model_id: str
    prompt_version: str
    generator_version: str

    def __post_init__(self) -> None:
        for name in ("provider", "model_id", "prompt_version", "generator_version"):
            object.__setattr__(self, name, _require_code(getattr(self, name)))


@dataclass(frozen=True)
class StructuredEditPatch:
    """Validated, preview-only patch proposed against one immutable snapshot."""

    request_key: str
    preview_key: str
    target: EditorTarget
    base_snapshot: ContentVersionSnapshot
    operations: tuple[PatchOperation, ...]
    source_evidence: tuple[SourceEvidenceReference, ...]
    validation_report: ValidationReport
    provider_provenance: ProviderProvenance
    applicability_status: PatchApplicabilityStatus

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_key", _require_opaque(self.request_key, key=True))
        object.__setattr__(self, "preview_key", _require_opaque(self.preview_key, key=True))
        if not isinstance(self.target, EditorTarget) or self.base_snapshot.target != self.target:
            raise PatchContractError("Invalid editor patch target")
        operations = tuple(self.operations)
        if not operations or len(operations) > _MAX_OPERATIONS:
            raise PatchContractError("Invalid editor patch operations")
        if not all(isinstance(item, PatchOperation) for item in operations):
            raise PatchContractError("Invalid editor patch operations")
        object.__setattr__(self, "operations", operations)
        evidence = tuple(self.source_evidence)
        if len(evidence) > _MAX_SOURCE_REFERENCES or not all(
            isinstance(item, SourceEvidenceReference) for item in evidence
        ):
            raise PatchContractError("Invalid editor source evidence")
        object.__setattr__(self, "source_evidence", evidence)
        if not isinstance(self.validation_report, ValidationReport):
            raise PatchContractError("Invalid editor validation report")
        if not isinstance(self.provider_provenance, ProviderProvenance):
            raise PatchContractError("Invalid editor provenance")
        try:
            status = PatchApplicabilityStatus(self.applicability_status)
        except (TypeError, ValueError):
            raise PatchContractError("Invalid editor applicability status") from None
        object.__setattr__(self, "applicability_status", status)


class EditPatchProvider(Protocol):
    """Minimal provider seam; production routing is intentionally not here."""

    def propose_patch(self, command: StructuredEditCommand) -> StructuredEditPatch:
        """Return a structured proposal without mutating content."""


@dataclass(frozen=True)
class RequestIdentityReservation:
    """Result of an atomic request-key reservation/read operation."""

    request_id: str
    is_new: bool


@dataclass(frozen=True)
class PreviewClaim:
    """Atomic claim result returned before any provider call."""

    state: PreviewClaimState
    payload_fingerprint: str
    claim_token: str | None = None
    patch: StructuredEditPatch | None = None

    def __post_init__(self) -> None:
        try:
            state = PreviewClaimState(self.state)
        except (TypeError, ValueError):
            raise PatchContractError("Invalid editor preview claim") from None
        object.__setattr__(self, "state", state)
        if not _SHA256.fullmatch(self.payload_fingerprint):
            raise PatchContractError("Invalid editor preview claim")
        if state is PreviewClaimState.NEW_OWNER:
            if self.claim_token is None:
                raise PatchContractError("Invalid editor preview claim")
            object.__setattr__(
                self, "claim_token", _require_opaque(self.claim_token, key=True)
            )
        elif self.claim_token is not None:
            raise PatchContractError("Invalid editor preview claim")


class EditorIdempotencyStore(Protocol):
    """Atomic storage seam for request identity and preview reservations.

    A durable implementation must make each reserve/read operation atomic
    against concurrent callers and must raise
    :class:`PatchIdempotencyCollisionError` for a key/payload mismatch.  Step
    2 provides no process-local or production implementation of this seam.
    """

    def reserve_request(
        self,
        request_key: str,
        payload_fingerprint: str,
        requested_request_id: str,
    ) -> RequestIdentityReservation:
        """Atomically reserve or read the canonical request identity."""

    def claim_preview(
        self,
        request_key: str,
        preview_key: str,
        payload_fingerprint: str,
    ) -> PreviewClaim:
        """Atomically claim, read-complete, or observe-pending preview state."""

    def complete_preview(
        self,
        request_key: str,
        preview_key: str,
        payload_fingerprint: str,
        claim_token: str,
        patch: StructuredEditPatch,
    ) -> StructuredEditPatch:
        """Atomically complete an owned preview and return its canonical patch."""

    def fail_preview(
        self,
        request_key: str,
        preview_key: str,
        payload_fingerprint: str,
        claim_token: str,
    ) -> None:
        """Atomically mark an owned preview failed and retryable."""

    def release_preview(
        self,
        request_key: str,
        preview_key: str,
        payload_fingerprint: str,
        claim_token: str,
    ) -> None:
        """Atomically release an owned pending preview without content."""


@dataclass(frozen=True)
class PatchApplicationPlan:
    """A pure apply preflight result; it is not a content mutation."""

    patch: StructuredEditPatch
    destination: str
    new_draft_revision_id: str | None
    mutates_content: bool = False


def _validate_patch_against_command(
    command: StructuredEditCommand,
    patch: StructuredEditPatch,
) -> StructuredEditPatch:
    if patch.request_key != command.request_key or patch.preview_key != command.preview_key:
        raise PatchContractError("Provider output does not match the editor command")
    if patch.target != command.target or patch.base_snapshot != command.base_snapshot:
        raise PatchContractError("Provider output does not match the editor command")
    if command.operation_constraints.require_source_evidence and not patch.source_evidence:
        raise PatchContractError("Editor patch requires source evidence")
    constraints = command.operation_constraints
    if len(patch.operations) > constraints.max_operations:
        raise PatchContractError("Editor patch exceeds the operation limit")
    for operation in patch.operations:
        if operation.target != command.target:
            raise PatchContractError("Editor patch is outside the selected target")
        if operation.operation not in constraints.allowed_operations:
            raise PatchContractError("Editor patch contains a disallowed operation")
        if not _path_is_within(operation.field_path, command.target.selected_scope):
            raise PatchContractError("Editor patch is outside the selected scope")
        if constraints.allowed_field_paths and operation.field_path not in constraints.allowed_field_paths:
            raise PatchContractError("Editor patch contains a disallowed field")
        if any(
            _path_is_within(operation.field_path, protected)
            for protected in constraints.protected_field_paths
        ):
            raise PatchContractError("Editor patch changes a protected field")
    if patch.validation_report.status is ValidationStatus.FAIL:
        raise PatchContractError("Editor patch failed deterministic validation")
    return patch


def preview_edit(
    command: StructuredEditCommand,
    provider: EditPatchProvider,
    current_snapshot: ContentVersionSnapshot,
) -> StructuredEditPatch:
    """Build a validated preview without changing course or quiz content.

    The snapshot is checked before the provider is called.  This makes a
    stale preview impossible to mark applicable and prevents provider work on
    an obsolete base version.
    """

    if current_snapshot != command.base_snapshot:
        raise StaleBaseVersionError("Editor base version is stale")
    patch = provider.propose_patch(command)
    if not isinstance(patch, StructuredEditPatch):
        raise PatchContractError("Provider output is not a structured editor patch")
    patch = _validate_patch_against_command(command, patch)
    if command.base_snapshot.lifecycle is ContentLifecycle.PUBLISHED:
        if patch.applicability_status is not PatchApplicabilityStatus.REQUIRES_NEW_DRAFT_REVISION:
            raise PatchContractError("Published content requires a new draft revision")
    elif patch.applicability_status is not PatchApplicabilityStatus.APPLICABLE:
        raise PatchContractError("Draft patch has an invalid applicability status")
    return patch


def prepare_patch_application(
    command: StructuredEditCommand,
    patch: StructuredEditPatch,
    current_snapshot: ContentVersionSnapshot,
    *,
    new_draft_revision_id: str | None = None,
) -> PatchApplicationPlan:
    """Validate an apply request and return a non-mutating application plan."""

    if current_snapshot != command.base_snapshot:
        raise StaleBaseVersionError("Editor base version is stale")
    _validate_patch_against_command(command, patch)
    if current_snapshot != patch.base_snapshot:
        raise StaleBaseVersionError("Editor base version is stale")
    if patch.base_snapshot.lifecycle is ContentLifecycle.PUBLISHED:
        if new_draft_revision_id is None:
            raise PatchContractError("Published content requires a new draft revision")
        revision_id = _require_opaque(new_draft_revision_id)
        return PatchApplicationPlan(
            patch=patch,
            destination="new_draft_revision",
            new_draft_revision_id=revision_id,
        )
    if patch.applicability_status is not PatchApplicabilityStatus.APPLICABLE:
        raise PatchContractError("Editor patch is not applicable")
    return PatchApplicationPlan(
        patch=patch,
        destination="current_draft",
        new_draft_revision_id=None,
    )


def _request_payload_fingerprint(command: StructuredEditCommand) -> str:
    """Digest request payload; request and preview keys are not payload."""

    payload = {
        "target_type": command.target.entity_type.value,
        "target_id": command.target.entity_id,
        "selected_scope": command.target.selected_scope,
        "base_version": command.base_snapshot.version,
        "base_hash": command.base_snapshot.content_hash,
        "lifecycle": command.base_snapshot.lifecycle.value,
        "constraints": {
            "allowed_operations": [item.value for item in command.operation_constraints.allowed_operations],
            "allowed_fields": list(command.operation_constraints.allowed_field_paths),
            "protected_fields": list(command.operation_constraints.protected_field_paths),
            "require_source_evidence": command.operation_constraints.require_source_evidence,
            "max_operations": command.operation_constraints.max_operations,
        },
        "instruction": command.instruction_text,
        "locale": command.locale,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _preview_payload_fingerprint(command: StructuredEditCommand) -> str:
    """Digest one preview payload, including its distinct preview key."""

    payload = {
        "request_payload": _request_payload_fingerprint(command),
        "preview_key": command.preview_key,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class RequestIdempotencyService:
    """Domain boundary for request-creation idempotency only."""

    def __init__(self, store: EditorIdempotencyStore):
        self._store = store

    def reserve(self, command: StructuredEditCommand, requested_request_id: str) -> RequestIdentityReservation:
        """Reserve/read one request identity using the normalized command."""

        return self._store.reserve_request(
            command.request_key,
            _request_payload_fingerprint(command),
            _require_opaque(requested_request_id, key=True),
        )


class PreviewIdempotencyGuard:
    """Preview idempotency boundary backed by an injected storage seam.

    This class intentionally does not provide in-memory storage.  Production
    persistence is an explicit implementation gap until a later application
    step supplies a durable :class:`EditorIdempotencyStore`.
    """

    def __init__(self, store: EditorIdempotencyStore):
        self._store = store

    def preview(
        self,
        command: StructuredEditCommand,
        provider: EditPatchProvider,
        current_snapshot: ContentVersionSnapshot,
    ) -> StructuredEditPatch:
        """Return the canonical patch for an exact preview retry."""

        if current_snapshot != command.base_snapshot:
            raise StaleBaseVersionError("Editor base version is stale")
        payload_fingerprint = _preview_payload_fingerprint(command)
        claim = self._store.claim_preview(
            command.request_key,
            command.preview_key,
            payload_fingerprint,
        )
        if claim.payload_fingerprint != payload_fingerprint:
            raise PatchIdempotencyCollisionError("Editor preview idempotency collision")
        if claim.state is PreviewClaimState.COMPLETED:
            if claim.patch is None:
                raise PatchContractError("Editor preview has invalid completion state")
            return _validate_patch_against_command(command, claim.patch)
        if claim.state is PreviewClaimState.PENDING:
            raise PreviewInProgressError("Editor preview is already in progress")
        if claim.claim_token is None:
            raise PatchContractError("Editor preview claim has no owner")
        try:
            patch = preview_edit(command, provider, current_snapshot)
            completed = self._store.complete_preview(
                command.request_key,
                command.preview_key,
                payload_fingerprint,
                claim.claim_token,
                patch,
            )
            return _validate_patch_against_command(command, completed)
        except PatchContractError:
            self._store.fail_preview(
                command.request_key,
                command.preview_key,
                payload_fingerprint,
                claim.claim_token,
            )
            raise
        except Exception:
            self._store.fail_preview(
                command.request_key,
                command.preview_key,
                payload_fingerprint,
                claim.claim_token,
            )
            raise PatchContractError("Editor provider failed") from None

def project_patch_analytics(patch: StructuredEditPatch) -> dict[str, Any]:
    """Return only normalized, non-content fields for product analytics."""

    return {
        "target_entity_type": patch.target.entity_type.value,
        "operation_count": len(patch.operations),
        "source_reference_count": len(patch.source_evidence),
        "validation_status": patch.validation_report.status.value,
        "applicability_status": patch.applicability_status.value,
        "content_lifecycle": patch.base_snapshot.lifecycle.value,
        "provider": patch.provider_provenance.provider,
        "model_id": patch.provider_provenance.model_id,
        "prompt_version": patch.provider_provenance.prompt_version,
        "generator_version": patch.provider_provenance.generator_version,
        "validator_version": patch.validation_report.validator_version,
    }


__all__ = [
    "ContentLifecycle",
    "ContentVersionSnapshot",
    "EditorTarget",
    "EditorTargetEntityType",
    "EditPatchProvider",
    "EditorIdempotencyStore",
    "OperationConstraints",
    "PatchApplicabilityStatus",
    "PatchContractError",
    "PatchIdempotencyCollisionError",
    "PreviewClaimOwnershipError",
    "PatchOperation",
    "PatchOperationType",
    "PatchApplicationPlan",
    "PatchValidationIssueCode",
    "PreviewIdempotencyGuard",
    "PreviewClaim",
    "PreviewClaimState",
    "PreviewInProgressError",
    "ProviderProvenance",
    "RequestIdentityReservation",
    "RequestIdempotencyService",
    "SourceEvidenceReference",
    "StaleBaseVersionError",
    "StructuredEditCommand",
    "StructuredEditPatch",
    "ValidationIssue",
    "ValidationReport",
    "ValidationStatus",
    "prepare_patch_application",
    "preview_edit",
    "project_patch_analytics",
]
