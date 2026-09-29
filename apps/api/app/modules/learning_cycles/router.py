# ruff: noqa: B008

from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.db import get_db
from app.models.courses import Course
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.audit.service import log_action
from app.modules.learning_cycles.bridge import (
    reconcile_learning_path_assignment,
    sync_learning_path_rules,
)
from app.modules.learning_cycles.models import (
    LearningCycleParticipantEvent,
    LearningPathCycleInstance,
    RecurringLearningAssignment,
    RecurringLearningRule,
)
from app.modules.learning_cycles.schemas import (
    DeadlineOverrideRequest,
    LearningPathSyncResponse,
    OccurrenceResponse,
    ParticipantEventResponse,
    RuleCreate,
    RuleResponse,
    RuleUpdate,
)
from app.modules.learning_paths.models import LearningPath

router = APIRouter(prefix="/learning-cycles", tags=["learning-cycles"])


def _rule_actor_id(user: Any) -> UUID | None:
    """Return a tenant-valid author while preserving impersonation audit identity."""
    if getattr(user, "is_impersonating", False):
        return None
    return cast(UUID, user.id)


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
    if stored_status in {"assigned", "active"} and due_at < now:
        return "overdue"
    return stored_status


def _course_occurrence_response(
    occurrence: RecurringLearningAssignment,
    completed_at: datetime | None,
    *,
    learner: User,
) -> OccurrenceResponse:
    effective_due_at = cast(datetime, occurrence.effective_due_at or occurrence.due_at)
    return OccurrenceResponse(
        id=occurrence.id,
        rule_id=occurrence.rule_id,
        user_id=occurrence.user_id,
        target_type="course",
        course_id=occurrence.course_id,
        learning_path_id=None,
        enrollment_id=occurrence.enrollment_id,
        sequence_no=occurrence.sequence_no,
        content_release_id=occurrence.content_release_id,
        scheduled_for=occurrence.scheduled_for,
        original_due_at=occurrence.due_at,
        effective_due_at=effective_due_at,
        due_at=effective_due_at,
        completed_at=completed_at,
        status=occurrence_reporting_status(
            stored_status=cast(str, occurrence.status),
            due_at=effective_due_at,
            completed_at=completed_at,
        ),
        learner_name=f"{learner.first_name} {learner.last_name}".strip(),
        learner_personnel_number=cast(str | None, learner.personnel_number),
        learner_is_active=cast(bool, learner.is_active),
    )


def _path_occurrence_response(cycle: LearningPathCycleInstance, *, learner: User) -> OccurrenceResponse:
    original_due_at = cast(datetime, cycle.due_at or cycle.scheduled_for)
    effective_due_at = cast(datetime, cycle.effective_due_at or original_due_at)
    return OccurrenceResponse(
        id=cycle.id,
        rule_id=cycle.rule_id,
        user_id=cycle.user_id,
        target_type="learning_path",
        course_id=None,
        learning_path_id=cycle.path_id,
        enrollment_id=None,
        sequence_no=cycle.sequence_no,
        content_release_id=None,
        scheduled_for=cycle.scheduled_for,
        original_due_at=original_due_at,
        effective_due_at=effective_due_at,
        due_at=effective_due_at,
        completed_at=cycle.completed_at,
        status=occurrence_reporting_status(
            stored_status=cast(str, cycle.status),
            due_at=effective_due_at,
            completed_at=cast(datetime | None, cycle.completed_at),
        ),
        learner_name=f"{learner.first_name} {learner.last_name}".strip(),
        learner_personnel_number=cast(str | None, learner.personnel_number),
        learner_is_active=cast(bool, learner.is_active),
    )


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
    scope: Literal["latest", "history"] = Query("latest"),
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(require_role("methodologist")),
) -> list[OccurrenceResponse]:
    rows = (
        await db.execute(
            select(RecurringLearningAssignment, Enrollment.completed_at, User)
            .outerjoin(Enrollment, Enrollment.id == RecurringLearningAssignment.enrollment_id)
            .join(User, User.id == RecurringLearningAssignment.user_id)
            .where(RecurringLearningAssignment.tenant_id == user.tenant_id)
            .order_by(
                RecurringLearningAssignment.rule_id,
                RecurringLearningAssignment.scheduled_for.desc(),
            )
        )
    ).all()
    responses: list[OccurrenceResponse] = []
    for occurrence, completed_at, learner in rows:
        responses.append(_course_occurrence_response(occurrence, completed_at, learner=learner))
    path_rows = (
        await db.execute(
            select(LearningPathCycleInstance, User)
            .join(User, User.id == LearningPathCycleInstance.user_id)
            .where(LearningPathCycleInstance.tenant_id == user.tenant_id)
            .order_by(
                LearningPathCycleInstance.rule_id,
                LearningPathCycleInstance.scheduled_for.desc(),
            )
        )
    ).all()
    for cycle, learner in path_rows:
        responses.append(_path_occurrence_response(cycle, learner=learner))
    responses.sort(key=lambda item: (item.scheduled_for, str(item.id)), reverse=True)
    if scope == "history":
        return responses
    latest: dict[UUID, OccurrenceResponse] = {}
    for occurrence in responses:
        latest.setdefault(occurrence.rule_id, occurrence)
    return list(latest.values())


