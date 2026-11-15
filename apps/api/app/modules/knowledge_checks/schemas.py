"""Bounded input schemas and snapshot invariants."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Choice(StrictModel):
    id: UUID
    text: str = Field(min_length=1, max_length=4000)
    is_correct: bool


class Question(StrictModel):
    id: UUID
    text: str = Field(min_length=1, max_length=10000)
    type: Literal["MCQ", "multiple_choice", "true_false"]
    points: int = Field(gt=0, le=1000)
    explanation: str | None = Field(default=None, max_length=10000)
    choices: list[Choice] = Field(min_length=2, max_length=50)

    @model_validator(mode="after")
    def validate_choices(self) -> Self:
        if len({c.id for c in self.choices}) != len(self.choices):
            raise ValueError("duplicate choice id")
        correct = sum(c.is_correct for c in self.choices)
        if self.type == "true_false" and len(self.choices) != 2:
            raise ValueError("true_false requires two choices")
        if self.type == "multiple_choice":
            if not 0 < correct < len(self.choices):
                raise ValueError("multiple_choice requires some but not all correct choices")
        elif correct != 1:
            raise ValueError("single-answer question requires one correct choice")
        return self


class Content(StrictModel):
    title: str = Field(min_length=1, max_length=500)
    instructions: str = Field(default="", max_length=10000)
    pass_score: int = Field(ge=0, le=100)
    attempt_limit: int = Field(ge=1, le=100)
    time_limit_minutes: int | None = Field(default=None, ge=1, le=10080)
    questions: list[Question] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        if len({q.id for q in self.questions}) != len(self.questions):
            raise ValueError("duplicate question id")
        all_choices = [c.id for q in self.questions for c in q.choices]
        if len(set(all_choices)) != len(all_choices):
            raise ValueError("duplicate choice id")
        return self


class Create(Content):
    id: UUID


class Replace(Content):
    expected_revision: int = Field(ge=1)


class Revision(StrictModel):
    expected_revision: int = Field(ge=1)


class Assign(Revision):
    user_ids: list[UUID] = Field(min_length=1, max_length=500)
    due_at: datetime | None = None

    @field_validator("due_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("due_at must include timezone")
        return value

    @field_validator("user_ids")
    @classmethod
    def unique_users(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("duplicate user id")
        return value


class Answer(StrictModel):
    question_id: UUID
    selected_choice_ids: list[UUID] = Field(max_length=50)


class Answers(StrictModel):
    answers: list[Answer] = Field(max_length=200)
