"""Document plans contain reviewed generation parameters, never authority."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.modules.ai.schemas import AIGenerateRequest, AIJobResponse

from .plan_contract import Fingerprint, Instruction, Revision


class DocumentGenerationRequest(AIGenerateRequest):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def new_course_only(self) -> Self:
        if self.course_id is not None:
            raise ValueError("document_workbench_creates_new_draft_only")
        if len(self.documents) > 5:
            raise ValueError("too_many_documents")
        if not self.course_intent.strip():
            raise ValueError("document_course_intent_required")
        return self


class DocumentPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    instruction: Instruction
    generation: DocumentGenerationRequest


class DocumentSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    document_id: UUID
    title: str = Field(min_length=1)
    version: int = Field(ge=1)
    content_sha256: Fingerprint
    index_revision: int = Field(ge=1)


class DocumentSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    plan_id: UUID
    revision: Revision
    tenant_id: UUID
    actor_id: UUID
    expires_at: AwareDatetime
    instruction: Instruction
    generation: DocumentGenerationRequest
    sources: tuple[DocumentSource, ...] = Field(min_length=1, max_length=5)


class DocumentPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    state: Literal["preview_ready"] = "preview_ready"
    plan_id: UUID
    revision: Revision
    fingerprint: Fingerprint
    expires_at: AwareDatetime
    instruction: Instruction
    generation: DocumentGenerationRequest
    sources: tuple[DocumentSource, ...] = Field(min_length=1, max_length=5)


class DocumentExecution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    state: Literal["submitted"] = "submitted"
    plan_id: UUID
    job: AIJobResponse


DocumentPlanResponse = DocumentPreview | DocumentExecution
