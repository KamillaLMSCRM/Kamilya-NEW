from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field


class SurveyQuestion(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    text: str = Field(..., min_length=1, max_length=1000)
    type: Literal["rating", "text"] = "rating"
    required: bool = True


class SurveyCreate(BaseModel):
    course_id: UUID
    title: str = Field(..., min_length=1, max_length=255)
    status: Literal["draft", "published"] = "draft"
    questions: list[SurveyQuestion] = Field(..., min_length=1, max_length=20)


class SurveySummary(BaseModel):
    id: UUID
    course_id: UUID
    title: str
    status: str
    question_count: int
    created_at: datetime


class SurveyDetail(SurveySummary):
    questions: list[SurveyQuestion]


class SurveyAnswerSubmit(BaseModel):
    answers: dict[str, str | int | None]


class LearnerSurvey(BaseModel):
    id: UUID
    course_id: UUID
    course_title: str
    title: str
    questions: list[SurveyQuestion]
    submitted: bool
