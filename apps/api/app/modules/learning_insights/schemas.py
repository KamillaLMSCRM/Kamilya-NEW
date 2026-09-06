"""Wire models for the learning-insights V1 contract."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ReviewStatus = Literal[
    "unreviewed",
    "train_staff",
    "review_question",
    "improve_material",
    "resolved",
]
EvidenceStatus = Literal["verified", "unavailable", "invalid"]


class ReviewUpdate(BaseModel):
    status: ReviewStatus

    model_config = ConfigDict(extra="forbid")


class Review(BaseModel):
    status: ReviewStatus
    updated_at: datetime | None = None


class ChoiceDetail(BaseModel):
    id: str
    text: str
    selected: bool
    correct: bool


class QuestionDetail(BaseModel):
    question_id: str
    question_key: str
    text: str
    type: str
    explanation: str | None = None
    is_correct: bool
    points_earned: int
    points_possible: int
    choices: list[ChoiceDetail] = Field(default_factory=list)
    review: Review


class AttemptDetail(BaseModel):
    id: UUID
    quiz_id: UUID
    quiz_title: str
    content_release_id: UUID | None = None
    completed_at: datetime
    attempt_number: int
    score_percent: int
    passed: bool
    evidence_status: EvidenceStatus
    lesson_id: UUID | None = None
    questions: list[QuestionDetail] = Field(default_factory=list)


class EnrollmentInsights(BaseModel):
    enrollment_id: UUID
    user_name: str
    course_id: UUID
    course_title: str
    attempts: list[AttemptDetail] = Field(default_factory=list)


class WrongChoice(BaseModel):
    id: str
    text: str
    count: int


class QuestionStats(BaseModel):
    question_key: str
    question_id: str
    quiz_id: str
    quiz_title: str
    content_release_id: str | None = None
    text: str
    lesson_id: str | None = None
    respondents: int
    incorrect: int
    incorrect_percent: float
    latest_incorrect: int
    latest_respondents: int
    latest_unavailable: int
    latest_incorrect_percent: float | None
    improved: int
    regressed: int
    wrong_choices: list[WrongChoice] = Field(default_factory=list)
    review: Review
    example_attempt_id: str


class CourseInsights(BaseModel):
    course_id: UUID
    course_title: str
    cohort_basis: Literal["current_structure"] = "current_structure"
    attempt_basis: Literal["first_completed"] = "first_completed"
    included_employees: int
    excluded_attempts: int
    questions: list[QuestionStats] = Field(default_factory=list)
