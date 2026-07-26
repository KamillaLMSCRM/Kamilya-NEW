from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LearningPathCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    sequencing_mode: str = Field(default="linear", pattern="^(linear|open)$")


class LearningPathUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    sequencing_mode: str | None = Field(default=None, pattern="^(linear|open)$")


class LearningPathStepInput(BaseModel):
    course_id: UUID
    required: bool = True


class LearningPathCurriculumReplace(BaseModel):
    steps: list[LearningPathStepInput] = Field(default_factory=list, max_length=100)


class LearningPathCourseItem(BaseModel):
    course_id: UUID
    title: str
    order_index: int
    required: bool


class LearningPathSummary(BaseModel):
    id: UUID
    family_id: UUID
    version: int
    title: str
    description: str
    status: str
    sequencing_mode: str
    course_count: int
    assignment_count: int = 0
    published_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LearningPathDetail(LearningPathSummary):
    courses: list[LearningPathCourseItem]


class LearningPathAssignmentAudience(BaseModel):
    user_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    cohort_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    department_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    position_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    starts_at: datetime | None = None
    due_at: datetime | None = None


class LearningPathAssignmentResponse(BaseModel):
    id: UUID
    path_id: UUID
    user_id: UUID
    source: str
    source_ref_id: UUID | None = None
    assigned_by: UUID | None = None
    starts_at: datetime | None = None
    due_at: datetime | None = None
    status: str
    created_at: datetime
    cancelled_at: datetime | None = None
    completed_at: datetime | None = None
    user_name: str | None = None
    user_email: str | None = None

    model_config = ConfigDict(from_attributes=True)


class LearningPathAssignmentResult(BaseModel):
    added: int
    skipped: int
    total: int
    assignments: list[LearningPathAssignmentResponse]


class LearnerPathStep(BaseModel):
    course_id: UUID
    title: str
    order_index: int
    required: bool
    state: str = Field(pattern="^(locked|available|completed)$")


class LearnerPathItem(BaseModel):
    id: UUID
    assignment_id: UUID
    family_id: UUID
    version: int
    title: str
    description: str
    sequencing_mode: str
    starts_at: datetime | None = None
    due_at: datetime | None = None
    total_required_courses: int
    completed_required_courses: int
    progress_percent: int
    current_course_id: UUID | None = None
    steps: list[LearnerPathStep]
