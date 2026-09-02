"""Learning-program delivery rules.

The assignment table is the source of truth for who may see a program. An
enrollment is a materialized access record only: it is created for courses
that the learner can currently open and is deliberately never deleted here.
That conservative rule prevents a cancelled program from revoking a course
which may also have been granted manually or by an organisation rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enrollment import Enrollment
from app.modules.learning_cycles.models import LearningPathCycleInstance, RecurringLearningRule
from app.modules.learning_paths.models import (
    LearningPath,
    LearningPathAssignment,
    LearningPathCourse,
)


@dataclass(frozen=True)
class StepState:
    course_id: UUID
    state: str


def path_step_states(
    steps: list[LearningPathCourse],
    completed_course_ids: set[UUID],
    sequencing_mode: str,
) -> list[StepState]:
    """Return learner-visible states for an ordered curriculum.

    Linear programs release a step when every earlier *required* step is
    complete. Optional steps therefore do not block later courses, but become
    available only once the learner has reached their point in the sequence.
    """
    states: list[StepState] = []
    previous_required_complete = True
    for step in sorted(steps, key=lambda item: item.order_index):
        if step.course_id in completed_course_ids:
            state = "completed"
        elif sequencing_mode == "open" or previous_required_complete:
            state = "available"
        else:
            state = "locked"
        states.append(StepState(course_id=cast(UUID, step.course_id), state=state))
        if step.required and step.course_id not in completed_course_ids:
            previous_required_complete = False
    return states


async def _completed_course_ids(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    course_ids: list[UUID],
    learning_path_assignment_id: UUID,
) -> set[UUID]:
    if not course_ids:
        return set()
    result = await db.execute(
        select(Enrollment.course_id).where(
            Enrollment.tenant_id == tenant_id,
            Enrollment.user_id == user_id,
            Enrollment.course_id.in_(course_ids),
            Enrollment.status == "completed",
            Enrollment.learning_path_assignment_id == learning_path_assignment_id,
        )
    )
    return set(result.scalars().all())


async def _load_assignment_path(
    db: AsyncSession, assignment: LearningPathAssignment
) -> LearningPath:
    result = await db.execute(
        select(LearningPath)
        .options(selectinload(LearningPath.courses).selectinload(LearningPathCourse.course))
        .where(
            LearningPath.id == assignment.path_id,
            LearningPath.tenant_id == assignment.tenant_id,
        )
    )
    path = result.scalar_one_or_none()
    if path is None:
        raise RuntimeError("Learning-path assignment references a missing tenant path")
    return path


async def _schedule_recurrence_after_completion(
    db: AsyncSession,
    assignment: LearningPathAssignment,
    path: LearningPath,
    *,
    completed_at: datetime,
) -> None:
    if (
        path.recurrence_mode != "fixed_interval_after_completion"
        or path.recurrence_cadence_days is None
        or path.recurrence_due_days is None
    ):
        return

    next_run_at = completed_at + timedelta(days=cast(int, path.recurrence_cadence_days))
    rule = await db.scalar(
        select(RecurringLearningRule)
        .where(
            RecurringLearningRule.tenant_id == assignment.tenant_id,
            RecurringLearningRule.learning_path_id == assignment.path_id,
            RecurringLearningRule.user_id == assignment.user_id,
        )
        .with_for_update()
    )
    # The rule is deliberately NULL while its current assignment is active.
    # This guard makes repeated completion idempotent and prevents an older
    # completion from moving an already-scheduled occurrence forward.
    if rule is not None and rule.status == "active" and rule.next_run_at is None:
        rule.next_run_at = next_run_at

    if assignment.recurrence_instance_id is not None:
        cycle = await db.scalar(
            select(LearningPathCycleInstance)
            .where(
                LearningPathCycleInstance.id == assignment.recurrence_instance_id,
                LearningPathCycleInstance.tenant_id == assignment.tenant_id,
            )
            .with_for_update()
        )
        if cycle is not None and cycle.status != "completed":
            writable_cycle = cast(Any, cycle)
            writable_cycle.status = "completed"
            writable_cycle.completed_at = completed_at


async def sync_assignment_enrollments(
    db: AsyncSession,
    assignment: LearningPathAssignment,
    *,
    now: datetime | None = None,
) -> int:
    """Materialize currently available program courses for one assignment.

    The function does not commit. Callers can include program updates, course
    completion and enrollment materialization in the same transaction.
    """
    now = now or datetime.now(UTC)
    if (
        assignment.status != "active"
        or assignment.starts_at is not None
        and assignment.starts_at > now
    ):
        return 0

    path = await _load_assignment_path(db, assignment)
    if path.status != "published":
        return 0
    steps = [step for step in path.courses if step.course is not None and step.course.status == "published"]
    course_ids = [step.course_id for step in steps]
    completed = await _completed_course_ids(
        db,
        tenant_id=assignment.tenant_id,
        user_id=assignment.user_id,
        course_ids=course_ids,
        learning_path_assignment_id=assignment.id,
    )
    states = path_step_states(steps, completed, path.sequencing_mode)
    available_course_ids = [state.course_id for state in states if state.state == "available"]

    if available_course_ids:
        existing = await db.execute(
            select(Enrollment.course_id).where(
                Enrollment.tenant_id == assignment.tenant_id,
                Enrollment.user_id == assignment.user_id,
                Enrollment.course_id.in_(available_course_ids),
                Enrollment.learning_path_assignment_id == assignment.id,
            )
        )
        existing_course_ids = set(existing.scalars().all())
    else:
        existing_course_ids = set()

    added = 0
    for course_id in available_course_ids:
        if course_id not in existing_course_ids:
            db.add(
                Enrollment(
                    course_id=course_id,
                    user_id=assignment.user_id,
                    tenant_id=assignment.tenant_id,
                    status="enrolled",
                    source="learning_path",
                    learning_path_assignment_id=assignment.id,
                )
            )
            added += 1

    required_course_ids = {step.course_id for step in steps if step.required}
    completion_course_ids = required_course_ids or set(course_ids)
    if completion_course_ids and completion_course_ids.issubset(completed):
        assignment.status = "completed"
        assignment.completed_at = now
        await _schedule_recurrence_after_completion(
            db,
            assignment,
            path,
            completed_at=now,
        )
    if added:
        await db.flush()
    return added


async def sync_learning_path_enrollments_after_course_completion(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    now: datetime | None = None,
    return_completed_assignments: bool = False,
) -> int | list[LearningPathAssignment]:
    """Release next steps after a learner completes any course."""
    now = now or datetime.now(UTC)
    result = await db.execute(
        select(LearningPathAssignment)
        .join(LearningPath, LearningPath.id == LearningPathAssignment.path_id)
        .options(selectinload(LearningPathAssignment.path).selectinload(LearningPath.courses).selectinload(LearningPathCourse.course))
        .where(
            LearningPathAssignment.tenant_id == tenant_id,
            LearningPathAssignment.user_id == user_id,
            LearningPathAssignment.status == "active",
            LearningPath.status == "published",
            (LearningPathAssignment.starts_at.is_(None)) | (LearningPathAssignment.starts_at <= now),
        )
    )
    added = 0
    completed_assignments: list[LearningPathAssignment] = []
    for assignment in result.scalars().unique().all():
        was_active = assignment.status == "active"
        added += await sync_assignment_enrollments(db, assignment, now=now)
        if was_active and assignment.status == "completed":
            completed_assignments.append(assignment)
    if return_completed_assignments:
        return completed_assignments
    return added
