"""Activate and deactivate course assignment rules at publication time."""
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.courses import Course
from app.modules.positions.batch_service import (
    recompute_department_members,
    recompute_position_holders,
)
from app.modules.positions.models import DepartmentCourse, PositionCourse


async def _bound_rule_ids(
    db: AsyncSession,
    course: Course,
) -> tuple[list[UUID], list[UUID]]:
    position_result = await db.execute(
        select(PositionCourse.position_id).where(
            PositionCourse.course_id == course.id,
            PositionCourse.tenant_id == course.tenant_id,
        )
    )
    department_result = await db.execute(
        select(DepartmentCourse.department_id).where(
            DepartmentCourse.course_id == course.id,
            DepartmentCourse.tenant_id == course.tenant_id,
        )
    )
    return (
        list(position_result.scalars().all()),
        list(department_result.scalars().all()),
    )


async def activate_course_assignments(db: AsyncSession, course: Course) -> None:
    """Materialize rules for a newly published course.

    For a regenerated job-instruction course, the new version replaces older
    bindings from the same source document for the same position. Completed
    enrollments remain protected by the assignment kernel.
    """
    position_ids, department_ids = await _bound_rule_ids(db, course)

    if course.source_instruction_id is not None and position_ids:
        prior_course_ids = select(Course.id).where(
            Course.tenant_id == course.tenant_id,
            Course.source_instruction_id.is_not(None),
            Course.id != course.id,
        )
        await db.execute(
            delete(PositionCourse).where(
                PositionCourse.tenant_id == course.tenant_id,
                PositionCourse.position_id.in_(position_ids),
                PositionCourse.course_id.in_(prior_course_ids),
            )
        )
        await db.flush()

    for position_id in position_ids:
        await recompute_position_holders(db, position_id, course.tenant_id)
    for department_id in department_ids:
        await recompute_department_members(db, department_id, course.tenant_id)


async def refresh_course_assignments(db: AsyncSession, course: Course) -> None:
    """Recompute affected users after a course leaves published state."""
    position_ids, department_ids = await _bound_rule_ids(db, course)
    for position_id in position_ids:
        await recompute_position_holders(db, position_id, course.tenant_id)
    for department_id in department_ids:
        await recompute_department_members(db, department_id, course.tenant_id)
