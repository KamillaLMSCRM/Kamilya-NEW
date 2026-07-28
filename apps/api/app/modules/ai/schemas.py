"""AI Generation — schemas"""
from pydantic import BaseModel, Field, ConfigDict, model_validator
from uuid import UUID
from datetime import datetime
from typing import Optional, List, Literal


class AIGenerateRequest(BaseModel):
    course_id: UUID | None = None
    documents: List[UUID] = Field(min_length=1, max_length=20, description="Source document IDs")
    target_audience: str = Field(default="", max_length=2000, description="Target audience description")
    num_modules: int = Field(default=3, ge=1, le=10)
    language: Literal["ru", "kk", "en"] = "ru"
    tone: str = Field(default="professional", max_length=100)
    source_strategy: Literal["single_topic", "intentional_combination"] = "single_topic"
    combination_goal: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_combination_goal(self):
        if self.source_strategy == "intentional_combination" and len(self.combination_goal.strip()) < 20:
            raise ValueError("combination_goal must explain the shared learning goal (at least 20 characters)")
        return self


class DocumentCompatibilityRequest(BaseModel):
    documents: List[UUID] = Field(min_length=1, max_length=20)


class CompatibilityDocument(BaseModel):
    id: UUID
    title: str
    filename: str


class CompatibilityCluster(BaseModel):
    id: str
    label: str
    cohesion: float
    documents: list[CompatibilityDocument]


class DocumentCompatibilityResponse(BaseModel):
    status: Literal["compatible", "mixed", "incompatible"]
    score: float
    requires_decision: bool
    clusters: list[CompatibilityCluster]


class AIJobResponse(BaseModel):
    id: str
    status: str
    course_id: UUID | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    progress: int = 0
    stage: str = ""
    message: str = ""
    errors: list[dict[str, str] | str] | None = None


class AIJobProgress(BaseModel):
    job_id: str
    status: str
    stage: str
    progress: int
    message: str
    course_id: UUID | None = None


# ── Chat with AI assistant (methodologist review) ─────────────────────

class AIChatRequest(BaseModel):
    """Body for POST /ai/chat — assistant that helps review and refine
    AI-generated course content. Scoped to a course (and optionally a
    specific lesson or module) so the LLM has relevant context."""
    course_id: UUID
    context: Literal["course", "module", "lesson"] = "course"
    target_id: Optional[UUID] = None  # required when context=module|lesson
    message: str = Field(..., min_length=1, max_length=2000)
    language: Literal["ru", "kk", "en"] = "ru"
    intent: Literal["course_review", "content_revision", "audience_recommendation"] | None = None


class AudienceRecommendationScope(BaseModel):
    type: Literal["organization", "department", "position", "cohort"]
    id: UUID | None = None
    name: str
    employee_count: int = Field(ge=0)
    priority: Literal["primary", "secondary"]
    confidence: Literal["high", "medium", "low"]
    reasons: list[str] = Field(default_factory=list)


class AudienceRecommendation(BaseModel):
    """Validated, aggregate-only audience advice.

    This is deliberately a recommendation contract, not an assignment
    command. ``assignment_url`` is a navigation hint for published courses;
    it never carries a write action or a preselected mutation payload.
    """

    course_status: Literal["draft", "review", "published", "archived"]
    recommended_scopes: list[AudienceRecommendationScope] = Field(default_factory=list)
    matched_employee_count: int = Field(ge=0)
    already_enrolled_count: int = Field(ge=0)
    data_warnings: list[str] = Field(default_factory=list)
    assignment_url: str | None = None


class AIChatResponse(BaseModel):
    """LLM reply, optionally with an inline suggestion the methodologist
    can apply directly to a lesson. If the assistant wraps a rewrite in
    [APPLY_LESSON:uuid]…[/APPLY_LESSON] tags, backend extracts the body,
    strips the tags from `reply`, and exposes the parsed suggestion
    here for the UI's one-click apply button.
    """
    reply: str
    apply_lesson_id: Optional[UUID] = None
    apply_lesson_content: Optional[str] = None
    apply_lesson_title_hint: Optional[str] = None  # parsed "[APPLY_LESSON:title=...]" hint, optional
    audience_recommendation: AudienceRecommendation | None = None
    model_config = ConfigDict(protected_namespaces=())


# ── Regenerate module / lesson ────────────────────────────────────────

class AIRegenerateModuleRequest(BaseModel):
    guidance: str = Field(default="", max_length=1000,
                          description="Optional guidance to nudge the rewrite")
    language: str = "ru"


class AIRegenerateLessonRequest(BaseModel):
    guidance: str = Field(default="", max_length=1000)
    regenerate_quiz: bool = Field(default=True,
                                  description="Also regenerate the quiz for this lesson")
