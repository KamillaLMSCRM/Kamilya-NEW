"""Source-bound draft-lesson policy; neither preview nor confirmation writes.

Callers must resolve context from the authenticated tenant, never from a model
or client snapshot. Evidence membership proves identity, not semantic truth.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.modules.editor_assistant.patch_contract import (
    ContentLifecycle,
    ContentVersionSnapshot,
    EditorTarget,
    EditorTargetEntityType,
    EditPatchProvider,
    OperationConstraints,
    PatchApplicationPlan,
    PatchContractError,
    PatchOperationType,
    StructuredEditCommand,
    StructuredEditPatch,
    prepare_patch_application,
    preview_edit,
)

from .plan_contract import ActorContext, ConfirmationRequest, Fingerprint, Instruction, Revision

Text = Annotated[str, Field(strict=True, min_length=1, max_length=64_000)]
Locator = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=120, strip_whitespace=True)]
CorrectionVersion = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=120, strip_whitespace=True)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]


class CorrectionError(ValueError):
    """Fixed safe code, without untrusted provider or content details."""


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CorrectionEvidence(_Frozen):
    locator: Locator
    evidence_hash: Fingerprint


class CorrectionSource(_Frozen):
    document_id: UUID
    version: PositiveInt
    content_sha256: Fingerprint
    index_revision: PositiveInt
    evidence: tuple[CorrectionEvidence, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def unique_locators(self) -> Self:
        if len({item.locator for item in self.evidence}) != len(self.evidence):
            raise ValueError("duplicate_correction_evidence")
        return self


class LessonCorrectionContext(_Frozen):
    """Trusted server state; version tokens cover source binding/approval too."""

    tenant_id: UUID
    course_id: UUID
    module_id: UUID
    lesson_id: UUID
    course_version: CorrectionVersion
    lesson_version: CorrectionVersion
    lifecycle: Literal["draft", "published"]
    content: Text
    sources: tuple[CorrectionSource, ...] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def bounded_sources(self) -> Self:
        if not self.content.strip():
            raise ValueError("empty_correction_content")
        if len({source.document_id for source in self.sources}) != len(self.sources):
            raise ValueError("duplicate_correction_source")
        if sum(len(source.evidence) for source in self.sources) > 64:
            raise ValueError("too_many_correction_evidence")
        return self


class LessonCorrectionSnapshot(_Frozen):
    plan_id: UUID
    revision: Revision
    actor_id: UUID
    created_at: AwareDatetime
    expires_at: AwareDatetime
    context: LessonCorrectionContext
    instruction: Instruction
    locale: Literal["ru", "kk", "en"]

    @model_validator(mode="after")
    def bounded_lifetime(self) -> Self:
        lifetime = self.expires_at - self.created_at
        if not timedelta(0) < lifetime <= timedelta(minutes=15):
            raise ValueError("invalid_correction_lifetime")
        return self


@dataclass(frozen=True)
class LessonCorrectionPreview:
    snapshot: LessonCorrectionSnapshot
    patch: StructuredEditPatch
    fingerprint: str


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _command(snapshot: LessonCorrectionSnapshot) -> StructuredEditCommand:
    context = snapshot.context
    target = EditorTarget(EditorTargetEntityType.LESSON, str(context.lesson_id), "lesson.content")
    return StructuredEditCommand(
        request_key=str(snapshot.plan_id),
        preview_key=f"{snapshot.plan_id}:{snapshot.revision}",
        target=target,
        base_snapshot=ContentVersionSnapshot(
            target=target,
            version=context.lesson_version,
            content_hash=_text_hash(context.content),
            lifecycle=ContentLifecycle.DRAFT,
        ),
        operation_constraints=OperationConstraints(
            allowed_operations=(PatchOperationType.REPLACE,),
            allowed_field_paths=("lesson.content",),
            require_source_evidence=True,
            max_operations=1,
        ),
        instruction_text=snapshot.instruction,
        locale=snapshot.locale,
    )


def _check_context(
    snapshot: LessonCorrectionSnapshot,
    actor: ActorContext,
    current: LessonCorrectionContext,
    now: datetime,
) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise CorrectionError("invalid_confirmation_time")
    if actor.active_role != "methodologist":
        raise CorrectionError("role_denied")
    if actor.tenant_id != snapshot.context.tenant_id or actor.actor_id != snapshot.actor_id:
        raise CorrectionError("context_mismatch")
    if now < snapshot.created_at:
        raise CorrectionError("preview_not_yet_valid")
    if now >= snapshot.expires_at:
        raise CorrectionError("expired")
    if current != snapshot.context:
        raise CorrectionError("stale")
    if current.lifecycle != "draft":
        raise CorrectionError("new_draft_required")


def _validate_lesson_patch(snapshot: LessonCorrectionSnapshot, patch: StructuredEditPatch) -> None:
    """Strengthen generic editor validation with exact text and evidence identity."""

    operation = patch.operations[0]
    before = snapshot.context.content
    after = operation.after_value
    if (
        not isinstance(operation.before_value, str)
        or operation.before_value != before
        or operation.before_hash != _text_hash(before)
        or not isinstance(after, str)
        or not after.strip()
        or len(after) > 64_000
        or after == before
        or operation.after_hash != _text_hash(after)
    ):
        raise CorrectionError("invalid_content_change")
    admitted = {
        (str(source.document_id), evidence.locator, evidence.evidence_hash)
        for source in snapshot.context.sources
        for evidence in source.evidence
    }
    cited = [(item.source_id, item.locator, item.evidence_hash) for item in patch.source_evidence]
    if len(set(cited)) != len(cited) or any(item not in admitted for item in cited):
        raise CorrectionError("invalid_source_evidence")


def _fingerprint(snapshot: LessonCorrectionSnapshot, patch: StructuredEditPatch) -> str:
    payload = {"snapshot": snapshot.model_dump(mode="json"), "patch": asdict(patch)}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _text_hash(encoded)


def preview_lesson_correction(
    snapshot: LessonCorrectionSnapshot,
    *,
    actor: ActorContext,
    current: LessonCorrectionContext,
    provider: EditPatchProvider,
    now: datetime,
) -> LessonCorrectionPreview:
    """Admit exactly one draft-text suggestion without any content mutation."""

    _check_context(snapshot, actor, current, now)
    command = _command(snapshot)
    try:
        patch = preview_edit(command, provider, command.base_snapshot)
    except PatchContractError:
        raise CorrectionError("invalid_proposal") from None
    except Exception:
        raise CorrectionError("proposal_unavailable") from None
    _validate_lesson_patch(snapshot, patch)
    return LessonCorrectionPreview(snapshot, patch, _fingerprint(snapshot, patch))


def prepare_lesson_correction(
    preview: LessonCorrectionPreview,
    request: ConfirmationRequest,
    *,
    actor: ActorContext,
    current: LessonCorrectionContext,
    now: datetime,
) -> PatchApplicationPlan:
    """Return a pure plan, NOT a write or durable idempotency/concurrency claim."""

    snapshot = preview.snapshot
    _check_context(snapshot, actor, current, now)
    if request.plan_id != snapshot.plan_id:
        raise CorrectionError("plan_mismatch")
    if request.revision != snapshot.revision:
        raise CorrectionError("revision_mismatch")
    # Revalidate before hashing: generic patch values may otherwise contain
    # mutable containers. This slice admits strings only, never arbitrary JSON.
    command = _command(snapshot)
    try:
        plan = prepare_patch_application(command, preview.patch, command.base_snapshot)
    except PatchContractError:
        raise CorrectionError("invalid_proposal") from None
    _validate_lesson_patch(snapshot, preview.patch)
    actual = _fingerprint(snapshot, preview.patch)
    if preview.fingerprint != actual or request.fingerprint != actual:
        raise CorrectionError("fingerprint_mismatch")
    return plan
