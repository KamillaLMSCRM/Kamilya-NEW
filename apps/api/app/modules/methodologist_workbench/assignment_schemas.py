"""Strict transport shapes; no client-owned tenant, actor or executable plan."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StringConstraints

from .plan_contract import Fingerprint, Instruction, Revision


class _DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AssignmentPreviewRequest(_DTO):
    instruction: Instruction
    timezone_name: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=80)]
    notify: StrictBool = False
    include_descendants: StrictBool = False
    course_id: UUID | None = None
    department_id: UUID | None = None


class Choice(_DTO):
    id: UUID
    label: str


class Clarification(_DTO):
    state: Literal["clarification_needed"] = "clarification_needed"
    code: str
    course_choices: tuple[Choice, ...] = Field(default=(), max_length=20)
    department_choices: tuple[Choice, ...] = Field(default=(), max_length=20)


class Recipient(_DTO):
    user_id: UUID
    label: str
    already_assigned: bool
    access_warning: bool


class AssignmentPreview(_DTO):
    state: Literal["preview_ready"] = "preview_ready"
    plan_id: UUID
    revision: Revision
    fingerprint: Fingerprint
    expires_at: AwareDatetime
    course_id: UUID
    course_title: str
    release_id: UUID
    department_id: UUID
    department_name: str
    timezone_name: str
    due_at: AwareDatetime
    notify: bool
    include_descendants: bool
    recipients: tuple[Recipient, ...] = Field(min_length=1, max_length=5000)
    new_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)


class CreatedAssignment(_DTO):
    user_id: UUID
    enrollment_id: UUID
    notification_id: UUID | None


class AssignmentReceipt(_DTO):
    state: Literal["succeeded"] = "succeeded"
    plan_id: UUID
    created: tuple[CreatedAssignment, ...] = Field(max_length=5000)
    skipped: tuple[UUID, ...] = Field(max_length=5000)
    notification_state: Literal["queued", "not_requested"]


PreviewResponse = AssignmentPreview | Clarification
PlanResponse = AssignmentPreview | AssignmentReceipt
