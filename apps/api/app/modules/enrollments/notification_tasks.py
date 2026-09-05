"""Celery delivery and bounded recovery for assignment notifications."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.db import async_session_factory
from app.core.email import EmailDeliveryError, EmailService
from app.models.courses import Course
from app.models.enrollment import Enrollment
from app.models.tenants import Tenant
from app.models.users import User, UserInvitation
from app.modules.enrollments.notification_outbox import (
    RECOVERY_BATCH_SIZE,
    PostgresAssignmentNotificationStore,
    PostgresLearningPathAssignmentNotificationStore,
)
from app.modules.learning_paths.models import LearningPath, LearningPathAssignment

TRANSIENT_EMAIL_CATEGORIES = frozenset(
    {
        "provider_timeout",
        "provider_unreachable",
        "provider_rate_limited",
        "provider_unavailable",
    }
)

logger = logging.getLogger(__name__)


async def _set_tenant_context(db: AsyncSession, tenant_id: UUID) -> None:
    await db.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)})


def _mark_invitation_attempt(invite: UserInvitation) -> None:
    writable = cast(Any, invite)
    writable.delivery_last_attempt_at = datetime.now(UTC)
    writable.delivery_attempt_count = (invite.delivery_attempt_count or 0) + 1
    writable.delivery_failure_category = None
    writable.delivery_failure_message = None


def _mark_invitation_failure(invite: UserInvitation, *, status: str, category: str, message: str) -> None:
    writable = cast(Any, invite)
    writable.delivery_status = status
    writable.delivery_failure_category = category[:64]
    writable.delivery_failure_message = message[:500]


def _mark_invitation_sent(invite: UserInvitation, message_id: str | None) -> None:
    writable = cast(Any, invite)
    writable.delivery_status = "sent"
    writable.delivery_message_id = message_id
    writable.delivery_failure_category = None
    writable.delivery_failure_message = None


async def _deliver(*, tenant_id: UUID, notification_id: UUID) -> dict[str, str]:
    async with async_session_factory() as db:
        await _set_tenant_context(db, tenant_id)
        store = PostgresAssignmentNotificationStore(db)
        item = await store.claim(tenant_id=tenant_id, notification_id=notification_id)
        if item is None:
            return {"status": "skipped"}

        # claim() commits, so transaction-local RLS context must be restored.
        await _set_tenant_context(db, tenant_id)
        row = (
            await db.execute(
                select(Enrollment, User, Course, Tenant.name)
                .join(User, User.id == Enrollment.user_id)
                .join(Course, Course.id == Enrollment.course_id)
                .join(Tenant, Tenant.id == Enrollment.tenant_id)
                .where(
                    Enrollment.id == item.enrollment_id,
                    Enrollment.tenant_id == tenant_id,
                    User.tenant_id == tenant_id,
                    Course.tenant_id == tenant_id,
                )
            )
        ).one_or_none()
        if row is None:
            await store.finalize(item, kind="terminal", error_category="enrollment_missing")
            return {"status": "dead"}

        _enrollment, learner, course, company_name = row
        if not learner.email or not learner.email.strip():
            await store.finalize(item, kind="terminal", error_category="email_missing")
            return {"status": "dead"}

        email = EmailService()
        if not email.delivery_ready():
            await store.finalize(item, kind="defer", error_category="configuration_missing")
            return {"status": "deferred"}

        settings = get_settings()
        base_url = settings.PUBLIC_URL.rstrip("/")
        activation_required = not learner.has_login_access
        invite = None
        if activation_required:
            invite = await db.scalar(
                select(UserInvitation)
                .where(
                    UserInvitation.tenant_id == tenant_id,
                    UserInvitation.user_id == learner.id,
                    UserInvitation.status == "pending",
                    UserInvitation.expires_at > datetime.now(UTC),
                )
                .order_by(UserInvitation.created_at.desc())
                .limit(1)
            )
            access_url = f"{base_url}/accept-invite?token={invite.token}" if invite else None
        else:
            access_url = f"{base_url}/courses/{course.id}"

        if access_url is None:
            await store.finalize(item, kind="terminal", error_category="activation_not_prepared")
            return {"status": "dead"}

        try:
            if invite is not None:
                _mark_invitation_attempt(invite)
            message_id = await email.send_course_assignment(
                to_email=learner.email,
                company_name=company_name,
                learner_name=f"{learner.first_name} {learner.last_name}".strip(),
                course_title=course.title,
                access_url=access_url,
                activation_required=activation_required,
                idempotency_key=f"course-assignment/{item.id}",
            )
        except EmailDeliveryError as exc:
            kind = "transient" if exc.category in TRANSIENT_EMAIL_CATEGORIES else "terminal"
            if invite is not None:
                _mark_invitation_failure(
                    invite,
                    status="pending" if kind == "transient" else "failed",
                    category=exc.category,
                    message=exc.message,
                )
            await store.finalize(item, kind=kind, error_category=exc.category)
            return {"status": kind}
        except Exception:
            if invite is not None:
                invite.delivery_status = "failed"
                invite.delivery_failure_category = "internal_error"
                invite.delivery_failure_message = "The assignment email could not be sent."
            await store.finalize(item, kind="terminal", error_category="internal_error")
            return {"status": "dead"}
        if invite is not None:
            invite.delivery_status = "sent"
            invite.delivery_message_id = message_id
            invite.delivery_failure_category = None
            invite.delivery_failure_message = None
        await store.finalize(item, kind="success", message_id=message_id)
        return {"status": "sent"}


async def _deliver_learning_path(*, tenant_id: UUID, notification_id: UUID) -> dict[str, str]:
    async with async_session_factory() as db:
        await _set_tenant_context(db, tenant_id)
        store = PostgresLearningPathAssignmentNotificationStore(db)
        item = await store.claim(tenant_id=tenant_id, notification_id=notification_id)
        if item is None:
            return {"status": "skipped"}

        # claim() commits, so transaction-local RLS context must be restored.
        await _set_tenant_context(db, tenant_id)
        row = (
            await db.execute(
                select(LearningPathAssignment, User, LearningPath, Tenant.name)
                .join(User, User.id == LearningPathAssignment.user_id)
                .join(LearningPath, LearningPath.id == LearningPathAssignment.path_id)
                .join(Tenant, Tenant.id == LearningPathAssignment.tenant_id)
                .where(
                    LearningPathAssignment.id == item.learning_path_assignment_id,
                    LearningPathAssignment.tenant_id == tenant_id,
                    LearningPathAssignment.status == "active",
                    User.tenant_id == tenant_id,
                    LearningPath.tenant_id == tenant_id,
                    LearningPath.status == "published",
                )
            )
        ).one_or_none()
        if row is None:
            await store.finalize(item, kind="terminal", error_category="assignment_missing")
            return {"status": "dead"}

        _assignment, learner, path, company_name = row
        if not learner.email or not learner.email.strip():
            await store.finalize(item, kind="terminal", error_category="email_missing")
            return {"status": "dead"}

        email = EmailService()
        if not email.delivery_ready():
            await store.finalize(item, kind="defer", error_category="configuration_missing")
            return {"status": "deferred"}

        base_url = get_settings().PUBLIC_URL.rstrip("/")
        program_url = f"{base_url}/learning-paths"
        activation_required = not learner.has_login_access
        invite = None
        if activation_required:
            invite = await db.scalar(
                select(UserInvitation)
                .where(
                    UserInvitation.tenant_id == tenant_id,
                    UserInvitation.user_id == learner.id,
                    UserInvitation.status == "pending",
                    UserInvitation.expires_at > datetime.now(UTC),
                )
                .order_by(UserInvitation.created_at.desc())
                .limit(1)
            )
            access_url = f"{base_url}/accept-invite?token={invite.token}" if invite else None
        else:
            access_url = program_url

        if access_url is None:
            await store.finalize(item, kind="terminal", error_category="activation_not_prepared")
            return {"status": "dead"}

        try:
            if invite is not None:
                invite.delivery_last_attempt_at = datetime.now(UTC)
                invite.delivery_attempt_count = (invite.delivery_attempt_count or 0) + 1
                invite.delivery_failure_category = None
                invite.delivery_failure_message = None
            message_id = await email.send_learning_path_assignment(
                to_email=learner.email,
                company_name=company_name,
                learner_name=f"{learner.first_name} {learner.last_name}".strip(),
                path_title=path.title,
                access_url=access_url,
                program_url=program_url,
                activation_required=activation_required,
                idempotency_key=f"learning-path-assignment/{item.id}",
            )
        except EmailDeliveryError as exc:
            kind = "transient" if exc.category in TRANSIENT_EMAIL_CATEGORIES else "terminal"
            if invite is not None:
                invite.delivery_status = "pending" if kind == "transient" else "failed"
                invite.delivery_failure_category = exc.category[:64]
                invite.delivery_failure_message = exc.message[:500]
            await store.finalize(item, kind=kind, error_category=exc.category)
            return {"status": kind}
        except Exception:
            if invite is not None:
                _mark_invitation_failure(
                    invite,
                    status="failed",
                    category="internal_error",
                    message="The program assignment email could not be sent.",
                )
            await store.finalize(item, kind="terminal", error_category="internal_error")
            return {"status": "dead"}
        if invite is not None:
            _mark_invitation_sent(invite, message_id)
        await store.finalize(item, kind="success", message_id=message_id)
        return {"status": "sent"}


async def recover_due_notifications(limit: int = RECOVERY_BATCH_SIZE) -> dict[str, int]:
    """Attempt one fair, globally bounded batch across both durable outboxes.

    ``succeeded`` counts items whose delivery handler completed and persisted
    its outcome, including terminal/deferred outcomes. ``failed`` counts only
    unhandled poison-item exceptions. One failed item never stops the batch.
    """
    bounded = max(1, min(limit, 100))
    recovery_url = get_settings().ASSIGNMENT_RECOVERY_DATABASE_URL
    if not recovery_url:
        raise RuntimeError("ASSIGNMENT_RECOVERY_DATABASE_URL is required for global notification recovery")
    recovery_engine = create_async_engine(recovery_url, poolclass=NullPool)
    recovery_sessions = async_sessionmaker(recovery_engine, expire_on_commit=False)
    try:
        async with recovery_sessions() as db:
            course_due = await PostgresAssignmentNotificationStore(db).due(bounded)
            learning_path_due = await PostgresLearningPathAssignmentNotificationStore(db).due(bounded)
    finally:
        await recovery_engine.dispose()
    plan = []
    for index in range(max(len(course_due), len(learning_path_due))):
        if index < len(course_due):
            plan.append(("course", course_due[index]))
        if len(plan) >= bounded:
            break
        if index < len(learning_path_due):
            plan.append(("learning_path", learning_path_due[index]))
        if len(plan) >= bounded:
            break

    attempted = 0
    succeeded = 0
    failed = 0
    for notification_kind, item in plan:
        attempted += 1
        delivery = _deliver_learning_path if notification_kind == "learning_path" else _deliver
        try:
            await delivery(tenant_id=item.tenant_id, notification_id=item.id)
        except Exception:
            failed += 1
            logger.exception(
                "Assignment notification recovery failed for %s item %s",
                notification_kind,
                item.id,
            )
            continue
        succeeded += 1
    # The existing broker-independent recovery entrypoint also services reminders.
    # Keep its result/counters and initial-assignment behavior compatible.
    if getattr(get_settings(), "LEARNING_REMINDERS_ENABLED", False):
        from app.modules.learning_reminders.tasks import recover_due_reminders

        await recover_due_reminders(limit=bounded)
    return {
        "due": len(plan),
        "processed": attempted,
        "attempted": attempted,
        "succeeded": succeeded,
        "failed": failed,
    }


@celery_app.task(name="enrollments.deliver_assignment_notification")
def deliver_assignment_notification_task(
    tenant_id: str, notification_id: str, notification_kind: str = "course"
) -> dict[str, str]:
    if notification_kind not in {"course", "learning_path"}:
        raise ValueError(f"Unsupported assignment notification kind: {notification_kind}")
    delivery = _deliver_learning_path if notification_kind == "learning_path" else _deliver
    return asyncio.run(delivery(tenant_id=UUID(tenant_id), notification_id=UUID(notification_id)))


@celery_app.task(name="enrollments.recover_assignment_notifications")
def recover_assignment_notifications_task() -> dict[str, int]:
    return asyncio.run(recover_due_notifications())
