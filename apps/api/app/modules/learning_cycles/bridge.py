"""Tenant-safe bridge between published LearningPaths and cycle rules."""

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.users import User
from app.modules.learning_cycles.models import RecurringLearningRule
from app.modules.learning_paths.models import LearningPath, LearningPathAssignment


@dataclass(frozen=True)
class PathRuleReconcileResult:
    rule: RecurringLearningRule | None
    action: str


@dataclass
class PathRuleSyncCounts:
    created: int = 0
    reconciled: int = 0
    skipped: int = 0
    total: int = 0


async def _active_student(db: AsyncSession, *, user_id: UUID, tenant_id: UUID) -> UUID | None:
    return cast(UUID | None, await db.scalar(
        select(User.id).where(
            User.id == user_id,
            User.tenant_id == tenant_id,
            User.role == "student",
            User.is_active.is_(True),
            User.status == "active",
        )
    ))


def _is_recurring_path(path: LearningPath) -> bool:
    return bool(
        path.status == "published"
        and path.recurrence_mode == "fixed_interval_after_completion"
        and path.recurrence_cadence_days is not None
        and path.recurrence_due_days is not None
    )


async def reconcile_learning_path_assignment(
    db: AsyncSession,
    *,
    path: LearningPath,
    user_id: UUID,
    created_by: UUID | None,
) -> PathRuleReconcileResult:
    """Create or source-reconcile one rule without changing its assignment."""
    if not _is_recurring_path(path):
        return PathRuleReconcileResult(rule=None, action="skipped")
    if await _active_student(db, user_id=user_id, tenant_id=cast(UUID, path.tenant_id)) is None:
        return PathRuleReconcileResult(rule=None, action="skipped")

    rule = await db.scalar(
        select(RecurringLearningRule).where(
            RecurringLearningRule.tenant_id == path.tenant_id,
            RecurringLearningRule.learning_path_id == path.id,
            RecurringLearningRule.user_id == user_id,
        )
    )
    if rule is None:
        candidate = RecurringLearningRule(
            tenant_id=path.tenant_id,
            learning_path_id=path.id,
            user_id=user_id,
            cadence_days=path.recurrence_cadence_days,
            due_days=path.recurrence_due_days,
            status="active",
            next_run_at=None,
            created_by=created_by,
        )
        try:
            async with db.begin_nested():
                db.add(candidate)
                await db.flush()
        except IntegrityError:
            rule = await db.scalar(
                select(RecurringLearningRule).where(
                    RecurringLearningRule.tenant_id == path.tenant_id,
                    RecurringLearningRule.learning_path_id == path.id,
                    RecurringLearningRule.user_id == user_id,
                )
            )
            if rule is None:
                raise
        else:
            return PathRuleReconcileResult(rule=candidate, action="created")

    rule.cadence_days = path.recurrence_cadence_days
    rule.due_days = path.recurrence_due_days
    return PathRuleReconcileResult(rule=rule, action="reconciled")


async def sync_learning_path_rules(
    db: AsyncSession,
    *,
    path: LearningPath,
    created_by: UUID | None,
) -> PathRuleSyncCounts:
    """Reconcile current assignments; never rewrite assignment history."""
    result = await db.execute(
        select(LearningPathAssignment).where(
            LearningPathAssignment.tenant_id == path.tenant_id,
            LearningPathAssignment.path_id == path.id,
        )
    )
    assignments = result.scalars().all()
    counts = PathRuleSyncCounts(total=len(assignments))
    for assignment in assignments:
        if assignment.status != "active":
            counts.skipped += 1
            continue
        outcome = await reconcile_learning_path_assignment(
            db,
            path=path,
            user_id=cast(UUID, assignment.user_id),
            created_by=created_by,
        )
        if outcome.action == "created":
            counts.created += 1
        elif outcome.action == "reconciled":
            counts.reconciled += 1
        else:
            counts.skipped += 1
    return counts