async def _owned_occurrence(
    db: AsyncSession,
    *,
    target_type: Literal["course", "learning_path"],
    occurrence_id: UUID,
    tenant_id: UUID,
) -> tuple[RecurringLearningAssignment | LearningPathCycleInstance, datetime | None]:
    if target_type == "course":
        row = (
            await db.execute(
                select(RecurringLearningAssignment, Enrollment.completed_at)
                .outerjoin(Enrollment, Enrollment.id == RecurringLearningAssignment.enrollment_id)
                .where(
                    RecurringLearningAssignment.id == occurrence_id,
                    RecurringLearningAssignment.tenant_id == tenant_id,
                )
                .with_for_update(of=RecurringLearningAssignment)
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Learning occurrence not found")
        return row[0], row[1]
    cycle = await db.scalar(
        select(LearningPathCycleInstance)
        .where(
            LearningPathCycleInstance.id == occurrence_id,
            LearningPathCycleInstance.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if cycle is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Learning occurrence not found")
    return cycle, cast(datetime | None, cycle.completed_at)


@router.get(
    "/occurrences/{target_type}/{occurrence_id}/events",
    response_model=list[ParticipantEventResponse],
)
async def list_occurrence_events(
    target_type: Literal["course", "learning_path"],
    occurrence_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(require_role("methodologist")),
) -> list[LearningCycleParticipantEvent]:
    await _owned_occurrence(
        db,
        target_type=target_type,
        occurrence_id=occurrence_id,
        tenant_id=user.tenant_id,
    )
    target_column = (
        LearningCycleParticipantEvent.course_occurrence_id
        if target_type == "course"
        else LearningCycleParticipantEvent.path_cycle_instance_id
    )
    return list(
        (
            await db.scalars(
                select(LearningCycleParticipantEvent)
                .where(
                    LearningCycleParticipantEvent.tenant_id == user.tenant_id,
                    target_column == occurrence_id,
                )
                .order_by(
                    LearningCycleParticipantEvent.created_at.desc(),
                    LearningCycleParticipantEvent.id.desc(),
                )
            )
        ).all()
    )


@router.post(
    "/occurrences/{target_type}/{occurrence_id}/deadline-override",
    response_model=OccurrenceResponse,
)
async def override_occurrence_deadline(
    target_type: Literal["course", "learning_path"],
    occurrence_id: UUID,
    body: DeadlineOverrideRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Any = Depends(require_role("methodologist")),
) -> OccurrenceResponse:
    occurrence, completed_at = await _owned_occurrence(
        db,
        target_type=target_type,
        occurrence_id=occurrence_id,
        tenant_id=user.tenant_id,
    )
    terminal = {"completed", "skipped"} if target_type == "course" else {"completed", "skipped", "cancelled"}
    if occurrence.status in terminal or completed_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A terminal occurrence deadline cannot be changed")
    if target_type == "course":
        earliest = cast(datetime, cast(RecurringLearningAssignment, occurrence).scheduled_for)
    else:
        path_occurrence = cast(LearningPathCycleInstance, occurrence)
        earliest = cast(datetime, path_occurrence.starts_at or path_occurrence.scheduled_for)
    if body.effective_due_at < earliest:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Deadline cannot precede occurrence start")
    previous = occurrence.effective_due_at or occurrence.due_at
    if previous is None or body.effective_due_at == previous:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Deadline must change")

    cast(Any, occurrence).effective_due_at = body.effective_due_at
    event = LearningCycleParticipantEvent(
        tenant_id=user.tenant_id,
        course_occurrence_id=occurrence.id if target_type == "course" else None,
        path_cycle_instance_id=occurrence.id if target_type == "learning_path" else None,
        user_id=occurrence.user_id,
        previous_effective_due_at=previous,
        effective_due_at=body.effective_due_at,
        reason=body.reason,
        actor_id=_rule_actor_id(user),
    )
    db.add(event)
    await db.flush()
    await db.execute(
        text("SELECT public.reschedule_learning_reminder(:tenant_id,:course_id,:path_id,:due_at)"),
        {
            "tenant_id": user.tenant_id,
            "course_id": occurrence.id if target_type == "course" else None,
            "path_id": occurrence.id if target_type == "learning_path" else None,
            "due_at": body.effective_due_at,
        },
    )
    await log_action(
        db,
        user.tenant_id,
        "learning_cycle.deadline_overridden",
        "learning_occurrence",
        resource_id=cast(UUID, occurrence.id),
        user_id=user.id,
        details={
            "target_type": target_type,
            "previous_effective_due_at": previous.isoformat(),
            "effective_due_at": body.effective_due_at.isoformat(),
            "reason": body.reason,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    learner = await db.scalar(
        select(User).where(
            User.id == occurrence.user_id,
            User.tenant_id == user.tenant_id,
        )
    )
    if learner is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Occurrence learner identity is unavailable")
    await db.commit()
    if target_type == "course":
        return _course_occurrence_response(
            cast(RecurringLearningAssignment, occurrence),
            completed_at,
            learner=learner,
        )
    return _path_occurrence_response(cast(LearningPathCycleInstance, occurrence), learner=learner)


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
            created_by=_rule_actor_id(user),
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
        created_by=_rule_actor_id(user),
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
    result = await sync_learning_path_rules(db, path=path, created_by=_rule_actor_id(user))
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
