"""Idempotent recurring native-course materialization."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.db import async_session_factory
from app.models.enrollment import Enrollment
from app.models.registry import load_all_models
from app.models.users import User
from app.modules.courses.release_service import ensure_course_release
from app.modules.enrollments.notification_outbox import (
    queue_learning_path_assignment_notification,
    queue_manual_enrollment_notification,
)
from app.modules.learning_cycles.models import (
    LearningPathCycleInstance,
    RecurringLearningAssignment,
    RecurringLearningRule,
)
from app.modules.learning_paths.models import LearningPath, LearningPathAssignment
from app.modules.learning_paths.service import sync_assignment_enrollments
from app.modules.users.invitations_service import prepare_user_invitation

load_all_models()

logger = logging.getLogger(__name__)


async def _set_tenant(db: AsyncSession, tenant_id: UUID) -> None:
    await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)})


async def _queue_reminder(db: AsyncSession, tenant_id: UUID, *, course_id: UUID | None = None, path_id: UUID | None = None) -> None:
    if not get_settings().LEARNING_REMINDERS_ENABLED:
        return
    await db.flush()
    await db.execute(
        text("SELECT public.enqueue_learning_reminder(:tid,:course,:path)"),
        {"tid": tenant_id, "course": course_id, "path": path_id},
    )


async def _materialize_path_rule(db, rule, *, scheduled_for, now) -> tuple[str, UUID | None]:
    """Materialize one immutable path occurrence inside the caller transaction."""
    path = await db.scalar(
        select(LearningPath).where(
            LearningPath.id == rule.learning_path_id,
            LearningPath.tenant_id == rule.tenant_id,
        )
    )
    learner = await db.scalar(
        select(User).where(
            User.id == rule.user_id,
            User.tenant_id == rule.tenant_id,
        )
    )

    # The rule row is locked by materialize_rule. The scheduled-time lookup is
    # an additional idempotency guard for repaired/imported rows; the database
    # sequence uniqueness remains the final duplicate protection.
    existing_cycle = await db.scalar(
        select(LearningPathCycleInstance).where(
            LearningPathCycleInstance.tenant_id == rule.tenant_id,
            LearningPathCycleInstance.rule_id == rule.id,
            LearningPathCycleInstance.scheduled_for == scheduled_for,
        )
    )
    if existing_cycle is not None:
        return "already_materialized", None

    sequence_no = (
        await db.scalar(
            select(func.max(LearningPathCycleInstance.sequence_no)).where(
                LearningPathCycleInstance.tenant_id == rule.tenant_id,
                LearningPathCycleInstance.rule_id == rule.id,
            )
        )
        or 0
    ) + 1
    due_at = scheduled_for + timedelta(days=rule.due_days)
    valid_target = path is not None and path.status == "published"
    valid_learner = (
        learner is not None
        and learner.role == "student"
        and learner.is_active is True
        and learner.status == "active"
    )

    # A skipped cycle is retained when the referenced rows exist but are no
    # longer eligible. Foreign keys and the ownership trigger make a cycle for
    # a completely missing or cross-tenant target impossible to persist. Do
    # not consume that run as if materialization succeeded: deactivate the
    # invalid rule and return an explicit safe result.
    if path is None or learner is None:
        rule.status = "inactive"
        logger.warning(
            "Recurring learning-path rule %s has an unmaterializable target or learner",
            rule.id,
        )
        return ("missing_path" if path is None else "missing_learner"), None

    cycle = LearningPathCycleInstance(
        tenant_id=rule.tenant_id,
        rule_id=rule.id,
        path_id=path.id,
        user_id=learner.id,
        sequence_no=sequence_no,
        scheduled_for=scheduled_for,
        starts_at=scheduled_for,
        due_at=due_at,
        status="active" if valid_target and valid_learner else "skipped",
    )
    db.add(cycle)
    await db.flush()
    if not valid_target or not valid_learner:
        return "skipped", None

    # Clearing before sync lets an immediately-completed assignment schedule
    # the next run from its completion timestamp. An active assignment leaves
    # the field NULL until its first completion.
    rule.next_run_at = None
    assignment = LearningPathAssignment(
        tenant_id=rule.tenant_id,
        path_id=path.id,
        user_id=learner.id,
        source="recurring",
        assigned_by=rule.created_by,
        starts_at=scheduled_for,
        due_at=due_at,
        status="active",
        recurrence_instance_id=cycle.id,
    )
    db.add(assignment)
    await db.flush()
    await sync_assignment_enrollments(db, assignment, now=now)
    if learner.email and not learner.has_login_access:
        await prepare_user_invitation(
            db,
            rule.tenant_id,
            rule.created_by,
            learner.id,
            get_settings().PUBLIC_URL,
            reuse_valid=True,
        )
    notification_id = await queue_learning_path_assignment_notification(
        db,
        tenant_id=rule.tenant_id,
        learning_path_assignment_id=assignment.id,
        assigned_by=rule.created_by,
    )
    await _queue_reminder(db, rule.tenant_id, path_id=cycle.id)
    return "materialized", notification_id


async def materialize_rule(rule_id: UUID, tenant_id: UUID, now=None):
    now = now or datetime.now(UTC)
    notification_id = None
    notification_kind = "course"
    async with async_session_factory() as db:
        await _set_tenant(db, tenant_id)
        rule = await db.scalar(
            select(RecurringLearningRule)
            .where(
                RecurringLearningRule.id == rule_id,
                RecurringLearningRule.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        if not rule or rule.status != "active" or not rule.next_run_at or rule.next_run_at > now:
            return {"status": "skipped"}
        scheduled_for = rule.next_run_at
        if rule.learning_path_id is not None:
            path_result, notification_id = await _materialize_path_rule(
                db, rule, scheduled_for=scheduled_for, now=now
            )
            if path_result in {"missing_path", "missing_learner"}:
                await db.commit()
                return {"status": "skipped", "reason": path_result}
            notification_kind = "learning_path"
            rule.last_run_at = scheduled_for
            if rule.next_run_at == scheduled_for:
                rule.next_run_at = None
        else:
            # Keep native course recurrence behavior unchanged.
            occurrence = await db.scalar(
                select(RecurringLearningAssignment).where(
                    RecurringLearningAssignment.rule_id == rule.id,
                    RecurringLearningAssignment.scheduled_for == scheduled_for,
                )
            )
            if occurrence is None:
                occurrence = RecurringLearningAssignment(
                    tenant_id=tenant_id,
                    rule_id=rule.id,
                    user_id=rule.user_id,
                    course_id=rule.course_id,
                    scheduled_for=scheduled_for,
                    due_at=scheduled_for + timedelta(days=rule.due_days),
                    status="assigned",
                )
                db.add(occurrence)
                await db.flush()
                learner = await db.scalar(
                    select(User).where(
                        User.id == rule.user_id,
                        User.tenant_id == tenant_id,
                        User.role == "student",
                        User.is_active.is_(True),
                        User.status == "active",
                    )
                )
                from app.models.courses import Course

                course = await db.scalar(
                    select(Course).where(
                        Course.id == rule.course_id,
                        Course.tenant_id == tenant_id,
                        Course.status == "published",
                        Course.delivery_type != "scorm",
                    )
                )
                if learner is None or course is None:
                    occurrence.status = "skipped"
                else:
                    release = await ensure_course_release(db, course)
                    enrollment = Enrollment(
                        tenant_id=tenant_id,
                        user_id=learner.id,
                        course_id=course.id,
                        content_release_id=release.id,
                        status="enrolled",
                        source="recurring",
                        recurring_assignment_id=occurrence.id,
                    )
                    db.add(enrollment)
                    await db.flush()
                    occurrence.enrollment_id = enrollment.id
                    if learner.email and not learner.has_login_access:
                        await prepare_user_invitation(
                            db, tenant_id, rule.created_by, learner.id, get_settings().PUBLIC_URL, reuse_valid=True
                        )
                    notification_id = await queue_manual_enrollment_notification(
                        db, tenant_id=tenant_id, enrollment_id=enrollment.id, assigned_by=rule.created_by
                    )
                    await _queue_reminder(db, tenant_id, course_id=occurrence.id)
            rule.last_run_at = scheduled_for
            rule.next_run_at = scheduled_for + timedelta(days=rule.cadence_days)
        await db.commit()

    if notification_id:
        try:
            from app.modules.enrollments.notification_tasks import deliver_assignment_notification_task

            dispatch_kwargs = {"notification_kind": notification_kind} if notification_kind != "course" else {}
            deliver_assignment_notification_task.apply_async(
                args=[str(tenant_id), str(notification_id)], kwargs=dispatch_kwargs
            )
        except Exception:
            logger.warning("Recurring notification dispatch failed; outbox recovery will retry", exc_info=True)
    return {"status": "materialized", "notification_id": str(notification_id) if notification_id else None}


async def recover_due(limit=20):
    recovery_url = get_settings().ASSIGNMENT_RECOVERY_DATABASE_URL
    if not recovery_url:
        raise RuntimeError("ASSIGNMENT_RECOVERY_DATABASE_URL is required for global recurring recovery")
    recovery_engine = create_async_engine(recovery_url, poolclass=NullPool)
    sessions = async_sessionmaker(recovery_engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            rows = (
                (
                    await db.execute(
                        text("SELECT * FROM due_recurring_learning_rules(:limit)"),
                        {"limit": max(1, min(limit, 100))},
                    )
                )
                .mappings()
                .all()
            )
    finally:
        await recovery_engine.dispose()
    processed = 0
    for row in rows:
        try:
            await materialize_rule(row["id"], row["tenant_id"])
            processed += 1
        except Exception:
            logger.exception("Recurring rule materialization failed for %s", row["id"])
    return {"due": len(rows), "processed": processed}
