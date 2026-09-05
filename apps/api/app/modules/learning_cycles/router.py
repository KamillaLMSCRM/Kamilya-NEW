# ruff: noqa: B008

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.courses import Course
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.learning_cycles.bridge import (
    reconcile_learning_path_assignment,
    sync_learning_path_rules,
)
from app.modules.learning_cycles.models import (
    LearningPathCycleInstance,
    RecurringLearningAssignment,
    RecurringLearningRule,
)
from app.modules.learning_cycles.schemas import (
    LearningPathSyncResponse,
    OccurrenceResponse,
    RuleCreate,
    RuleResponse,
    RuleUpdate,
)
from app.modules.learning_paths.models import LearningPath

router = APIRouter(prefix="/learning-cycles", tags=["learning-cycles"])


def occurrence_reporting_status(
    *,
    stored_status: str,
    due_at: datetime,
    completed_at: datetime | None,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(UTC)
    if completed_at is not None:
        return "completed_late" if completed_at > due_at else "completed"
    if stored_status == "assigned" and due_at < now:
        return "overdue"
    return stored_status


async def _owned_rule(db: AsyncSession, rule_id: UUID, tenant_id: UUID) -> RecurringLearningRule:
    rule = await db.scalar(
        select(RecurringLearningRule).where(
            RecurringLearningRule.id == rule_id,
            RecurringLearningRule.tenant_id == tenant_id,
        )
    )
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recurring rule not found")
    return rule


@router.get("", response_model=list[RuleResponse])
async def list_rules(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("methodologist")),
):
    return list(
        (
            await db.scalars(
                select(RecurringLearningRule)
                .where(RecurringLearningRule.tenant_id == user.tenant_id)
                .order_by(RecurringLearningRule.created_at.desc())
            )
        ).all()
    )


@router.get("/occurrences", response_model=list[OccurrenceResponse])
async def list_latest_occurrences(
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(require_role("methodologist")),
) -> list[OccurrenceResponse]:
    rows = (
        await db.execute(
            select(RecurringLearningAssignment, Enrollment.completed_at)
            .outerjoin(Enrollment, Enrollment.id == RecurringLearningAssignment.enrollment_id)
            .where(RecurringLearningAssignment.tenant_id == user.tenant_id)
            .order_by(
                RecurringLearningAssignment.rule_id,
                RecurringLearningAssignment.scheduled_for.desc(),
            )
        )
    ).all()
    latest = {}
    for occurrence, completed_at in rows:
        if occurrence.rule_id in latest:
            continue
        latest[occurrence.rule_id] = OccurrenceResponse(
            id=occurrence.id,
            rule_id=occurrence.rule_id,
            user_id=occurrence.user_id,
            target_type="course",
            course_id=occurrence.course_id,
            learning_path_id=None,
            enrollment_id=occurrence.enrollment_id,
            scheduled_for=occurrence.scheduled_for,
            due_at=occurrence.due_at,
            completed_at=completed_at,
            status=occurrence_reporting_status(
                stored_status=occurrence.status,
                due_at=occurrence.due_at,
                completed_at=completed_at,
            ),
        )
    path_rows = (
        await db.execute(
            select(LearningPathCycleInstance)
            .where(LearningPathCycleInstance.tenant_id == user.tenant_id)
            .order_by(
                LearningPathCycleInstance.rule_id,
                LearningPathCycleInstance.scheduled_for.desc(),
            )
        )
    ).scalars().all()
    for cycle in path_rows:
        if cycle.rule_id in latest:
            continue
        due_at = cycle.due_at or cycle.scheduled_for
        latest[cycle.rule_id] = OccurrenceResponse(
            id=cycle.id,
            rule_id=cycle.rule_id,
            user_id=cycle.user_id,
            target_type="learning_path",
            course_id=None,
            learning_path_id=cycle.path_id,
            enrollment_id=None,
            scheduled_for=cycle.scheduled_for,
            due_at=due_at,
            completed_at=cycle.completed_at,
            status=occurrence_reporting_status(
                stored_status=cast(str, cycle.status),
                due_at=cast(datetime, due_at),
                completed_at=cast(datetime | None, cycle.completed_at),
            ),
        )
    return list(latest.values())


