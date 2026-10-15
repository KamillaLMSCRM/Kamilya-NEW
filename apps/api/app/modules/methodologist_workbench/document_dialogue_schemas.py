"""Private document preparation; history is not an execution receipt."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator

from .document_intent import DocumentCandidate, DocumentClarification, Language
from .document_schemas import DocumentSource
from .plan_contract import Instruction, Revision

DraftInstruction = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, max_length=4000)]
ReuseReason = Literal["different_audience", "different_language", "different_depth", "updated_revision", "recurring_training", "other"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DialogueDraft(Contract):
    instruction: DraftInstruction = ""
    candidate: DocumentCandidate
    language_confirmed: StrictBool = False
    reuse_reason: ReuseReason | None = None


class CreateDialogue(Contract):
    task_id: UUID
    document_ids: list[UUID] = Field(min_length=1, max_length=5)
    language: Language
    draft: DialogueDraft

    @model_validator(mode="after")
    def scope(self) -> Self:
        if len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("duplicate_documents")
        if self.draft.candidate.language != self.language:
            raise ValueError("dialogue_language_mismatch")
        return self


class SaveDialogue(Contract):
    expected_revision: Revision
    draft: DialogueDraft


class SendDocumentMessage(Contract):
    request_id: UUID
    expected_revision: Revision
    instruction: Instruction


class PreviewDialogue(Contract):
    expected_revision: Revision


class InterpretedDocument(Contract):
    state: Literal["interpreted"] = "interpreted"
    candidate: DocumentCandidate


class DocumentExchange(Contract):
    id: UUID
    instruction: Instruction
    state: Literal["pending", "completed", "failed"]
    response: InterpretedDocument | DocumentClarification | None = None
    error_code: str | None = None
    created_at: AwareDatetime


class DocumentDialogue(Contract):
    id: UUID
    revision: Revision
    language: Language
    sources: tuple[DocumentSource, ...]
    draft: DialogueDraft
    plan_id: UUID | None
    source_stale: bool
    pending_request_id: UUID | None
    interrupted_request_id: UUID | None
    exchanges: list[DocumentExchange]
    created_at: AwareDatetime
    updated_at: AwareDatetime


class DocumentDialogueSummary(Contract):
    id: UUID
    title: str
    updated_at: AwareDatetime
    plan_id: UUID | None


class DocumentDialogueList(Contract):
    tasks: list[DocumentDialogueSummary]
    has_more: bool
    next_before: UUID | None
