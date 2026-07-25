"""Documents — public API schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

DocumentCategory = Literal["general", "job_instruction"]
DocumentIndexStatus = Literal["processing", "ready", "partial", "failed"]
DocumentLifecycleStatus = Literal["active", "deletion_pending", "delete_failed"]


class DocumentResponse(BaseModel):
    """Backward-compatible single-document/upload DTO without storage metadata."""

    id: UUID
    title: str
    filename: str
    content_type: str
    size: int
    description: str = ""
    category: DocumentCategory = "general"
    embedding_status: Literal["pending", "success", "failed"] = "pending"
    embedding_error: str | None = None
    created_at: datetime
    updated_at: datetime
    # Populated by router._hydrate when educational summary is available.
    summary_ready: bool = False
    short_summary: str | None = None
    model_config = {"from_attributes": True}


class DocumentIndexResponse(BaseModel):
    status: DocumentIndexStatus
    error_code: str | None = None
    message: str | None = None
    chunks_total: int | None = Field(default=None, ge=0)
    chunks_indexed: int | None = Field(default=None, ge=0)
    indexed_at: datetime | None = None
    revision: int = Field(gt=0)


class DocumentUsageSummary(BaseModel):
    total: int = 0
    courses: int = 0
    positions: int = 0
    lessons: int = 0
    active_jobs: int = 0


class DocumentCatalogItem(BaseModel):
    id: UUID
    source_family_id: UUID
    title: str
    filename: str
    content_type: str
    size: int
    description: str = ""
    category: DocumentCategory
    index: DocumentIndexResponse
    version: int = Field(gt=0)
    is_latest: bool
    lifecycle_status: DocumentLifecycleStatus
    deletion_error_code: str | None = None
    deletion_error_message: str | None = None
    deletion_job_id: str | None = None
    created_at: datetime
    updated_at: datetime
    usages_summary: DocumentUsageSummary | None = None


class DocumentCatalogPage(BaseModel):
    next_cursor: str | None = None
    has_more: bool
    limit: int = Field(ge=1, le=100)


class DocumentCatalogResponse(BaseModel):
    items: list[DocumentCatalogItem]
    page: DocumentCatalogPage


DocumentUsageType = Literal[
    "position_instruction",
    "course_instruction",
    "course_source",
    "lesson_source",
    "active_ai_job",
]


class DocumentUsageItem(BaseModel):
    type: DocumentUsageType
    id: str
    title: str
    status: str | None = None
    route: str
    blocks_delete: bool = True


class DocumentUsageDetailSummary(BaseModel):
    total: int = 0
    positions: int = 0
    courses: int = 0
    lessons: int = 0
    active_jobs: int = 0


class DocumentUsagePage(BaseModel):
    next_cursor: str | None = None
    has_more: bool
    limit: int = Field(ge=1, le=100)


class DocumentUsageResponse(BaseModel):
    summary: DocumentUsageDetailSummary
    items: list[DocumentUsageItem]
    page: DocumentUsagePage


class DocumentDeleteAccepted(BaseModel):
    document_id: UUID
    lifecycle_status: Literal["deletion_pending"]
    job_id: str
    status_url: str


class DocumentReindexAccepted(BaseModel):
    document_id: UUID
    index_status: Literal["processing"]
    revision: int = Field(gt=0)
    job_id: str
    status_url: str


class DocumentHashBackfillAccepted(BaseModel):
    job_id: str
    status_url: str
