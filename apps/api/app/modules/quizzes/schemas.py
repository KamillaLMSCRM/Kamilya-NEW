"""Quiz schemas"""
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional, Literal


class QuizChoiceResponse(BaseModel):
    id: UUID
    text: str
    order_index: int
    is_correct: bool = False
    model_config = {"from_attributes": True}


class QuestionResponse(BaseModel):
    id: UUID
    text: str
    type: str
    points: int
    explanation: str | None = None
    order_index: int
    choices: list[QuizChoiceResponse] = []
    model_config = {"from_attributes": True}


class QuizResponse(BaseModel):
    id: UUID
    lesson_id: UUID
    title: str
    pass_score: int
    time_limit: int | None = None
    attempt_limit: int
    deferral_days: int = 7
    questions: list[QuestionResponse] = []
    model_config = {"from_attributes": True}


# --- CRUD schemas ---


class QuizCreate(BaseModel):
    lesson_id: UUID
    title: str
    pass_score: int = 80
    time_limit: int | None = None
    attempt_limit: int = 3
    deferral_days: int = 7


class QuizUpdate(BaseModel):
    title: str | None = None
    pass_score: int | None = None
    time_limit: int | None = None
    attempt_limit: int | None = None
    deferral_days: int | None = None


class QuizChoiceCreate(BaseModel):
    text: str
    is_correct: bool = False
    order_index: int = 0


class QuizChoiceUpdate(BaseModel):
    text: str | None = None
    is_correct: bool | None = None
    order_index: int | None = None


class QuestionCreate(BaseModel):
    text: str
    type: str = "MCQ"
    points: int = 1
    explanation: str | None = None
    order_index: int = 0
    pool_group: str | None = None
    choices: list[QuizChoiceCreate] = []


class QuestionUpdate(BaseModel):
    text: str | None = None
    type: str | None = None
    points: int | None = None
    explanation: str | None = None
    order_index: int | None = None


# --- Submission schemas ---


class AnswerSubmission(BaseModel):
    question_id: UUID
    selected_choice_ids: list[UUID] = Field(default_factory=list)


class QuizSubmission(BaseModel):
    answers: list[AnswerSubmission]
    time_spent_seconds: int | None = None


class QuizAttemptResponse(BaseModel):
    id: UUID
    quiz_id: UUID
    user_id: UUID
    score_percent: int
    total_points: int
    earned_points: int
    passed: bool
    answers: list[dict]
    started_at: datetime
    completed_at: datetime | None = None
    time_spent_seconds: int | None = None
    model_config = {"from_attributes": True}


class QuizResultResponse(BaseModel):
    attempt: QuizAttemptResponse
    correct_answers: int
    total_questions: int
    passed: bool
    message: str


# --- AI generation schemas (2026-06-26) -------------------------------
# Methodologists used to hand-write 5-15 questions with 4 choices each —
# a 30-60 min task per test. The AI assistant generates a draft from the
# lesson text and the methodologist edits/refines before saving.
#
# Design notes:
# - Sync endpoint (NOT a job+polling pattern). Qwen answers in ~10s,
#   the test payload is small (~2000 tokens). Polling would add
#   client-side complexity for no latency win.
# - We return BOTH the AI draft AND the lesson_id it belongs to so the
#   UI can save it with one POST /v1/quizzes in a single click.
# - The endpoint never writes to the DB. Saving is explicit, so the
#   methodologist always reviews before publishing.


class QuizGenerateRequest(BaseModel):
    """Generate a draft quiz for an existing lesson.

    The lesson is the source of truth — its title and content (truncated
    to 6 KB to fit the Qwen context window with margin) ground the model.
    """

    lesson_id: UUID
    num_questions: int = Field(default=8, ge=3, le=20)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    language: Literal["ru", "kk", "en"] = "ru"
    guidance: str | None = Field(
        default=None,
        max_length=500,
        description="Optional free-form guidance, e.g. 'focus on safety procedures'",
    )


class QuizChoiceDraft(BaseModel):
    """One choice in an AI-generated question. Mirrors QuizChoiceCreate but
    without DB-side fields (no id/order_index — those are assigned on save)."""

    text: str
    is_correct: bool = False


class QuizQuestionDraft(BaseModel):
    """One AI-generated question. Mirrors QuestionCreate but without id/quiz_id."""

    text: str
    type: str = "MCQ"
    points: int = 1
    explanation: str | None = None
    order_index: int = 0
    choices: list[QuizChoiceDraft] = Field(default_factory=list)


class QuizGenerateResponse(BaseModel):
    """The AI draft. Caller reviews then POSTs to /v1/quizzes to persist.

    Includes the resolved title suggestion and the lesson_id so the UI
    can call POST /v1/quizzes with this draft directly."""

    lesson_id: UUID
    suggested_title: str
    suggested_pass_score: int
    questions: list[QuizQuestionDraft]
    model_used: str | None = None  # which tier answered (qwen / deepseek / etc.)
    latency_ms: int | None = None


# --- Grouped listing (for Quiz Constructor UI) ---


class QuizWithLocation(QuizResponse):
    """Quiz with its parent course/module/lesson resolved.

    Returned by GET /v1/quizzes/grouped. The UI uses `location` to render
    the three-column cascade (course → module → lesson) without needing
    a separate preview endpoint, eliminating the previous design where
    quizzes appeared as "orphan" before any preview was loaded.

    `location` is null only for true orphans (quiz whose lesson was
    deleted out from under it). The UI should highlight these so
    methodologists can clean up.
    """
    location: "QuizLocation | None" = None


class QuizLocation(BaseModel):
    """Path from quiz up to its course — used to render cascade UI."""
    course_id: UUID
    course_title: str
    course_status: str  # draft / published / archived
    module_id: UUID
    module_title: str
    module_order_index: int
    lesson_id: UUID
    lesson_title: str
    lesson_order_index: int
    model_config = {"from_attributes": True}


class QuizGroupedResponse(BaseModel):
    """Response for GET /v1/quizzes/grouped.

    Server-side grouped by course → module → lesson → quiz. The UI
    receives a ready-to-render cascade without any client-side
    grouping or extra requests.

    `orphans` lists quizzes whose lesson was deleted out from under them
    or whose lesson_id is null. Surfaced so the methodologist sees real
    orphans (not "everything before preview loaded").
    """
    courses: list["GroupedCourse"]
    orphans: list["OrphanQuiz"] = []


class GroupedCourse(BaseModel):
    id: UUID
    title: str
    status: str
    modules: list["GroupedModule"]


class GroupedModule(BaseModel):
    id: UUID
    title: str
    order_index: int
    lessons: list["GroupedLesson"]


class GroupedLesson(BaseModel):
    id: UUID
    title: str
    order_index: int
    quiz: QuizResponse | None  # None if lesson has no quiz yet


class OrphanQuiz(BaseModel):
    """Quiz whose lesson was deleted or whose lesson_id is null.

    Surfaced separately so UI can warn the methodologist instead of
    silently dropping the quiz.
    """
    quiz: QuizResponse
    lesson_id: UUID | None  # None if FK is null, otherwise points to non-existent lesson


# Rebuild the forward references
QuizWithLocation.model_rebuild()
QuizGroupedResponse.model_rebuild()
