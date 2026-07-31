"""Input snapshots for evidence exports.

The exporter deliberately accepts snapshots instead of ORM objects. This keeps
formatting and packaging independent from database migrations and lets a caller
assemble the snapshot from the current release, training log and quiz evidence
services without coupling this module to their SQL models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class TenantEvidence(_EvidenceModel):
    id: str | None = None
    name: str
    slug: str | None = None


class EmployeeEvidence(_EvidenceModel):
    id: str | None = None
    full_name: str
    email: str | None = None
    personnel_number: str | None = None
    department: str | None = None
    position: str | None = None
    phone: str | None = None


class ProcedureEvidence(_EvidenceModel):
    type: str
    title: str
    code: str | None = None
    version: str | None = None
    purpose: str | None = None


class CourseEvidence(_EvidenceModel):
    id: str | None = None
    title: str
    delivery_type: str | None = None
    release_id: str | None = None
    release_version: int | None = None
    release_sha256: str | None = None


class AssignmentEvidence(_EvidenceModel):
    enrollment_id: str | None = None
    source: str
    assigned_at: datetime | None = None
    due_at: datetime | None = None
    group_or_rule: str | None = None


class AttemptEvidence(_EvidenceModel):
    id: str | None = None
    quiz_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    time_spent_seconds: int | None = Field(default=None, ge=0)
    threshold_percent: int | None = Field(default=None, ge=0, le=100)
    score_percent: int | None = Field(default=None, ge=0, le=100)
    total_points: int | None = Field(default=None, ge=0)
    earned_points: int | None = Field(default=None, ge=0)
    passed: bool | None = None
    answers: list[dict[str, Any]] = Field(default_factory=list)


class ConfirmationEvidence(_EvidenceModel):
    confirmed: bool
    method: Literal["otp", "password", "manual", "eds", "other"]
    confirmed_at: datetime | None = None
    statement: str | None = None
    actor: str | None = None
    evidence_reference: str | None = None


class CorrectionEvidence(_EvidenceModel):
    id: str | None = None
    recorded_at: datetime | None = None
    kind: Literal["correction", "annulment", "supersession", "other"]
    reason: str
    actor: str | None = None
    supersedes_sha256: str | None = None
    replacement_reference: str | None = None


class CommissionEvidence(_EvidenceModel):
    members: list[str] = Field(default_factory=list)
    appointed_at: datetime | None = None
    basis: str | None = None


class DecisionEvidence(_EvidenceModel):
    outcome: str
    decided_at: datetime | None = None
    decided_by: str | None = None
    rationale: str | None = None


class IndividualEvidenceInput(_EvidenceModel):
    tenant: TenantEvidence
    employee: EmployeeEvidence
    procedure: ProcedureEvidence
    course: CourseEvidence | None = None
    assignment: AssignmentEvidence | None = None
    attempts: list[AttemptEvidence] = Field(default_factory=list)
    confirmation: ConfirmationEvidence | None = None
    corrections: list[CorrectionEvidence] = Field(default_factory=list)
    commission: CommissionEvidence | None = None
    decision: DecisionEvidence | None = None
    generated_at: datetime | None = None


class GroupRecordEvidence(_EvidenceModel):
    employee: EmployeeEvidence
    assignment: AssignmentEvidence | None = None
    attempts: list[AttemptEvidence] = Field(default_factory=list)
    confirmation: ConfirmationEvidence | None = None
    corrections: list[CorrectionEvidence] = Field(default_factory=list)
    decision: DecisionEvidence | None = None


class GroupEvidenceInput(_EvidenceModel):
    tenant: TenantEvidence
    procedure: ProcedureEvidence
    course: CourseEvidence | None = None
    records: list[GroupRecordEvidence] = Field(min_length=1)
    commission: CommissionEvidence | None = None
    decision: DecisionEvidence | None = None
    generated_at: datetime | None = None
