from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CohortCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)


class CohortUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)


class CohortMembers(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_ids: list[UUID] = Field(default_factory=list, max_length=1000)


class CohortLinks(BaseModel):
    """Deprecated compatibility payload for the former links endpoint.

    Empty ``course_ids`` is accepted so older clients can migrate without a
    schema failure. Non-empty course links are rejected by the router and are
    never materialized.
    """

    model_config = ConfigDict(extra="forbid")
    user_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    course_ids: list[UUID] = Field(default_factory=list, max_length=200)


class CohortSummary(BaseModel):
    id: UUID
    name: str
    description: str
    is_active: bool
    member_count: int
    created_at: datetime


class CohortDetail(CohortSummary):
    user_ids: list[UUID]


class LearnerCohort(BaseModel):
    id: UUID
    name: str
    description: str
