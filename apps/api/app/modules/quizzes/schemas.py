"""Quiz schemas"""
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional


class QuizChoiceResponse(BaseModel):
    id: UUID
    text: str
    order_index: int
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
    questions: list[QuestionResponse] = []
    model_config = {"from_attributes": True}


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
