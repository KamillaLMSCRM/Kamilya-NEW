# ruff: noqa: B008

from datetime import UTC, datetime
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
from app.modules.learning_cycles.models import RecurringLearningAssignment, RecurringLearningRule
from app.modules.learning_cycles.schemas import OccurrenceResponse, RuleCreate, RuleResponse, RuleUpdate

router = APIRouter(prefix="/learning-cycles", tags=["learning-cycles"])


def occurrence_reporting_status(*, stored_status: str, due_at, completed_at, now=None) -> str:
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
    user=Depends(require_role("methodologist")),
):
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
            course_id=occurrence.course_id,
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
    return list(latest.values())


@router.post("", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rule(
    body: RuleCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("methodologist")),
):
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
    if body.cadence_days is not None:
        rule.cadence_days = body.cadence_days
    if body.due_days is not None:
        rule.due_days = body.due_days
    return rule


@router.post("/{rule_id}/activate", response_model=RuleResponse)
async def activate(
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_role("methodologist")),
):
    rule = await _owned_rule(db, rule_id, user.tenant_id)
    course = await db.scalar(select(Course).where(Course.id == rule.course_id, Course.tenant_id == user.tenant_id))
    if course is None or course.status != "published" or course.delivery_type == "scorm":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only published native courses support recurring delivery")
    rule.status = "active"
    rule.next_run_at = rule.next_run_at or datetime.now(UTC)
    return rule


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
