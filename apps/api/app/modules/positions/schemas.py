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
    # Cached count maintained by /positions/{id}/assign/{user} and
    # staff-import endpoints. May be stale if employees were added/removed
    # via direct DB writes. UI should prefer current_employee_count when
    # shown — it's always computed at query time.
    employee_count: int
    # Always-fresh count: SELECT COUNT(*) FROM users WHERE position_id = ...
    # filtered by is_active=true. Computed in the same query as the
    # position GET, so no extra round-trip. Added 2026-06-27 because the
    # cached employee_count drifted to 0 in some tenants after staff import
    # paths that bypass the position-assignment endpoint.
    current_employee_count: int = 0
    # True when cached count != live count. UI can show a small "↻ уточнено"
    # badge so the methodologist knows the cached value was stale.
    employee_count_stale: bool = False
    # nullable on the Pydantic side: legacy rows in the `positions` table
    # (pre-migration 0036 / staff-import that bypassed ServerDefault)
    # can have created_at IS NULL. Without the default this validation
    # error would 422 every list call the moment a NULL row exists in
    # the tenant. See LESSONS.md Lesson 14 (added 2026-06-30).
    created_at: datetime | None = None
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


# ── Onboarding quiz (Phase 3) ──────────────────────────────────


class QuizChoiceDraft(BaseModel):
    """One answer choice in an onboarding quiz question.

    Draft = not yet persisted to a separate QuizChoice row (we store
    questions as JSON for v1). Methodologist edits/adds/removes these
    in the modal before saving.
    """
    text: str = Field(..., min_length=1, max_length=1000)
    is_correct: bool = False


class QuizQuestionDraft(BaseModel):
    """One question in an onboarding quiz.

    Stored as JSON in position_quizzes.questions. Designed for v1:
    - Only MCQ type supported (single correct answer per question)
    - explanation is optional but recommended (shown to learner after submit)
    """
    text: str = Field(..., min_length=3, max_length=2000)
    type: str = Field(default="MCQ", max_length=32)
    explanation: str = Field(default="", max_length=2000)
    choices: list[QuizChoiceDraft] = Field(..., min_length=2, max_length=8)

    def normalize(self) -> "QuizQuestionDraft":
        """Trim text and ensure exactly one correct choice (default first if none)."""
        clean_choices = [
            QuizChoiceDraft(text=c.text.strip()[:1000], is_correct=bool(c.is_correct))
            for c in self.choices
            if c.text.strip()
        ]
        if not any(c.is_correct for c in clean_choices) and clean_choices:
            clean_choices[0].is_correct = True
        return QuizQuestionDraft(
            text=self.text.strip()[:2000],
            type=(self.type or "MCQ").strip()[:32] or "MCQ",
            explanation=self.explanation.strip()[:2000],
            choices=clean_choices,
        )


class SuggestOnboardingQuizResponse(BaseModel):
    """Return of POST /{id}/suggest-onboarding-quiz (AI draft, not saved)."""
    title: str
    questions: list[QuizQuestionDraft]


class SavePositionQuizRequest(BaseModel):
    """Body for POST /{id}/onboarding-quiz (upsert)."""
    title: str = Field(..., min_length=2, max_length=255)
    pass_score: int = Field(default=80, ge=0, le=100)
    time_limit: int | None = Field(default=None, ge=1, le=600)  # minutes
    questions: list[QuizQuestionDraft] = Field(..., min_length=1, max_length=30)
    is_active: bool = True


class PositionQuizResponse(BaseModel):
    """Stored onboarding quiz (return of GET or POST upsert)."""
    id: UUID
    position_id: UUID
    title: str
    pass_score: int
    time_limit: int | None
    questions: list[QuizQuestionDraft]
    is_active: bool
    created_at: datetime
    updated_at: datetime
