"""Lessons module — schemas"""
import json
from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field, field_validator


class ModuleCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    order_index: int = Field(ge=0, default=0)

class ModuleUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    order_index: Optional[int] = Field(default=None, ge=0)
    ai_generated: Optional[bool] = None

class ModuleResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    course_id: UUID
    title: str
    description: str
    order_index: int
    ai_generated: bool
    source_document_ids: list[str] = Field(default_factory=list)
    source_references: list[dict] = Field(default_factory=list)
    source_validation_status: str = "not_applicable"
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

class LessonCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field(default="text")
    content: Optional[str] = None
    duration_seconds: Optional[int] = None
    order_index: int = Field(ge=0, default=0)

class LessonUpdate(BaseModel):
    title: Optional[str] = None
    content_type: Optional[str] = None
    content: Optional[str] = None
    duration_seconds: Optional[int] = None
    order_index: Optional[int] = None
    ai_generated: Optional[bool] = None
    published_at: Optional[datetime] = None

class LessonResponse(BaseModel):
    id: UUID
    module_id: UUID
    tenant_id: UUID
    title: str
    content_type: str
    content: Optional[str] = None
    duration_seconds: Optional[int] = None
    order_index: int
    ai_generated: bool
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

class ContentBlockCreate(BaseModel):
    lesson_id: UUID
    block_type: str
    content: Optional[str] = None
    order_index: int = Field(ge=0, default=0)
    metadata: Optional[str] = None

class ContentBlockResponse(BaseModel):
    id: UUID
    lesson_id: UUID
    block_type: str
    content: Optional[str] = None
    order_index: int
    metadata: Optional[str] = Field(default=None, validation_alias=AliasChoices("metadata_", "metadata"))
    created_at: datetime
    model_config = {"from_attributes": True}

    @field_validator("metadata", mode="before")
    @classmethod
    def serialize_legacy_metadata(cls, value: Any) -> Any:
        if isinstance(value, dict | list | bool | int | float):
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return value

class CourseStructureResponse(BaseModel):
    id: UUID
    title: str
    description: str
    status: str
    modules: List["ModuleWithLessonsResponse"]
    model_config = {"from_attributes": True}

class ModuleWithLessonsResponse(BaseModel):
    id: UUID
    title: str
    description: str
    order_index: int
    lessons: List[LessonResponse]
