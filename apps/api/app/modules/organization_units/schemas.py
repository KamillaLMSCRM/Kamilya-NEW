from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .domain import OrganizationUnitType


class OrganizationUnitCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    unit_type: OrganizationUnitType
    parent_id: UUID | None = None
    external_key: str | None = Field(default=None, min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    code: str | None = Field(default=None, max_length=100)
    is_head_office: bool = False
    head_user_id: UUID | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_shape(self) -> OrganizationUnitCreate:
        if self.is_head_office and self.parent_id is not None:
            raise ValueError("head office must be a root organization unit")
        return self


class OrganizationUnitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    parent_id: UUID | None = None
    external_key: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    code: str | None = Field(default=None, max_length=100)
    is_head_office: bool | None = None
    head_user_id: UUID | None = None

    model_config = ConfigDict(extra="forbid")


class OrganizationUnitArchive(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)

    model_config = ConfigDict(extra="forbid")


class OrganizationUnitMovePreviewRequest(BaseModel):
    parent_id: UUID | None = None

    model_config = ConfigDict(extra="forbid")


class OrganizationUnitMovePreviewResponse(BaseModel):
    unit_id: UUID
    parent_id: UUID | None
    affected_units: int
    affected_positions: int
    affected_employees: int
    resulting_depth: int
    subtree_height: int


class OrganizationUnitResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    unit_type: OrganizationUnitType
    parent_id: UUID | None
    external_key: str | None
    is_active: bool
    legacy_root: bool
    description: str
    code: str | None
    created_at: datetime
    is_head_office: bool = False
    head_user_id: UUID | None = None
    depth: int | None = None
    breadcrumb: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class OrganizationUnitEmployee(BaseModel):
    """Employee projection used by the staff Structure screen.

    This is deliberately a tenant-scoped, non-sensitive projection.  Email,
    phone and other contact fields are not part of the tree payload.
    """

    id: UUID
    full_name: str
    personnel_number: str | None = None
    is_active: bool
    assigned_courses: int = 0
    completed_courses: int = 0
    ready_percent: int = 0


class OrganizationUnitPosition(BaseModel):
    id: UUID
    name: str
    department: str
    department_slug: str | None = None
    employee_count: int = 0
    ready_percent: int = 0
    employees: list[OrganizationUnitEmployee] = Field(default_factory=list)


class OrganizationUnitTreeNode(OrganizationUnitResponse):
    children: list[OrganizationUnitTreeNode] = Field(default_factory=list)
    # A branch contains departments in ``children``; a department/legacy root
    # exposes its positions directly.  Keeping children preserves the
    # canonical unit hierarchy while these projections make the endpoint
    # sufficient for the Structure UI without a second request.
    department_count: int = 0
    position_count: int = 0
    employee_count: int = 0
    ready_percent: int = 0
    positions: list[OrganizationUnitPosition] = Field(default_factory=list)


class OrganizationUnitTreeResponse(BaseModel):
    branches: list[OrganizationUnitTreeNode]
    legacy_roots: list[OrganizationUnitTreeNode]
    roots: list[OrganizationUnitTreeNode] = Field(default_factory=list)
    unassigned_legacy_positions: list[OrganizationUnitPosition] = Field(default_factory=list)
    summary: dict[str, int]


OrganizationUnitTreeNode.model_rebuild()
