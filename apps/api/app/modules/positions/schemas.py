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
    issues: list["JDAuditItem"] = []  # quality audit findings (warnings/suggestions)


# ── Bulk create positions ─────────────────────────────────────


class BulkJDResponse(BaseModel):
    items: list[BulkJDItem]





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


# ── Generate JD from name (AI, no file) ────────────────────────


class GenerateJDRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    department: str = Field(default="", max_length=200)
    level: str = Field(default="", max_length=64)  # junior/middle/senior/lead/head


class GenerateJDResponse(BaseModel):
    """Same shape as the analyze-jd response, returned by name-only generation."""
    name: str
    department: str
    level: str
    responsibilities: str
    requirements: str


# ── JD audit (quality check) ──────────────────────────────────


class JDAuditItem(BaseModel):
    """One finding from the AI quality audit.

    Used by:
    - POST /v1/positions/analyze-jd (and bulk variant) — file upload audit
    - POST /v1/positions/{id}/jd-audit — re-audit of saved position

    The methodologist uses these to improve the JD before locking it in.
    """
    severity: str  # "warning" | "suggestion" | "ok"
    category: str  # "completeness" | "clarity" | "compliance" | "specificity" | "structure" | "other"
    field: str = ""  # which field the issue is about ("responsibilities" | "requirements" | "name" | "" for whole-JD)
    message: str  # human-readable description
    suggestion: str = ""  # optional concrete fix


class JDAuditResponse(BaseModel):
    """Return of /jd-audit (audit-only, no re-parse)."""
    issues: list[JDAuditItem]


# ── Course suggestions (AI proposes training topics from JD) ────


class CourseSuggestion(BaseModel):
    """One AI-proposed course topic derived from a position's JD.

    The methodologist reviews, picks which ones to create as draft
    courses, and fills in the actual content (via existing ai/generate
    pipeline or manually).
    """
    title: str
    description: str
    estimated_chapters: int  # rough number of chapters
    reason: str  # why this course is relevant to the position


class CourseSuggestionsResponse(BaseModel):
    items: list[CourseSuggestion]


class CreateCourseItem(BaseModel):
    """One course to create from a selected suggestion."""
    title: str = Field(..., min_length=2, max_length=200)
    description: str = Field(default="", max_length=2000)


class CreateCoursesRequest(BaseModel):
    """Request body for POST /{id}/create-courses."""
    items: list[CreateCourseItem] = Field(..., min_length=1, max_length=10)


class CreatedCourseRef(BaseModel):
    id: str  # course id
    title: str


class CreateCoursesResponse(BaseModel):
    created: list[CreatedCourseRef]
    attached_to_position: int  # how many were linked to this position via position_courses


# Rebuild BulkJDItem to include forward-ref'd JDAuditItem
BulkJDItem.model_rebuild()


# ── JD preview / diff (analyze against current) ────────────────


class JDPreviewItem(BaseModel):
    field: str  # "responsibilities" | "requirements" | "name" | "department" | "level"
    current: str
    proposed: str
    changed: bool


class JDPreviewRequest(BaseModel):
    """Multi-modal: file upload OR text. If file is provided, text is ignored."""
    text: str = ""  # raw text of the JD
    name: str = Field(default="", max_length=200)
    department: str = Field(default="", max_length=200)
    level: str = Field(default="", max_length=64)


class JDPreviewResponse(BaseModel):
    items: list[JDPreviewItem]  # field-by-field diff between current (position) and AI proposal


# ── Recommended courses (not documents) ────────────────────────


class RecommendedCourseItem(BaseModel):
    course_id: UUID
    title: str
    similarity: float
    matched_doc_name: str = ""  # which document in the course matched the position


class RecommendedCoursesResponse(BaseModel):
    items: list[RecommendedCourseItem]


# ── Position JD versions (history) ─────────────────────────────


class JDVersionItem(BaseModel):
    id: UUID
    responsibilities: str
    requirements: str
    source: str  # "auto" | "manual"
    note: str | None
    created_at: datetime
    created_by: UUID | None


class JDVersionListResponse(BaseModel):
    items: list[JDVersionItem]


class JDVersionCreate(BaseModel):
    """Manual snapshot with optional note."""
    note: str | None = Field(default=None, max_length=500)


class JDRestoreResponse(BaseModel):
    position: PositionResponse
    restored_from_version_id: UUID
