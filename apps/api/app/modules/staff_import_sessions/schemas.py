"""Pydantic DTOs for adaptive tenant-scoped import sessions.

These are pure domain models with no ORM dependency.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ImportMode(StrEnum):
    """Session import strategy.

    ADD_OR_UPDATE is the default and keeps existing structures not present in file.
    FULL_RECONCILIATION is opt-in and never selected implicitly.
    """

    ADD_OR_UPDATE = "ADD_OR_UPDATE"
    FULL_RECONCILIATION = "FULL_RECONCILIATION"


class ImportSessionState(StrEnum):
    """Canonical state graph used by API and worker orchestration."""

    UPLOADED = "uploaded"
    INSPECTING = "inspecting"
    NEEDS_MAPPING = "needs_mapping"
    NEEDS_REVIEW = "needs_review"
    NEEDS_CORRECTION = "needs_correction"
    READY_FOR_APPROVAL = "ready_for_approval"
    APPROVED = "approved"
    COMMITTING = "committing"
    COMMITTED = "committed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"


class ImportSessionStateTransition(StrEnum):
    """Discrete transition names for public command endpoints."""

    TO_INSPECTING = "to_inspecting"
    TO_NEEDS_MAPPING = "to_needs_mapping"
    TO_NEEDS_REVIEW = "to_needs_review"
    TO_NEEDS_CORRECTION = "to_needs_correction"
    TO_READY_FOR_APPROVAL = "to_ready_for_approval"
    TO_APPROVED = "to_approved"
    TO_COMMITTING = "to_committing"
    TO_COMMITTED = "to_committed"
    TO_REJECTED = "to_rejected"
    TO_EXPIRED = "to_expired"
    TO_FAILED = "to_failed"


class ProposalConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MatchAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    UNCHANGED = "unchanged"
    RENAME = "rename"
    MOVE = "move"
    SKIP = "skip"
    CONFLICT = "conflict"


class ProposalItemKind(StrEnum):
    BRANCH = "branch"
    DEPARTMENT = "department"
    POSITION = "position"
    STAFF = "staff"


class SourceCellRef(BaseModel):
    """Pointer to a source cell for explainability and audit trails."""

    sheet: str = Field(..., min_length=1, max_length=120)
    row: int = Field(..., ge=1)
    column: str = Field(..., min_length=1, max_length=16)

    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceItem(BaseModel):
    """Confidence-bearing rationale behind a proposal line item."""

    evidence_code: str = Field(..., min_length=1, max_length=120)
    claim: str = Field(..., min_length=1, max_length=400)
    confidence: ProposalConfidence = ProposalConfidence.MEDIUM
    reason: str = Field(default="", max_length=500)

    model_config = ConfigDict(extra="forbid", frozen=True)


class ImportSessionConflict(BaseModel):
    """Blocking or warning conflict discovered during proposal generation."""

    conflict_code: str = Field(..., min_length=1, max_length=120)
    scope: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=500)
    blocking: bool = Field(default=False)
    proposal_ids: list[str] = Field(default_factory=list)
    source_refs: list[SourceCellRef] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", frozen=True)


class CanonicalProposalBase(BaseModel):
    """Common fields used by branch/department/position/staff proposal DTOs."""

    external_key: str = Field(..., min_length=1, max_length=200)
    action: MatchAction
    confidence: ProposalConfidence = ProposalConfidence.MEDIUM
    source_refs: list[SourceCellRef] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", frozen=True)


class BranchProposal(CanonicalProposalBase):
    """Canonical branch proposal."""

    branch_id: str = Field(..., min_length=1, max_length=120)
    branch_name: str = Field(..., min_length=1, max_length=255)
    parent_path: str = "ROOT"


class CanonicalDepartmentProposal(CanonicalProposalBase):
    """Canonical department proposal under a branch."""

    department_id: str = Field(..., min_length=1, max_length=120)
    department_name: str = Field(..., min_length=1, max_length=255)
    branch_external_key: str = Field(..., min_length=1, max_length=120)


class CanonicalPositionProposal(CanonicalProposalBase):
    """Canonical position proposal under branch or department."""

    position_id: str = Field(..., min_length=1, max_length=120)
    position_name: str = Field(..., min_length=1, max_length=255)
    branch_external_key: str = Field(..., min_length=1, max_length=120)
    department_external_key: str | None = Field(default=None, min_length=1, max_length=120)


class CanonicalStaffProposal(CanonicalProposalBase):
    """Canonical staff proposal with direct source links to file cells."""

    personnel_number: str = Field(..., min_length=1, max_length=64)
    first_name: str = Field(..., min_length=1, max_length=120)
    last_name: str = Field(..., min_length=1, max_length=120)
    position_external_key: str = Field(..., min_length=1, max_length=120)
    branch_external_key: str = Field(..., min_length=1, max_length=120)
    department_external_key: str | None = Field(default=None, min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=64)


class ImportSessionProposal(BaseModel):
    """Pure, tenant-scoped proposed import snapshot.

    The proposal itself must be immutable once accepted by hash/revision contract.
    """

    mode: ImportMode = ImportMode.ADD_OR_UPDATE
    source_file_name: str = Field(..., min_length=1, max_length=255)
    source_file_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    extracted_by: str = Field(default="adaptive-workflow", max_length=120)
    branches: list[BranchProposal] = Field(default_factory=list)
    departments: list[CanonicalDepartmentProposal] = Field(default_factory=list)
    positions: list[CanonicalPositionProposal] = Field(default_factory=list)
    staff: list[CanonicalStaffProposal] = Field(default_factory=list)
    conflicts: list[ImportSessionConflict] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    revision: str | None = Field(default=None, max_length=120)
    revision_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    model_config = ConfigDict(extra="forbid", frozen=True)


class ProposalCorrection(BaseModel):
    """One explicit methodologist correction to a generated proposal item."""

    kind: ProposalItemKind
    external_key: str = Field(..., min_length=1, max_length=200)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    branch_external_key: str | None = Field(default=None, min_length=1, max_length=200)
    department_external_key: str | None = Field(default=None, min_length=1, max_length=200)
    position_external_key: str | None = Field(default=None, min_length=1, max_length=200)
    action: MatchAction | None = None

    model_config = ConfigDict(extra="forbid", frozen=True)


class ImportSessionDecision(BaseModel):
    """Input for state-changing decision endpoints."""

    next_transition: ImportSessionStateTransition
    mode: ImportMode | None = None
    revision: str | None = None
    approval_token_hash: str | None = None
    full_reconciliation_confirmation: bool = False
    reason: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(extra="forbid")


class ImportSession(BaseModel):
    """Tenant-scoped session model for adaptive import workflow."""

    session_id: str = Field(..., min_length=8, max_length=64)
    tenant_id: UUID
    actor_id: UUID
    actor_role: str = Field(..., min_length=1, max_length=64)
    state: ImportSessionState = ImportSessionState.UPLOADED
    mode: ImportMode = ImportMode.ADD_OR_UPDATE
    proposal: ImportSessionProposal | None = None
    approval_token_hash: str | None = None
    full_reconciliation_confirmation: bool = False
    reviewed_revision: str | None = None
    approved_revision: str | None = None
    approved_at: datetime | None = None
    expires_at: datetime | None = None

    model_config = ConfigDict(extra="forbid", frozen=True)
