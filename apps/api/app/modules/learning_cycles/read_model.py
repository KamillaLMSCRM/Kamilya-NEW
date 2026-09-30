"""Shared, read-only enrollment/cycle deadline projection."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, func, literal
from sqlalchemy.sql.elements import ColumnElement

from app.models.enrollment import Enrollment
from app.models.enrollment_access_policy import EnrollmentAccessPolicy
from app.modules.learning_cycles.models import LearningPathCycleInstance, RecurringLearningAssignment
from app.modules.learning_paths.models import LearningPathAssignment
from app.modules.training_log.deadline_policy import deadline_status_sql


@dataclass(frozen=True)
class CycleReadColumns:
    cycle_id: Any
    cycle_type: Any
    scheduled_for: Any
    due_at: Any
    assignment_due_at: Any
    eligible: Any

    def deadline_status(self) -> ColumnElement[str]:
        return deadline_status_sql(
            due_at=self.due_at,
            completed_at=Enrollment.completed_at,
            enrollment_status=Enrollment.status,
            eligible=self.eligible,
        )


def join_cycle_read_model(stmt: Any, tenant_id: UUID) -> tuple[Any, CycleReadColumns]:
    """Attach direct-course and learning-path cycle identity without writes."""
    stmt = stmt.outerjoin(
        RecurringLearningAssignment,
        and_(
            RecurringLearningAssignment.id == Enrollment.recurring_assignment_id,
            RecurringLearningAssignment.tenant_id == tenant_id,
            RecurringLearningAssignment.user_id == Enrollment.user_id,
            RecurringLearningAssignment.course_id == Enrollment.course_id,
            RecurringLearningAssignment.enrollment_id == Enrollment.id,
        ),
    )
    stmt = stmt.outerjoin(
        LearningPathAssignment,
        and_(
            LearningPathAssignment.id == Enrollment.learning_path_assignment_id,
            LearningPathAssignment.tenant_id == tenant_id,
            LearningPathAssignment.user_id == Enrollment.user_id,
        ),
    )
    stmt = stmt.outerjoin(
        LearningPathCycleInstance,
        and_(
            LearningPathCycleInstance.id == LearningPathAssignment.recurrence_instance_id,
            LearningPathCycleInstance.tenant_id == tenant_id,
            LearningPathCycleInstance.user_id == Enrollment.user_id,
            LearningPathCycleInstance.path_id == LearningPathAssignment.path_id,
        ),
    )
    stmt = stmt.outerjoin(
        EnrollmentAccessPolicy,
        and_(
            EnrollmentAccessPolicy.enrollment_id == Enrollment.id,
            EnrollmentAccessPolicy.tenant_id == tenant_id,
            EnrollmentAccessPolicy.user_id == Enrollment.user_id,
        ),
    )
    cycle_due_at = func.coalesce(
        RecurringLearningAssignment.effective_due_at,
        LearningPathCycleInstance.effective_due_at,
    )
    cycle_eligible = case(
        (
            RecurringLearningAssignment.id.is_not(None),
            RecurringLearningAssignment.status.in_(("assigned", "completed")),
        ),
        else_=and_(
            LearningPathCycleInstance.status.in_(("active", "completed")),
            LearningPathAssignment.status.in_(("active", "completed")),
        ),
    )
    assignment_due_at = func.coalesce(
        EnrollmentAccessPolicy.due_at,
        case((cycle_eligible.is_(True), cycle_due_at), else_=None),
    )
    return stmt, CycleReadColumns(
        cycle_id=func.coalesce(RecurringLearningAssignment.id, LearningPathCycleInstance.id),
        cycle_type=case(
            (RecurringLearningAssignment.id.is_not(None), literal("course")),
            (LearningPathCycleInstance.id.is_not(None), literal("learning_path")),
            else_=None,
        ),
        scheduled_for=func.coalesce(
            RecurringLearningAssignment.scheduled_for,
            LearningPathCycleInstance.scheduled_for,
        ),
        due_at=cycle_due_at,
        assignment_due_at=assignment_due_at,
        eligible=cycle_eligible,
    )
