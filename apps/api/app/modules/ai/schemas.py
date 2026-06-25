"""AI Generation — schemas"""
from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import Optional, List, Literal


class AIGenerateRequest(BaseModel):
    course_id: UUID | None = None
    documents: List[str] = Field(default=[], description="Document IDs or text content")
    target_audience: str = Field(default="", description="Target audience description")
    num_modules: int = Field(default=3, ge=1, le=10)
    language: str = Field(default="ru")
    tone: str = Field(default="professional")


class AIJobResponse(BaseModel):
    id: str
    status: str
    course_id: UUID | None
    created_at: datetime
    progress: int = 0
    stage: str = ""
    message: str = ""


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


class AIChatResponse(BaseModel):
    reply: str
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