@router.post("", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rule(
    body: RuleCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("methodologist")),
):
    if body.learning_path_id is not None:
        path = await db.scalar(
            select(LearningPath).where(
                LearningPath.id == body.learning_path_id,
                LearningPath.tenant_id == user.tenant_id,
                LearningPath.status == "published",
            )
        )
        if path is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Published learning path not found")
        if path.recurrence_mode != "fixed_interval_after_completion":
            raise HTTPException(status.HTTP_409_CONFLICT, "Learning path recurrence is not configured")
        result = await reconcile_learning_path_assignment(
            db,
            path=path,
            user_id=body.user_id,
            created_by=user.id,
        )
        if result.rule is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Active learner not found")
        if "reminder_enabled" in body.model_fields_set:
            cast(Any, result.rule).reminder_enabled = body.reminder_enabled
        if "reminder_days_before_due" in body.model_fields_set:
            cast(Any, result.rule).reminder_days_before_due = body.reminder_days_before_due
        return result.rule

    course = await db.scalar(
        select(Course.id).where(
            Course.id == body.course_id,
            Course.tenant_id == user.tenant_id,
            Course.status == "published",
        )
    )
    learner = await db.scalar(
        select(User.id).where(
            User.id == body.user_id,
            User.tenant_id == user.tenant_id,
            User.role == "student",
            User.is_active.is_(True),
            User.status == "active",
        )
    )
    if course is None or learner is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Published course or active learner not found",
        )
    rule = RecurringLearningRule(
        tenant_id=user.tenant_id,
        course_id=body.course_id,
        user_id=body.user_id,
        cadence_days=body.cadence_days,
        due_days=body.due_days,
        reminder_enabled=body.reminder_enabled,
        reminder_days_before_due=body.reminder_days_before_due,
        status="draft",
        created_by=user.id,
    )
    db.add(rule)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A recurring rule already exists for this learner and course",
        ) from exc
    return rule


@router.patch("/{rule_id}", response_model=RuleResponse)
async def update_rule(
    rule_id: UUID,
    body: RuleUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("methodologist")),
):
    rule = await _owned_rule(db, rule_id, user.tenant_id)
    if getattr(rule, "learning_path_id", None) is not None and (
        body.cadence_days is not None or body.due_days is not None
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "LearningPath recurrence cadence and due are source-controlled",
        )
    next_cadence = body.cadence_days if body.cadence_days is not None else rule.cadence_days
    next_due = body.due_days if body.due_days is not None else rule.due_days
    if next_due > next_cadence:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "due_days must not exceed cadence_days")
    if body.cadence_days is not None:
        rule.cadence_days = body.cadence_days
    if body.due_days is not None:
        rule.due_days = body.due_days
    if body.reminder_enabled is not None:
        cast(Any, rule).reminder_enabled = body.reminder_enabled
    if body.reminder_days_before_due is not None:
        cast(Any, rule).reminder_days_before_due = body.reminder_days_before_due
    return rule


@router.get("/{rule_id}/reminders")
async def reminder_statuses(
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("methodologist")),
) -> list[dict[str, Any]]:
    await _owned_rule(db, rule_id, user.tenant_id)
    from sqlalchemy import text

    rows = await db.execute(
        text("SELECT * FROM public.learning_reminder_statuses(:tenant_id,:rule_id)"),
        {"tenant_id": user.tenant_id, "rule_id": rule_id},
    )
    return [dict(row) for row in rows.mappings()]


@router.post("/{rule_id}/activate", response_model=RuleResponse)
async def activate(
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("methodologist")),
):
    rule = await _owned_rule(db, rule_id, user.tenant_id)
    if getattr(rule, "learning_path_id", None) is not None:
        path = await db.scalar(
            select(LearningPath).where(
                LearningPath.id == rule.learning_path_id,
                LearningPath.tenant_id == user.tenant_id,
                LearningPath.status == "published",
            )
        )
        if path is None or path.recurrence_mode != "fixed_interval_after_completion":
            raise HTTPException(status.HTTP_409_CONFLICT, "Only published recurring learning paths support recurring delivery")
        cast(Any, rule).status = "active"
        # A path repeat is armed by completion of its current path assignment.
        return rule
    course = await db.scalar(select(Course).where(Course.id == rule.course_id, Course.tenant_id == user.tenant_id))
    if course is None or course.status != "published" or course.delivery_type == "scorm":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only published native courses support recurring delivery")
    rule.status = "active"
    rule.next_run_at = rule.next_run_at or datetime.now(UTC)
    return rule


@router.post("/learning-paths/{path_id}/sync", response_model=LearningPathSyncResponse)
async def sync_learning_path(
    path_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("methodologist")),
):
    path = await db.scalar(
        select(LearningPath).where(
            LearningPath.id == path_id,
            LearningPath.tenant_id == user.tenant_id,
            LearningPath.status == "published",
        )
    )
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Published learning path not found")
    result = await sync_learning_path_rules(db, path=path, created_by=user.id)
    await db.flush()
    return LearningPathSyncResponse(path_id=path.id, **result.__dict__)


@router.post("/{rule_id}/deactivate", response_model=RuleResponse)
async def deactivate(
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("methodologist")),
):
    rule = await _owned_rule(db, rule_id, user.tenant_id)
    rule.status = "inactive"
    rule.claimed_at = None
    rule.claim_token = None
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("methodologist")),
) -> Response:
    rule = await _owned_rule(db, rule_id, user.tenant_id)
    if rule.last_run_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A materialized rule is immutable; deactivate it instead",
        )
    await db.delete(rule)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
