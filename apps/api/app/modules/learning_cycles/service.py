"""Idempotent recurring native-course materialization."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.db import async_session_factory
from app.models.enrollment import Enrollment
from app.models.users import User
from app.modules.courses.release_service import ensure_course_release
from app.modules.enrollments.notification_outbox import queue_manual_enrollment_notification
from app.modules.learning_cycles.models import RecurringLearningAssignment, RecurringLearningRule
from app.modules.users.invitations_service import prepare_user_invitation

logger = logging.getLogger(__name__)


async def _set_tenant(db, tenant_id):
    await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)})


async def materialize_rule(rule_id: UUID, tenant_id: UUID, now=None):
    now = now or datetime.now(UTC)
    notification_id = None
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
        rule.last_run_at = scheduled_for
        rule.next_run_at = scheduled_for + timedelta(days=rule.cadence_days)
        await db.commit()

    if notification_id:
        try:
            from app.modules.enrollments.notification_tasks import deliver_assignment_notification_task

            deliver_assignment_notification_task.apply_async(args=[str(tenant_id), str(notification_id)])
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
