from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime


class PositionCreate(BaseModel):
    name: str
    department: str = ""
    level: str = ""
    responsibilities: str = ""
    requirements: str = ""
    course_ids: list[UUID] = []


class PositionUpdate(BaseModel):
    name: str | None = None
    department: str | None = None
    level: str | None = None
    responsibilities: str | None = None
    requirements: str | None = None
    course_ids: list[UUID] | None = None


class PositionResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    department: str
    level: str
    responsibilities: str
    requirements: str
    course_ids: list[UUID] = []
    employee_count: int
    created_at: datetime
    re_enrolled: int | None = None  # only set on update responses

    class Config:
        from_attributes = True


# ── Bulk JD analysis (multi-file upload) ──────────────────────


class BulkJDItem(BaseModel):
    """One parsed JD, as returned by bulk-analyze-jd endpoint."""
    filename: str
    name: str = ""
    department: str = ""
    level: str = ""
    responsibilities: str = ""
    requirements: str = ""
    error: str | None = None  # set if parsing failed for this file


class BulkJDResponse(BaseModel):
    items: list[BulkJDItem]


# ── Bulk create positions ─────────────────────────────────────


class BulkPositionItem(BaseModel):
    """One position in a bulk create request. No id yet."""
    name: str
    department: str = ""
    level: str = ""
    responsibilities: str = ""
    requirements: str = ""
    course_ids: list[UUID] = []


class BulkPositionRequest(BaseModel):
    items: list[BulkPositionItem] = Field(..., max_length=200)


class BulkPositionCreated(BaseModel):
    index: int  # index in original request
    id: UUID
    name: str


class BulkPositionFailed(BaseModel):
    index: int
    name: str
    error: str


class BulkPositionResponse(BaseModel):
    created: list[BulkPositionCreated]
    failed: list[BulkPositionFailed]


# ── Recommended content (vector search against document_embeddings) ──


class RecommendedContentItem(BaseModel):
    """Top-N documents most relevant to a position's JD text."""
    doc_id: UUID
    doc_name: str
    similarity: float  # 0..1, higher is better
    headings: str = ""


class RecommendedContentResponse(BaseModel):
    items: list[RecommendedContentItem]
