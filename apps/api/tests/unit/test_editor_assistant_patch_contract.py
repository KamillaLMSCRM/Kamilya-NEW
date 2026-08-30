"""Pure Step 2 contract tests; no database, network, or real provider."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from app.modules.editor_assistant.patch_contract import (
    ContentLifecycle,
    ContentVersionSnapshot,
    EditorTarget,
    EditorTargetEntityType,
    OperationConstraints,
    PatchApplicabilityStatus,
    PatchContractError,
    PatchIdempotencyCollisionError,
    PatchOperation,
    PatchOperationType,
    PatchValidationIssueCode,
    PreviewClaim,
    PreviewClaimOwnershipError,
    PreviewClaimState,
    PreviewIdempotencyGuard,
    PreviewInProgressError,
    ProviderProvenance,
    RequestIdempotencyService,
    RequestIdentityReservation,
    SourceEvidenceReference,
    StaleBaseVersionError,
    StructuredEditCommand,
    StructuredEditPatch,
    ValidationIssue,
    ValidationReport,
    ValidationStatus,
    _preview_payload_fingerprint,
    prepare_patch_application,
    preview_edit,
    project_patch_analytics,
)

BASE_HASH = "a" * 64
AFTER_HASH = "b" * 64


def _command(*, lifecycle: ContentLifecycle = ContentLifecycle.DRAFT) -> StructuredEditCommand:
    target = EditorTarget(
        EditorTargetEntityType.QUESTION,
        "question-1",
        "question.answer_options",
    )
    return StructuredEditCommand(
        request_key="request-1",
        preview_key="preview-1",
        target=target,
        base_snapshot=ContentVersionSnapshot(
            target=target,
            version="course-v3",
            content_hash=BASE_HASH,
            lifecycle=lifecycle,
        ),
        operation_constraints=OperationConstraints(
            allowed_field_paths=("question.answer_options",),
            protected_field_paths=("question.correct_answer",),
        ),
        instruction_text="Make the distractors similarly detailed.",
        locale="ru-RU",
    )


def _patch(command: StructuredEditCommand, *, status: PatchApplicabilityStatus | None = None):
    return StructuredEditPatch(
        request_key=command.request_key,
        preview_key=command.preview_key,
        target=command.target,
        base_snapshot=command.base_snapshot,
        operations=(
            PatchOperation(
                target=command.target,
                field_path="question.answer_options",
                operation=PatchOperationType.REPLACE,
                before_hash=BASE_HASH,
                after_hash=AFTER_HASH,
                before_value=["Short"],
                after_value=["A similarly detailed distractor"],
            ),
        ),
        source_evidence=(SourceEvidenceReference("doc-1", "page:4"),),
        validation_report=ValidationReport(ValidationStatus.PASS),
        provider_provenance=ProviderProvenance(
            provider="fake.test",
            model_id="fake-editor-v1",
            prompt_version="prompt-v1",
            generator_version="generator-v1",
        ),
        applicability_status=status
        or (
            PatchApplicabilityStatus.REQUIRES_NEW_DRAFT_REVISION
            if command.base_snapshot.lifecycle is ContentLifecycle.PUBLISHED
            else PatchApplicabilityStatus.APPLICABLE
        ),
    )


class FakeProvider:
    def __init__(self):
        self.calls = 0

    def propose_patch(self, command: StructuredEditCommand) -> StructuredEditPatch:
        self.calls += 1
        return _patch(command)


class StaticProvider:
    def __init__(self, patch):
        self.patch = patch

    def propose_patch(self, command):
        return self.patch


class RaisingProvider:
    def __init__(self):
        self.calls = 0

    def propose_patch(self, command):
        self.calls += 1
        raise RuntimeError("provider content secret claim-token-1")


class InvalidPatchProvider:
    def __init__(self):
        self.calls = 0

    def propose_patch(self, command):
        self.calls += 1
        return object()


class NonProductionInMemoryIdempotencyStore:
    """Test-only store; not a production persistence implementation."""

    def __init__(self):
        self.requests = {}
        self.previews = {}
        self.next_claim_number = 1

    def reserve_request(self, request_key, payload_fingerprint, requested_request_id):
        existing = self.requests.get(request_key)
        if existing is not None:
            if existing[0] != payload_fingerprint:
                raise PatchIdempotencyCollisionError("Editor request idempotency collision")
            return RequestIdentityReservation(existing[1], is_new=False)
        self.requests[request_key] = (payload_fingerprint, requested_request_id)
        return RequestIdentityReservation(requested_request_id, is_new=True)

    def claim_preview(self, request_key, preview_key, payload_fingerprint):
        existing = self.previews.get((request_key, preview_key))
        if existing is None:
            claim_token = f"claim-token-{self.next_claim_number}"
            self.next_claim_number += 1
            self.previews[(request_key, preview_key)] = (
                payload_fingerprint,
                None,
                claim_token,
            )
            return PreviewClaim(
                PreviewClaimState.NEW_OWNER,
                payload_fingerprint,
                claim_token=claim_token,
            )
        if existing[0] != payload_fingerprint:
            raise PatchIdempotencyCollisionError("Editor preview idempotency collision")
        if existing[1] is None:
            return PreviewClaim(PreviewClaimState.PENDING, existing[0])
        return PreviewClaim(
            PreviewClaimState.COMPLETED,
            existing[0],
            patch=existing[1],
        )

    def complete_preview(
        self,
        request_key,
        preview_key,
        payload_fingerprint,
        claim_token,
        patch,
    ):
        key = (request_key, preview_key)
        existing = self.previews.get(key)
        if (
            existing is None
            or existing[0] != payload_fingerprint
            or existing[2] != claim_token
            or existing[1] is not None
        ):
            raise PreviewClaimOwnershipError("Editor preview claim ownership failure")
        self.previews[key] = (payload_fingerprint, patch, None)
        return patch

    def _release_owned(self, request_key, preview_key, payload_fingerprint, claim_token):
        key = (request_key, preview_key)
        existing = self.previews.get(key)
        if (
            existing is None
            or existing[0] != payload_fingerprint
            or existing[2] != claim_token
            or existing[1] is not None
        ):
            raise PreviewClaimOwnershipError("Editor preview claim ownership failure")
        del self.previews[key]

    def fail_preview(self, request_key, preview_key, payload_fingerprint, claim_token):
        self._release_owned(request_key, preview_key, payload_fingerprint, claim_token)

    def release_preview(self, request_key, preview_key, payload_fingerprint, claim_token):
        self._release_owned(request_key, preview_key, payload_fingerprint, claim_token)


def test_command_and_snapshot_are_immutable_and_explicit():
    command = _command()
    assert command.target.entity_type is EditorTargetEntityType.QUESTION
    assert command.target.selected_scope == "question.answer_options"
    assert command.base_snapshot.version == "course-v3"
    with pytest.raises(FrozenInstanceError):
        command.base_snapshot.version = "course-v4"


def test_preview_is_pure_and_deterministic_fake_provider_is_the_only_provider():
    command = _command()
    provider = FakeProvider()
    patch = preview_edit(command, provider, command.base_snapshot)
    assert patch.applicability_status is PatchApplicabilityStatus.APPLICABLE
    assert patch.operations[0].field_path == "question.answer_options"
    assert provider.calls == 1


def test_stale_snapshot_is_rejected_before_provider_is_called():
    command = _command()
    provider = FakeProvider()
    current = ContentVersionSnapshot(
        target=command.target,
        version="course-v4",
        content_hash=AFTER_HASH,
        lifecycle=ContentLifecycle.DRAFT,
    )
    with pytest.raises(StaleBaseVersionError):
        preview_edit(command, provider, current)
    assert provider.calls == 0


def test_scope_escape_and_protected_field_are_fail_closed():
    command = _command()
    valid = _patch(command)

    escaped = StructuredEditPatch(
        **{
            **valid.__dict__,
            "operations": (
                PatchOperation(
                    target=command.target,
                    field_path="question.explanation",
                    operation=PatchOperationType.REPLACE,
                    before_hash=BASE_HASH,
                    after_hash=AFTER_HASH,
                ),
            ),
        }
    )
    with pytest.raises(ValueError, match="outside the selected scope"):
        preview_edit(command, StaticProvider(escaped), command.base_snapshot)

    protected_target = EditorTarget(
        EditorTargetEntityType.QUESTION,
        "question-1",
        "question.correct_answer",
    )
    protected_command = StructuredEditCommand(
        request_key=command.request_key,
        preview_key=command.preview_key,
        target=protected_target,
        base_snapshot=ContentVersionSnapshot(
            target=protected_target,
            version=command.base_snapshot.version,
            content_hash=BASE_HASH,
            lifecycle=ContentLifecycle.DRAFT,
        ),
        operation_constraints=OperationConstraints(
            allowed_field_paths=("question.correct_answer",),
            protected_field_paths=("question.correct_answer",),
        ),
        instruction_text=command.instruction_text,
        locale=command.locale,
    )
    protected = StructuredEditPatch(
        **{
            **valid.__dict__,
            "target": protected_command.target,
            "base_snapshot": protected_command.base_snapshot,
            "request_key": protected_command.request_key,
            "preview_key": protected_command.preview_key,
            "operations": (
                PatchOperation(
                    target=protected_command.target,
                    field_path="question.correct_answer",
                    operation=PatchOperationType.REPLACE,
                    before_hash=BASE_HASH,
                    after_hash=AFTER_HASH,
                ),
            ),
        }
    )
    with pytest.raises(ValueError, match="protected field"):
        preview_edit(
            protected_command,
            StaticProvider(protected),
            protected_command.base_snapshot,
        )


def test_prepare_revalidates_originating_command_and_cannot_accept_forged_patch():
    command = _command()
    forged = StructuredEditPatch(
        **{
            **_patch(command).__dict__,
            "operations": (
                PatchOperation(
                    target=command.target,
                    field_path="question.explanation",
                    operation=PatchOperationType.REPLACE,
                    before_hash=BASE_HASH,
                    after_hash=AFTER_HASH,
                ),
            ),
        }
    )
    with pytest.raises(ValueError, match="outside the selected scope"):
        prepare_patch_application(command, forged, command.base_snapshot)


def test_prepare_enforces_command_specific_operation_limit():
    command = StructuredEditCommand(
        **{**_command().__dict__, "operation_constraints": OperationConstraints(
            allowed_field_paths=("question.answer_options",),
            max_operations=1,
        )}
    )
    single = _patch(command)
    two_operations = StructuredEditPatch(
        **{
            **single.__dict__,
            "operations": (single.operations[0], single.operations[0]),
        }
    )
    with pytest.raises(ValueError, match="operation limit"):
        prepare_patch_application(command, two_operations, command.base_snapshot)


def test_published_content_requires_a_new_draft_and_never_overwrites_in_place():
    command = _command(lifecycle=ContentLifecycle.PUBLISHED)
    provider = FakeProvider()
    patch = preview_edit(command, provider, command.base_snapshot)
    assert patch.applicability_status is PatchApplicabilityStatus.REQUIRES_NEW_DRAFT_REVISION
    with pytest.raises(ValueError, match="new draft revision"):
        prepare_patch_application(command, patch, command.base_snapshot)
    plan = prepare_patch_application(
        command,
        patch,
        command.base_snapshot,
        new_draft_revision_id="draft-v4",
    )
    assert plan.destination == "new_draft_revision"
    assert plan.mutates_content is False


def test_preview_idempotency_returns_same_patch_and_rejects_payload_collision():
    command = _command()
    provider = FakeProvider()
    store = NonProductionInMemoryIdempotencyStore()
    guard = PreviewIdempotencyGuard(store)
    first = guard.preview(command, provider, command.base_snapshot)
    retry_provider = FakeProvider()
    second = guard.preview(command, retry_provider, command.base_snapshot)
    assert second is first
    assert provider.calls == 1
    assert retry_provider.calls == 0

    collision_command = StructuredEditCommand(
        **{**command.__dict__, "instruction_text": "A different request."}
    )
    with pytest.raises(PatchIdempotencyCollisionError) as collision_error:
        guard.preview(collision_command, provider, command.base_snapshot)
    assert "A different request." not in str(collision_error.value)

    with pytest.raises(StaleBaseVersionError):
        guard.preview(
            command,
            provider,
            ContentVersionSnapshot(
                target=command.target,
                version="course-v4",
                content_hash=AFTER_HASH,
                lifecycle=ContentLifecycle.DRAFT,
            ),
        )


def test_request_idempotency_is_separate_and_new_preview_key_is_allowed():
    command = _command()
    store = NonProductionInMemoryIdempotencyStore()
    requests = RequestIdempotencyService(store)
    first = requests.reserve(command, "request-id-1")
    replay = requests.reserve(command, "request-id-2")
    assert first.request_id == replay.request_id == "request-id-1"
    assert first.is_new is True
    assert replay.is_new is False

    changed_target = EditorTarget(
        EditorTargetEntityType.QUESTION,
        "question-2",
        "question.answer_options",
    )
    changed_target_command = replace(
        command,
        target=changed_target,
        base_snapshot=ContentVersionSnapshot(
            target=changed_target,
            version=command.base_snapshot.version,
            content_hash=BASE_HASH,
            lifecycle=ContentLifecycle.DRAFT,
        ),
    )
    changed_base_command = replace(
        command,
        base_snapshot=ContentVersionSnapshot(
            target=command.target,
            version="course-v4",
            content_hash=AFTER_HASH,
            lifecycle=ContentLifecycle.DRAFT,
        ),
    )
    changed_constraints_command = replace(
        command,
        operation_constraints=OperationConstraints(
            allowed_field_paths=("question.answer_options",),
            max_operations=1,
        ),
    )
    changed_commands = (
        changed_target_command,
        replace(command, instruction_text="A different request."),
        changed_constraints_command,
        changed_base_command,
        replace(command, locale="kk-KZ"),
    )
    for changed in changed_commands:
        with pytest.raises(PatchIdempotencyCollisionError) as collision:
            requests.reserve(changed, "request-id-3")
        assert "question-2" not in str(collision.value)
        assert "A different request." not in str(collision.value)
        assert "course-v4" not in str(collision.value)
        assert "kk-KZ" not in str(collision.value)

    new_preview = StructuredEditCommand(
        **{**command.__dict__, "preview_key": "preview-2"}
    )
    provider = FakeProvider()
    guard = PreviewIdempotencyGuard(store)
    guard.preview(new_preview, provider, new_preview.base_snapshot)
    assert provider.calls == 1


def test_new_preview_key_keeps_the_same_request_identity():
    command = _command()
    store = NonProductionInMemoryIdempotencyStore()
    requests = RequestIdempotencyService(store)
    first = requests.reserve(command, "request-id-1")
    new_preview = replace(command, preview_key="preview-2")
    replay = requests.reserve(new_preview, "request-id-2")
    assert first.request_id == replay.request_id == "request-id-1"
    assert replay.is_new is False


def test_pending_preview_claim_rejects_without_invoking_provider():
    command = _command()
    store = NonProductionInMemoryIdempotencyStore()
    fingerprint = _preview_payload_fingerprint(command)
    claim = store.claim_preview(command.request_key, command.preview_key, fingerprint)
    assert claim.state is PreviewClaimState.NEW_OWNER

    provider = FakeProvider()
    with pytest.raises(PreviewInProgressError) as error:
        PreviewIdempotencyGuard(store).preview(
            command,
            provider,
            command.base_snapshot,
        )
    assert provider.calls == 0
    assert "Make the distractors" not in str(error.value)


def test_pending_and_completed_claims_do_not_expose_owner_token():
    command = _command()
    store = NonProductionInMemoryIdempotencyStore()
    fingerprint = _preview_payload_fingerprint(command)
    pending = store.claim_preview(command.request_key, command.preview_key, fingerprint)
    assert pending.state is PreviewClaimState.NEW_OWNER
    assert pending.claim_token is not None

    completed = store.complete_preview(
        command.request_key,
        command.preview_key,
        fingerprint,
        pending.claim_token,
        _patch(command),
    )
    assert completed is not None
    read_completed = store.claim_preview(
        command.request_key,
        command.preview_key,
        fingerprint,
    )
    assert read_completed.state is PreviewClaimState.COMPLETED
    assert read_completed.claim_token is None


def test_only_owner_can_complete_or_release_and_errors_do_not_reflect_token():
    command = _command()
    store = NonProductionInMemoryIdempotencyStore()
    fingerprint = _preview_payload_fingerprint(command)
    claim = store.claim_preview(command.request_key, command.preview_key, fingerprint)
    owner_token = claim.claim_token
    assert owner_token is not None
    wrong_token = "wrong-secret-token"

    with pytest.raises(PreviewClaimOwnershipError) as complete_error:
        store.complete_preview(
            command.request_key,
            command.preview_key,
            fingerprint,
            wrong_token,
            _patch(command),
        )
    assert wrong_token not in str(complete_error.value)
    with pytest.raises(PreviewClaimOwnershipError) as release_error:
        store.release_preview(
            command.request_key,
            command.preview_key,
            fingerprint,
            wrong_token,
        )
    assert wrong_token not in str(release_error.value)

    store.complete_preview(
        command.request_key,
        command.preview_key,
        fingerprint,
        owner_token,
        _patch(command),
    )
    with pytest.raises(PreviewClaimOwnershipError):
        store.complete_preview(
            command.request_key,
            command.preview_key,
            fingerprint,
            owner_token,
            _patch(command),
        )


def test_provider_exception_releases_claim_and_later_retry_can_become_owner():
    command = _command()
    store = NonProductionInMemoryIdempotencyStore()
    guard = PreviewIdempotencyGuard(store)
    failing_provider = RaisingProvider()
    with pytest.raises(PatchContractError) as error:
        guard.preview(command, failing_provider, command.base_snapshot)
    assert failing_provider.calls == 1
    assert store.previews == {}
    assert "provider content secret" not in str(error.value)
    assert "claim-token-1" not in str(error.value)

    retry_provider = FakeProvider()
    patch = guard.preview(command, retry_provider, command.base_snapshot)
    assert patch is not None
    assert retry_provider.calls == 1


def test_invalid_patch_releases_claim_and_later_retry_can_become_owner():
    command = _command()
    store = NonProductionInMemoryIdempotencyStore()
    guard = PreviewIdempotencyGuard(store)
    invalid_provider = InvalidPatchProvider()
    with pytest.raises(PatchContractError) as error:
        guard.preview(command, invalid_provider, command.base_snapshot)
    assert invalid_provider.calls == 1
    assert store.previews == {}
    assert "object" not in str(error.value)

    retry_provider = FakeProvider()
    guard.preview(command, retry_provider, command.base_snapshot)
    assert retry_provider.calls == 1


def test_validation_report_rejects_contradictory_states():
    warning = ValidationIssue(PatchValidationIssueCode.OUT_OF_SCOPE, blocking=False)
    blocking = ValidationIssue(PatchValidationIssueCode.OUT_OF_SCOPE, blocking=True)
    assert ValidationReport(ValidationStatus.PASS).status is ValidationStatus.PASS
    with pytest.raises(ValueError):
        ValidationReport(ValidationStatus.PASS, (warning,))
    with pytest.raises(ValueError):
        ValidationReport(ValidationStatus.WARN)
    with pytest.raises(ValueError):
        ValidationReport(ValidationStatus.WARN, (blocking,))
    with pytest.raises(ValueError):
        ValidationReport(ValidationStatus.FAIL, (warning,))
    assert ValidationReport(ValidationStatus.WARN, (warning,)).status is ValidationStatus.WARN
    assert ValidationReport(ValidationStatus.FAIL, (blocking,)).status is ValidationStatus.FAIL


def test_target_and_source_ids_require_opaque_key_format():
    with pytest.raises(ValueError):
        EditorTarget(EditorTargetEntityType.QUESTION, "question id", "question.text")
    with pytest.raises(ValueError):
        SourceEvidenceReference("doc id", "page:1")


def test_analytics_projection_excludes_instruction_content_and_entity_identity():
    command = _command()
    patch = _patch(command)
    projection = project_patch_analytics(patch)
    assert projection["target_entity_type"] == "question"
    assert projection["operation_count"] == 1
    assert "instruction_text" not in projection
    assert "question-1" not in projection.values()
    assert "Make the distractors similarly detailed." not in str(projection)


def test_validation_errors_do_not_reflect_untrusted_values():
    with pytest.raises(ValueError) as error:
        EditorTarget(EditorTargetEntityType.QUESTION, "id", "question..raw-text")
    assert "raw-text" not in str(error.value)

    issue = ValidationIssue(PatchValidationIssueCode.OUT_OF_SCOPE, blocking=True)
    assert ValidationReport(ValidationStatus.FAIL, (issue,)).status is ValidationStatus.FAIL
