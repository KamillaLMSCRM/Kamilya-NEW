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


class DocumentCatalogItem(BaseModel):
    id: UUID
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
