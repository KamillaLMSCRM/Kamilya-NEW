"""Methodologist API for persistent organization-wide course rules."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.courses import Course
from app.models.department import Department
from app.models.users import User
from app.modules.positions.assignment_service import preview_rule_change
from app.modules.positions.batch_service import recompute_tenant_members
from app.modules.positions.models import DepartmentCourse
from app.modules.training_rules.models import OrganizationCourseRule

router = APIRouter(prefix="/training-rules", tags=["training-rules"])


class OrganizationCourseRuleRequest(BaseModel):
    course_id: UUID
    required: bool = True


class OrganizationCourseRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    course_id: UUID
    required: bool
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime
    enrollments_added: int | None = None
    enrollments_removed: int | None = None


class OrganizationCourseRuleListResponse(BaseModel):
    rules: list[OrganizationCourseRuleResponse]


class RulePreviewRequest(BaseModel):
    scope: Literal["organization", "department"]
    operation: Literal["attach", "detach"]
    course_id: UUID
    department_id: str | None = None


class RulePreviewResponse(BaseModel):
    affected_employees: int
    enrollments_to_add: int
    in_progress_to_remove: int
    protected_completed: int
    protected_other_sources: int


async def _published_tenant_course(
    db: AsyncSession,
    tenant_id: UUID,
    course_id: UUID,
) -> Course:
    course = await db.scalar(
        select(Course).where(
            Course.id == course_id,
            Course.tenant_id == tenant_id,
            Course.status == "published",
        )
    )
    if course is None:
        # Do not disclose whether the UUID exists in another tenant or is draft.
        raise HTTPException(status_code=404, detail="Published course not found")
    return course


async def _preview_department(
    db: AsyncSession,
    tenant_id: UUID,
    locator: str,
) -> Department:
    try:
        department_uuid = UUID(locator)
    except (ValueError, TypeError):
        department_uuid = None
    if department_uuid is not None:
        statement = select(Department).where(
            Department.id == department_uuid,
            Department.tenant_id == tenant_id,
        )
    else:
        statement = select(Department).where(
            Department.slug == locator.strip().lower(),
            Department.tenant_id == tenant_id,
        )
    department = await db.scalar(statement)
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")
    return department


@router.post("/preview", response_model=RulePreviewResponse)
async def preview_training_rule_change(
    body: RulePreviewRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    if body.operation == "attach":
        await _published_tenant_course(db, user.tenant_id, body.course_id)
    else:
        course = await db.scalar(
            select(Course).where(Course.id == body.course_id, Course.tenant_id == user.tenant_id)
        )
        if course is None:
            raise HTTPException(status_code=404, detail="Course not found")

    department_id: UUID | None = None
    if body.scope == "organization":
        rule = await db.scalar(
            select(OrganizationCourseRule).where(
                OrganizationCourseRule.tenant_id == user.tenant_id,
                OrganizationCourseRule.course_id == body.course_id,
            )
        )
    else:
        if not body.department_id:
            raise HTTPException(status_code=422, detail="department_id is required for department rules")
        department = await _preview_department(db, user.tenant_id, body.department_id)
        department_id = department.id
        rule = await db.scalar(
            select(DepartmentCourse).where(
                DepartmentCourse.tenant_id == user.tenant_id,
                DepartmentCourse.department_id == department_id,
                DepartmentCourse.course_id == body.course_id,
            )
        )
    if body.operation == "detach" and rule is None:
        raise HTTPException(status_code=404, detail="Training rule not found")

    impact = await preview_rule_change(
        db,
        tenant_id=user.tenant_id,
        scope=body.scope,
        operation=body.operation,
        course_id=body.course_id,
        department_id=department_id,
    )
    return RulePreviewResponse(**impact.to_dict())


@router.get("/organization", response_model=OrganizationCourseRuleListResponse)
async def list_organization_course_rules(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    result = await db.execute(
        select(OrganizationCourseRule)
        .where(OrganizationCourseRule.tenant_id == user.tenant_id)
        .order_by(OrganizationCourseRule.created_at.asc())
    )
    return OrganizationCourseRuleListResponse(
        rules=[OrganizationCourseRuleResponse.model_validate(rule) for rule in result.scalars().all()]
    )


@router.post(
    "/organization",
    response_model=OrganizationCourseRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def attach_organization_course_rule(
    body: OrganizationCourseRuleRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    await _published_tenant_course(db, user.tenant_id, body.course_id)
    rule = await db.scalar(
        select(OrganizationCourseRule).where(
            OrganizationCourseRule.tenant_id == user.tenant_id,
            OrganizationCourseRule.course_id == body.course_id,
        )
    )
    if rule is None:
        rule = OrganizationCourseRule(
            tenant_id=user.tenant_id,
            course_id=body.course_id,
            required=body.required,
            created_by=user.id,
        )
        db.add(rule)
    else:
        rule.required = body.required
    await db.flush()

    batch = await recompute_tenant_members(db, user.tenant_id)
    await db.flush()
    return OrganizationCourseRuleResponse(
        id=rule.id,
        tenant_id=rule.tenant_id,
        course_id=rule.course_id,
        required=rule.required,
        created_by=rule.created_by,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
        enrollments_added=batch.added,
        enrollments_removed=batch.removed,
    )


@router.delete("/organization/{course_id}", response_model=OrganizationCourseRuleResponse)
async def detach_organization_course_rule(
    course_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("methodologist")),
):
    rule = await db.scalar(
        select(OrganizationCourseRule).where(
            OrganizationCourseRule.tenant_id == user.tenant_id,
            OrganizationCourseRule.course_id == course_id,
        )
    )
    if rule is None:
        raise HTTPException(status_code=404, detail="Organization course rule not found")

    response = OrganizationCourseRuleResponse.model_validate(rule)
    await db.delete(rule)
    await db.flush()
    batch = await recompute_tenant_members(db, user.tenant_id)
    await db.flush()
    return response.model_copy(
        update={
            "enrollments_added": batch.added,
            "enrollments_removed": batch.removed,
        }
    )
