"""Contracts for server-built training-evidence exports.

The request schemas intentionally contain identifiers only.  All employee,
course, release, attempt and audit data is read from the tenant-scoped
database by ``export_service``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.evidence_export.schemas import (
    AssignmentEvidence,
    AttemptEvidence,
    CommissionEvidence,
    ConfirmationEvidence,
    CorrectionEvidence,
    CourseEvidence,
    DecisionEvidence,
    EmployeeEvidence,
    GroupEvidenceInput,
    GroupRecordEvidence,
    IndividualEvidenceInput,
    ProcedureEvidence,
    TenantEvidence,
)


class LegalHoldEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    action: Literal["placed", "released"]
    reason: str
    acted_by: str | None = None
    occurred_at: datetime
    payload_sha256: str


class EvidenceState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_event_id: str
    active_record_type: Literal["original", "correction", "revocation"]
    latest_correction_event_id: str | None = None
    revoked: bool = False
    legal_hold_active: bool = False


class ServerIndividualEvidenceInput(IndividualEvidenceInput):
    """Builder input plus server-derived state omitted by the pure builder."""

    state: EvidenceState
    legal_holds: list[LegalHoldEvidence] = Field(default_factory=list)


class ServerGroupRecordEvidence(GroupRecordEvidence):
    state: EvidenceState
    legal_holds: list[LegalHoldEvidence] = Field(default_factory=list)
    decision: DecisionEvidence | None = None


class ServerGroupEvidenceInput(GroupEvidenceInput):
    records: list[ServerGroupRecordEvidence] = Field(min_length=1, max_length=200)


ExportFormat = Literal["zip", "pdf"]


class GroupEvidenceExportRequest(BaseModel):
    """Only event IDs are accepted; all other package data is server-owned."""

    model_config = ConfigDict(extra="forbid")

    event_ids: list[UUID] = Field(min_length=1, max_length=200)
    format: ExportFormat = "zip"


__all__ = [
    "AssignmentEvidence",
    "AttemptEvidence",
    "CommissionEvidence",
    "ConfirmationEvidence",
    "CorrectionEvidence",
    "CourseEvidence",
    "DecisionEvidence",
    "EmployeeEvidence",
    "EvidenceState",
    "ExportFormat",
    "GroupEvidenceExportRequest",
    "IndividualEvidenceInput",
    "LegalHoldEvidence",
    "ProcedureEvidence",
    "ServerGroupEvidenceInput",
    "ServerGroupRecordEvidence",
    "ServerIndividualEvidenceInput",
    "TenantEvidence",
]
