"""API contracts for training evidence.

The word "signature" is deliberately absent from this module. Email OTP or
another re-authentication method is recorded as a confirmation method, not as
an electronic signature or EDS.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ProcedureType = Literal[
    "acknowledgement",
    "training",
    "knowledge_check",
    "internal_attestation",
    "admission_decision",
]
RecordType = Literal["original", "correction", "revocation"]
ReauthMethod = Literal["email_otp", "telegram", "sso", "password"]
HoldAction = Literal["placed", "released"]
EvidenceConfirmationStatus = Literal["not_required", "pending", "confirmed"]


class EvidenceCorrectionCreate(BaseModel):
    user_id: UUID
    enrollment_id: UUID | None = None
    content_release_id: UUID | None = None
    procedure_type: ProcedureType
    payload_snapshot: dict[str, Any] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=2000)


class EvidenceRevocationCreate(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class LegalHoldCreate(BaseModel):
    action: HoldAction
    reason: str = Field(min_length=1, max_length=2000)


class EvidenceEventResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    user_id: UUID
    enrollment_id: UUID | None
    content_release_id: UUID | None
    procedure_type: str
    source_event_key: str | None
    record_type: str
    related_event_id: UUID | None
    reason: str | None
    payload_snapshot: dict[str, Any]
    payload_sha256: str
    recorded_by_user_id: UUID | None
    occurred_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LearnerEvidenceEventResponse(BaseModel):
    """Safe learner projection of one evidence event.

    The learner can inspect only their own event metadata.  Payload snapshots,
    hashes, actor IDs, IP addresses and other audit details stay on the
    methodologist-only projection and evidence export endpoints.
    """

    id: UUID
    enrollment_id: UUID | None
    content_release_id: UUID | None
    procedure_type: str
    record_type: str
    related_event_id: UUID | None
    occurred_at: datetime
    created_at: datetime
    confirmation_status: EvidenceConfirmationStatus
    procedure_title: str | None = None
    confirmation_statement: str | None = None
    confirmation_object_version: str | None = None
    release_version: int | None = None
    release_sha256: str | None = None

    model_config = ConfigDict(from_attributes=True)


class StepUpConfirmationResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    event_id: UUID
    user_id: UUID
    action_text: str
    object_version: str
    reauth_method: str
    confirmed_at: datetime
    ip_address: str | None
    user_agent: str | None
    confirmation_sha256: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LegalHoldResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    event_id: UUID
    action: str
    reason: str
    acted_by_user_id: UUID
    occurred_at: datetime
    payload_sha256: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
