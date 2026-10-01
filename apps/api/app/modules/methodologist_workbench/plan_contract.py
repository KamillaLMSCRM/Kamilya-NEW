"""Pure V1 intent, snapshot and confirmation contracts.

Only IntentCandidate and ConfirmationRequest are untrusted transport shapes.
PlanSnapshot/ActorContext must come from trusted server resolution, never a
client or model. ACCEPTED is not an execution grant: domain ownership, human
review, transactional claims and snapshot rechecks are future executor gates.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
)

Instruction = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=4000)]
VersionToken = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=160)]
Fingerprint = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-f0-9]{64}$")]
Revision = Annotated[int, Field(strict=True, ge=1)]
Action = Literal["create_course_draft", "propose_course_edit", "publish_course", "assign_course"]


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IntentCandidate(_FrozenContract):
    """Untrusted proposal only. Embedded instructions have no authority."""

    action: Action
    instruction: Instruction


class ReferenceSnapshot(_FrozenContract):
    """Server-resolved owned object and its authoritative version token."""

    object_id: UUID
    version_token: VersionToken


class CreateCourseDraft(_FrozenContract):
    action: Literal["create_course_draft"]
    sources: tuple[ReferenceSnapshot, ...] = Field(min_length=1, max_length=20)
    instruction: Instruction


class ProposeCourseEdit(_FrozenContract):
    action: Literal["propose_course_edit"]
    course: ReferenceSnapshot
    sources: tuple[ReferenceSnapshot, ...] = Field(max_length=20)
    instruction: Instruction


class PublishCourse(_FrozenContract):
    action: Literal["publish_course"]
    course: ReferenceSnapshot
    dependent_effects_fingerprint: Fingerprint


class AssignCourse(_FrozenContract):
    action: Literal["assign_course"]
    course: ReferenceSnapshot
    department_id: UUID
    audience_version_token: VersionToken
    recipients: tuple[UUID, ...] = Field(min_length=1, max_length=5000)
    due_at: AwareDatetime
    notify: StrictBool

    @field_validator("recipients")
    @classmethod
    def normalize_recipients(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(set(value)) != len(value):
            raise ValueError("duplicate recipient IDs")
        return tuple(sorted(value, key=str))


Operation = Annotated[
    CreateCourseDraft | ProposeCourseEdit | PublishCourse | AssignCourse,
    Field(discriminator="action"),
]


class PlanSnapshot(_FrozenContract):
    """Trusted, fully resolved one-step plan. No HTTP route accepts this shape."""

    plan_id: UUID
    revision: Revision
    tenant_id: UUID
    actor_id: UUID
    expires_at: AwareDatetime
    operation: Operation


class ConfirmationRequest(_FrozenContract):
    plan_id: UUID
    revision: Revision
    fingerprint: Fingerprint


class ActorContext(_FrozenContract):
    """Current server-authenticated identity; never inferred from model output."""

    tenant_id: UUID
    actor_id: UUID
    active_role: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=40)]


class ConfirmationDecision(StrEnum):
    ACCEPTED = "accepted"
    ROLE_DENIED = "role_denied"
    CONTEXT_MISMATCH = "context_mismatch"
    PLAN_MISMATCH = "plan_mismatch"
    REVISION_MISMATCH = "revision_mismatch"
    FINGERPRINT_MISMATCH = "fingerprint_mismatch"
    EXPIRED = "expired"
    DEADLINE_PASSED = "deadline_passed"
    STALE = "stale"


def plan_fingerprint(plan: PlanSnapshot) -> str:
    """Bind ALL executable fields. Digest is not a signature or auth token."""
    canonical = json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evaluate_confirmation(
    plan: PlanSnapshot,
    request: ConfirmationRequest,
    actor: ActorContext,
    current_fingerprint: str,
    now: datetime,
) -> ConfirmationDecision:
    """Check one preview, without any effects or a replay-safety guarantee.

    The future executor must compute current_fingerprint from authoritative
    domain state and atomically recheck/claim under locks before mutation.
    """
    if now.utcoffset() is None:
        raise ValueError("confirmation time must be timezone-aware")
    if actor.active_role != "methodologist":
        return ConfirmationDecision.ROLE_DENIED
    if actor.tenant_id != plan.tenant_id or actor.actor_id != plan.actor_id:
        return ConfirmationDecision.CONTEXT_MISMATCH
    if request.plan_id != plan.plan_id:
        return ConfirmationDecision.PLAN_MISMATCH
    if request.revision != plan.revision:
        return ConfirmationDecision.REVISION_MISMATCH
    fingerprint = plan_fingerprint(plan)
    if request.fingerprint != fingerprint:
        return ConfirmationDecision.FINGERPRINT_MISMATCH
    if now >= plan.expires_at:
        return ConfirmationDecision.EXPIRED
    if isinstance(plan.operation, AssignCourse) and now >= plan.operation.due_at:
        return ConfirmationDecision.DEADLINE_PASSED
    if current_fingerprint != fingerprint:
        return ConfirmationDecision.STALE
    return ConfirmationDecision.ACCEPTED
