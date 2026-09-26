"""Wire contracts for the explainable mandatory-training matrix."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.mandatory_training.requirements import (
    RequirementAction,
    RequirementState,
)

AssignmentReasonKind = Literal[
    "position",
    "department",
    "organization",
    "manual",
    "cohort",
    "learning_path",
    "recurring",
    "auto",
    "unknown",
]


class MandatoryTrainingFilter(BaseModel):
    course_id: UUID | None = None
    organization_unit_id: UUID | None = None
    position_id: UUID | None = None
    requirement_state: RequirementState | None = None
    action_required: RequirementAction | None = None
    search: str | None = Field(default=None, max_length=200)
    include_inactive: bool = False

    model_config = ConfigDict(extra="forbid")


class AssignmentReason(BaseModel):
    kind: AssignmentReasonKind
    source_ref_id: UUID | None = None
    source_name: str | None = None
    scope_path_ids: list[UUID] = Field(default_factory=list)
    scope_path_names: list[str] = Field(default_factory=list)
    reason_code: str


class MandatoryTrainingRow(BaseModel):
    user_id: UUID
    full_name: str
    personnel_number: str | None = None
    is_active: bool
    organization_unit_id: UUID | None = None
    organization_unit_path: list[str] = Field(default_factory=list)
    position_id: UUID | None = None
    position_name: str | None = None
    course_id: UUID
    course_title: str
    delivery_type: Literal["native", "scorm"]
    requirement_state: RequirementState
    assignment_reason: AssignmentReason
    action_required: RequirementAction
    enrollment_id: UUID | None = None
    enrollment_source: str | None = None
    enrollment_status: str | None = None


class MandatoryTrainingPage(BaseModel):
    items: list[MandatoryTrainingRow]
    total: int
    limit: int
    offset: int


class MandatoryTrainingSummary(BaseModel):
    total: int
    materialized: int
    missing_enrollment: int
    protected_assignment: int
    stale_managed_enrollment: int
    action_materialize: int
    action_review_stale: int
