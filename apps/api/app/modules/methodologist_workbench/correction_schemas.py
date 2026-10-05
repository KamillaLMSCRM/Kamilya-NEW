"""No client-supplied authority in lesson correction preview requests."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.modules.editor_assistant.patch_contract import ProviderProvenance

from .correction_contract import CorrectionEvidence, LessonCorrectionSnapshot, Text
from .plan_contract import Fingerprint, Instruction, Revision


class CorrectionPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_key: UUID
    lesson_id: UUID
    instruction: Instruction
    locale: Literal["ru", "kk", "en"]


class CorrectionCitation(CorrectionEvidence):
    document_id: UUID


class CorrectionProposal(BaseModel):
    """Server-normalized proposal, not the raw provider response."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    content: Text
    citations: tuple[CorrectionCitation, ...] = Field(min_length=1, max_length=64)
    provenance: ProviderProvenance
    quality_policy: str = "lesson-quality-v1"


class CorrectionPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    plan_id: UUID
    lesson_id: UUID
    state: Literal["pending", "ready", "failed"]
    expires_at: AwareDatetime
    fingerprint: Fingerprint | None = None
    before_content: str | None = None
    proposal: CorrectionProposal | None = None
    error_code: str | None = None


class StoredCorrection(BaseModel):
    """Validated immutable context reconstructed from the owned record."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    snapshot: LessonCorrectionSnapshot
    proposal: CorrectionProposal


class CorrectionApplicationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)
    plan_id: UUID
    lesson_id: UUID
    course_id: UUID
    revision: Revision
    fingerprint: Fingerprint
    before_sha256: Fingerprint
    after_sha256: Fingerprint
    applied_at: AwareDatetime
    state: Literal["applied"] = "applied"
    source_review: Literal["needs_review"] = "needs_review"
    quiz_review: Literal["needs_review"] = "needs_review"
